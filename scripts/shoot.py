"""Render a film's shots when the engines live on two servers that cannot coexist.

    python scripts/shoot.py --plan shots.json --dry-run
    python scripts/shoot.py --plan shots.json                # render, resumable
    python scripts/shoot.py --plan shots.json --only windows # one pass only
    python scripts/shoot.py --status --plan shots.json

The problem this exists for
---------------------------

A film here needs both engines. LTX renders the ambient shots on **Windows**;
Wan renders the ones that need authored motion, and Wan lives in **WSL** because
that is 33% faster and where its weights now are. Both servers may run at once, but **two video renders cannot**: GPU memory is
system RAM (63.6 GiB) and a video job peaks near 43 GiB on either platform, so
two will not fit however the processes are arranged
(`wiki/comfyui/two-platforms.md`).

So a shoot is still **one pass per platform**, and what gates each pass is
measured free memory rather than whether the other server exists. Doing that by
hand across 37 shots is how a batch ends up half-rendered with nobody sure
which half.

What this does
--------------

Groups the shots by the platform their engine needs, renders each group with
only that server running, and records every result as it lands. Re-running skips
what already exists, so an interrupted shoot resumes instead of restarting - and
an hour-long video batch *will* be interrupted.

It refuses rather than freeing or stopping anything itself: dropping someone's
loaded models unasked is not this script's business, and it says which endpoint
to call instead.

The plan file
-------------

A JSON list. `engine` decides the platform; everything else is passed through::

    [
      {"id": "sc01", "engine": "ltx",     "workflow": "...json", "output": "sc01.mp4"},
      {"id": "sc16", "engine": "wan_flf", "workflow": "...json", "output": "sc16.mp4",
       "inputs": {"start_image": "a.png", "end_image": "b.png"}}
    ]
"""

from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from lib.comfy_routing import (  # noqa: E402
    free_gib, is_wan, PEAK_GIB, wan_server, which_platform, windows_server,
)
from lib.machine_paths import project_dir  # noqa: E402

#: Which platform each engine needs. An engine absent here is assumed to be a
#: Wan variant if its name says so, and Windows otherwise.
ENGINE_PLATFORM = {
    "ltx": "windows",
    "sdxl": "windows",
    "flux": "windows",
    "zimage": "windows",
    "klein": "windows",
    "wan": "wsl",
    "wan_i2v": "wsl",
    "wan_t2v": "wsl",
    "wan_flf": "wsl",
    "wan_animate": "wsl",
    "scail": "wsl",
}


def platform_for(shot: dict) -> str:
    engine = str(shot.get("engine", "")).lower()
    if engine in ENGINE_PLATFORM:
        return ENGINE_PLATFORM[engine]
    if is_wan(engine) or is_wan(str(shot.get("workflow", ""))):
        return "wsl"
    return "windows"


def server_for_platform(platform: str) -> str:
    return wan_server() if platform == "wsl" else windows_server()


def server_up(url: str) -> bool:
    try:
        urllib.request.urlopen(f"{url}/system_stats", timeout=5)
        return True
    except Exception:
        return False


def check_capacity(platform: str) -> str | None:
    """None when it is safe to render, else why it is not.

    Both servers are allowed to run (Raul, 2026-08-30). What is checked is
    memory: a video job on either platform peaked around 43 GiB when it was
    measured, and GPU memory here is system RAM, so two of them at once cannot
    fit in 63.6 GiB however the processes are arranged. The old rule refused on
    server count, which blocked the many combinations that do fit.
    """
    want = server_for_platform(platform)

    if not server_up(want):
        how = ("scripts/start_comfyui_wsl.sh" if platform == "wsl"
               else "scripts/start_comfyui_windows.ps1")
        return f"the {platform} server at {want} is not running - start it with {how}"

    seen = which_platform(want)
    if seen not in (platform, "unknown"):
        return (f"{want} reports itself as {seen}, not {platform}. Comfy Desktop "
                "reassigns ports; check which server is really there.")

    need = PEAK_GIB[("video", platform)]
    free = free_gib()
    if free is not None and free < need + 4.0:
        other = server_for_platform("wsl" if platform == "windows" else "windows")
        hint = (f" The other server at {other} is up - POST to its /free endpoint "
                "to drop its models without stopping it."
                if server_up(other) else " Close what else is resident.")
        return (f"only {free} GiB free; a video render on {platform} peaked at "
                f"{need} GiB when measured.{hint}")
    return None


def submit(server: str, graph: dict, out_path: Path, timeout_s: int) -> dict:
    start = time.time()
    req = urllib.request.Request(f"{server}/prompt",
                                 data=json.dumps({"prompt": graph}).encode(),
                                 headers={"Content-Type": "application/json"})
    try:
        pid = json.loads(urllib.request.urlopen(req, timeout=120).read())["prompt_id"]
    except urllib.error.HTTPError as exc:
        return {"ok": False, "error": exc.read().decode(errors="replace")[:400]}

    while time.time() - start < timeout_s:
        try:
            hist = json.loads(urllib.request.urlopen(
                f"{server}/history/{pid}", timeout=60).read())
            if pid in hist:
                break
        except Exception:
            pass
        time.sleep(5)
    else:
        # The render keeps going after we stop waiting; say so rather than
        # letting a resume submit the same work twice.
        return {"ok": False, "error": f"still running after {timeout_s}s", "prompt_id": pid}

    entry = hist[pid]
    for node in (entry.get("outputs") or {}).values():
        for kind in ("videos", "gifs", "images"):
            for item in node.get(kind) or []:
                q = urllib.parse.urlencode({
                    "filename": item["filename"], "subfolder": item.get("subfolder", ""),
                    "type": item.get("type", "output")})
                out_path.parent.mkdir(parents=True, exist_ok=True)
                out_path.write_bytes(urllib.request.urlopen(
                    f"{server}/view?{q}", timeout=1800).read())
                return {"ok": True, "seconds": round(time.time() - start, 1),
                        "path": str(out_path), "prompt_id": pid}
    return {"ok": False, "error": "completed but wrote no file", "prompt_id": pid}


def load_graph(shot: dict, repo: Path) -> dict:
    wf = Path(shot["workflow"])
    if not wf.is_absolute():
        wf = repo / wf
    graph = json.loads(wf.read_text(encoding="utf-8"))
    for node_id, fields in (shot.get("patch") or {}).items():
        graph.setdefault(node_id, {}).setdefault("inputs", {}).update(fields)
    return graph


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--plan", type=Path, required=True, help="JSON list of shots")
    ap.add_argument("--project", default=None)
    ap.add_argument("--only", choices=("windows", "wsl"), default=None,
                    help="render just one platform's pass")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--status", action="store_true")
    ap.add_argument("--timeout", type=int, default=5400, help="seconds per shot")
    args = ap.parse_args()

    project = project_dir(args.project)
    repo = Path(__file__).resolve().parents[1]
    plan_path = args.plan if args.plan.is_absolute() else (project / args.plan)
    shots = json.loads(plan_path.read_text(encoding="utf-8"))
    out_root = project / "assets" / "video"
    ledger = project / "artifacts" / "shoot_log.jsonl"

    passes: dict[str, list[dict]] = {"windows": [], "wsl": []}
    for shot in shots:
        passes[platform_for(shot)].append(shot)

    def done(shot: dict) -> bool:
        p = out_root / shot.get("output", f"{shot['id']}.mp4")
        return p.exists() and p.stat().st_size > 1024

    print(f"{len(shots)} shots: "
          f"{len(passes['windows'])} on Windows, {len(passes['wsl'])} in WSL")
    for platform in ("windows", "wsl"):
        group = passes[platform]
        if not group:
            continue
        left = [s for s in group if not done(s)]
        print(f"  {platform:8} {len(group):3} shots, {len(left):3} still to render"
              f"  -> {server_for_platform(platform)}")
    if args.status or args.dry_run:
        print("\nEach pass needs its own server running and the other stopped.")
        return 0

    for platform in ("windows", "wsl"):
        group = [s for s in passes[platform] if not done(s)]
        if not group or (args.only and args.only != platform):
            continue

        print(f"\n=== {platform} pass: {len(group)} shot(s) ===")
        problem = check_capacity(platform)
        if problem:
            print(f"  SKIPPED - {problem}")
            continue

        server = server_for_platform(platform)
        for shot in group:
            out = out_root / shot.get("output", f"{shot['id']}.mp4")
            graph = load_graph(shot, repo)
            if platform == "wsl":
                from lib.comfy_routing import to_wsl_paths
                graph, n = to_wsl_paths(graph)
                if n:
                    print(f"  {shot['id']}: translated {n} path(s) for WSL")
            print(f"  {shot['id']} ({shot.get('engine', '?')}) ...", end="", flush=True)
            r = submit(server, graph, out, args.timeout)
            r.update(id=shot["id"], engine=shot.get("engine"), platform=platform)
            ledger.parent.mkdir(parents=True, exist_ok=True)
            with ledger.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(r) + "\n")
            print(f" {r['seconds']}s" if r.get("ok") else f" FAILED: {str(r.get('error'))[:70]}")

    remaining = [s for g in passes.values() for s in g if not done(s)]
    print(f"\n{len(shots) - len(remaining)}/{len(shots)} rendered. "
          f"Log: {ledger}")
    if remaining:
        by = {}
        for s in remaining:
            by[platform_for(s)] = by.get(platform_for(s), 0) + 1
        print("still to do: " + ", ".join(f"{n} on {p}" for p, n in by.items())
              + " - switch servers and run again.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
