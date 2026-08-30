"""Measure LTX's two passes properly, by reading the progress bar.

    python scripts/ltx_pass_cost.py --upscale off
    python scripts/ltx_pass_cost.py --upscale on

Settles three claims the wiki currently makes and cannot support:

  - "at 1920x1080 the second pass never completed"  -- killed at 2.5 h is not
    the same as never completes
  - "the refine pass is 24x more expensive per step"
  - the per-clip cost of LTX at all, which rests on one render from film 1

All three came from waiting for output instead of reading `s/it`. This runs the
**known-good generator workflow** - the one with 15 finished clips behind it -
scaled down so both passes can be observed cheaply, and reports the seconds per
step of each pass from the Desktop wrapper log.

The wrapper log is the instrument. `ComfyUI/user/comfyui.log` does not carry the
progress bar; `ComfyUI-Installs/ComfyUI/logs/comfyui.log` does. Getting that
wrong is what produced three false conclusions in one day.
"""

from __future__ import annotations

import argparse
import glob
import json
import re
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from lib.comfy_routing import windows_server  # noqa: E402
from lib.machine_paths import comfy_install_dir, project_dir, repo_root, scratch_dir  # noqa: E402

REPO = repo_root()
SRV = windows_server()          # LTX runs on Windows; Wan is routed to WSL
SCRATCH = scratch_dir()
OUT: Path                       # set in main(), once the project is known

#: The **Desktop wrapper** log is the one that carries the progress bar; the
#: Python log under ComfyUI/user does not. Reading the wrong one is what
#: produced three false "deadlock" conclusions on 2026-08-29.
_install = comfy_install_dir()
WRAPPER = (_install / "logs" / "comfyui.log") if _install else Path("comfyui.log")

#: `12%|##3   | 1/8 [24:46<2:53:26, 1486.59s/it]` and its it/s counterpart.
STEP = re.compile(r"(\d+)/(\d+)\s*\[[^\]]*?,\s*([\d.]+)(s/it|it/s)")


def patch_size(graph: dict, width: int, height: int, frames: int | None) -> None:
    """The generator's own node ids: 736:425 width, 736:426 height, 736:424 fps."""
    for nid, val in (("736:425", width), ("736:426", height)):
        if nid in graph:
            graph[nid]["inputs"]["value"] = val
    if frames:
        for n in graph.values():
            if n.get("class_type") == "EmptyLTXVLatentVideo":
                if not isinstance(n["inputs"].get("length"), list):
                    n["inputs"]["length"] = frames


def passes(text: str) -> list[dict]:
    """Split the progress lines into passes by watching the denominator change."""
    out: list[dict] = []
    for m in STEP.finditer(text):
        cur, total, rate, unit = int(m.group(1)), int(m.group(2)), float(m.group(3)), m.group(4)
        secs = rate if unit == "s/it" else (1.0 / rate if rate else 0.0)
        if not out or out[-1]["steps"] != total or cur < out[-1]["last"]:
            out.append({"steps": total, "last": cur, "rate": secs})
        else:
            out[-1]["last"], out[-1]["rate"] = cur, secs
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--upscale", choices=("on", "off"), default="off")
    ap.add_argument("--width", type=int, default=640)
    ap.add_argument("--height", type=int, default=640)
    ap.add_argument("--frames", type=int, default=None)
    ap.add_argument("--minutes", type=float, default=90.0)
    args = ap.parse_args()

    folder = "ltx_upscale_on" if args.upscale == "on" else "ltx_known_good"
    files = glob.glob(str(SCRATCH / folder / "i2v_scene_0005*.json"))
    if not files:
        raise SystemExit(f"no generated workflow in {SCRATCH / folder}")
    graph = json.loads(Path(files[0]).read_text(encoding="utf-8"))
    patch_size(graph, args.width, args.height, args.frames)
    OUT.mkdir(parents=True, exist_ok=True)

    mark = WRAPPER.stat().st_size if WRAPPER.exists() else 0
    start = time.time()
    req = urllib.request.Request(f"{SRV}/prompt", data=json.dumps({"prompt": graph}).encode(),
                                 headers={"Content-Type": "application/json"})
    try:
        pid = json.loads(urllib.request.urlopen(req, timeout=120).read())["prompt_id"]
    except urllib.error.HTTPError as exc:
        print("REJECTED:", exc.read().decode(errors="replace")[:600])
        return 1
    print(f"upscale {args.upscale} at {args.width}x{args.height}, prompt {pid[:8]}\n")

    seen = 0
    while time.time() - start < args.minutes * 60:
        try:
            with WRAPPER.open("rb") as f:
                f.seek(mark)
                tail = f.read().decode("utf-8", "replace")
        except OSError:
            tail = ""
        found = passes(tail)
        # Report each pass the first time it shows a rate, so a long run is
        # informative while it is still running rather than only at the end.
        for i, p in enumerate(found):
            if i >= seen:
                print(f"  pass {i+1}: {p['steps']} steps, first rate {p['rate']:.1f} s/step "
                      f"-> {p['steps']*p['rate']/60:.1f} min projected", flush=True)
                seen = i + 1
        try:
            hist = json.loads(urllib.request.urlopen(f"{SRV}/history/{pid}", timeout=60).read())
            if pid in hist:
                break
        except Exception:
            pass
        time.sleep(10)
    else:
        print(f"\nno result after {args.minutes:.0f} min - interrupting")
        urllib.request.urlopen(urllib.request.Request(
            f"{SRV}/interrupt", data=b"", headers={"Content-Type": "application/json"}), timeout=60)
        hist = {}

    with WRAPPER.open("rb") as f:
        f.seek(mark)
        tail = f.read().decode("utf-8", "replace")
    found = passes(tail)
    elapsed = round(time.time() - start, 1)

    saved = None
    if pid in hist:
        for node in (hist[pid].get("outputs") or {}).values():
            for kind in ("videos", "gifs", "images"):
                for item in node.get(kind) or []:
                    q = urllib.parse.urlencode({
                        "filename": item["filename"], "subfolder": item.get("subfolder", ""),
                        "type": item.get("type", "output")})
                    dest = OUT / f"ltx_upscale_{args.upscale}{Path(item['filename']).suffix}"
                    dest.write_bytes(urllib.request.urlopen(
                        f"{SRV}/view?{q}", timeout=900).read())
                    saved = dest
                    break
                if saved:
                    break
            if saved:
                break

    print(f"\n{'pass':>6} {'steps':>6} {'s/step':>9} {'minutes':>9}")
    for i, p in enumerate(found, 1):
        print(f"{i:>6} {p['steps']:>6} {p['rate']:>9.1f} {p['steps']*p['rate']/60:>9.1f}")
    if len(found) >= 2 and found[0]["rate"]:
        print(f"\nrefine is {found[1]['rate']/found[0]['rate']:.1f}x the base pass per step")
    print(f"\ntotal {elapsed}s ({elapsed/60:.1f} min) -> {saved}")

    (OUT / f"ltx_pass_cost_{args.upscale}.json").write_text(json.dumps({
        "upscale": args.upscale, "width": args.width, "height": args.height,
        "seconds": elapsed, "passes": found, "path": str(saved) if saved else None,
        "prompt_id": pid}, indent=2), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
