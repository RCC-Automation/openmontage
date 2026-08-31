"""Collect an in-flight render, then finish the remaining shots. Run detached.

    Start-Process .venv\\Scripts\\python.exe scripts\\finish_shots.py ...

A submitted prompt outlives whatever submitted it, and long renders here outlive
the shell that starts them - three background runners were killed mid-render
during this shoot without losing a single frame, because the work was always on
the server. This is the piece that survives on its own: it attaches to a prompt
already in flight, waits for it, then renders what is left and delivers
everything into the Builder project.

Every id is used in full. A prompt id truncated to 8 characters matches nothing
on `/history/<id>`, so a finished render reads as still-running forever - that
cost an hour on sc01.
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from lib.machine_paths import project_dir, repo_root  # noqa: E402


def resolve(server: str, pid: str) -> str | None:
    """A prefix is enough; a truncated id on its own is not."""
    if len(pid) >= 36:
        return pid
    try:
        h = json.loads(urllib.request.urlopen(f"{server}/history", timeout=60).read())
        hits = [k for k in h if k.startswith(pid)]
        if hits:
            return hits[0]
    except Exception:
        pass
    try:
        q = json.loads(urllib.request.urlopen(f"{server}/queue", timeout=30).read())
        for bucket in ("queue_running", "queue_pending"):
            for item in q.get(bucket) or []:
                if str(item[1]).startswith(pid):
                    return str(item[1])
    except Exception:
        pass
    return None


def fetch(server: str, pid: str, dest: Path, minutes: float) -> dict:
    start = time.time()
    while time.time() - start < minutes * 60:
        try:
            h = json.loads(urllib.request.urlopen(
                f"{server}/history/{pid}", timeout=60).read())
            if pid in h:
                e = h[pid]
                for node in (e.get("outputs") or {}).values():
                    for kind in ("videos", "gifs", "images"):
                        for it in node.get(kind) or []:
                            if not str(it["filename"]).endswith(".mp4"):
                                continue
                            q = urllib.parse.urlencode({
                                "filename": it["filename"],
                                "subfolder": it.get("subfolder", ""),
                                "type": it.get("type", "output")})
                            dest.parent.mkdir(parents=True, exist_ok=True)
                            dest.write_bytes(urllib.request.urlopen(
                                f"{server}/view?{q}", timeout=1800).read())
                            msgs = {m[0]: m[1] for m in
                                    (e.get("status") or {}).get("messages", [])}
                            took = None
                            if "execution_start" in msgs and "execution_success" in msgs:
                                took = round((msgs["execution_success"]["timestamp"]
                                              - msgs["execution_start"]["timestamp"]) / 1000, 1)
                            return {"ok": True, "seconds": took, "path": str(dest)}
                return {"ok": False,
                        "error": (e.get("status") or {}).get("status_str") or "no video"}
        except Exception:
            pass
        time.sleep(15)
    return {"ok": False, "error": f"not finished after {minutes:.0f} min"}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--project", default=None)
    ap.add_argument("--server", default="http://127.0.0.1:8189")
    ap.add_argument("--collect", nargs=2, metavar=("SCENE", "PROMPT_ID"),
                    help="a render already in flight, e.g. sc02 ea4d0b3b")
    ap.add_argument("--then", nargs="*", default=[],
                    help="scene ids to render after that")
    ap.add_argument("--builder", default=None)
    ap.add_argument("--minutes", type=float, default=90.0)
    args = ap.parse_args()

    project = project_dir(args.project)
    out = project / "assets" / "video"
    plan = json.loads((project / "artifacts" / "scene_plan.json").read_text(encoding="utf-8"))
    order = [s["id"] for s in plan["scenes"]]
    done: list[str] = []

    if args.collect:
        sid, raw = args.collect
        pid = resolve(args.server, raw)
        print(f"{sid}: {raw} -> {pid}", flush=True)
        if pid:
            r = fetch(args.server, pid, out / f"{sid}.mp4", args.minutes)
            print(f"{sid}: {r}", flush=True)
            if r.get("ok"):
                done.append(sid)

    if args.then:
        cmd = [sys.executable, str(repo_root() / "scripts" / "render_shots.py"),
               "--project", project.name, "--only", *args.then,
               "--server", args.server]
        print("running:", " ".join(cmd), flush=True)
        subprocess.run(cmd, cwd=str(repo_root()))
        done += [s for s in args.then if (out / f"{s}.mp4").exists()]

    if args.builder:
        target = Path(args.builder) / "rendered_scene_videos"
        target.mkdir(parents=True, exist_ok=True)
        for sid in dict.fromkeys(done):
            src = out / f"{sid}.mp4"
            if src.exists():
                dst = target / f"scene_{order.index(sid) + 1:04d}.mp4"
                shutil.copyfile(src, dst)
                print(f"delivered {sid} -> {dst}", flush=True)

    print("finished:", ", ".join(done) or "nothing", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
