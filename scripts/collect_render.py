"""Wait for a ComfyUI prompt that is already running, and save its output.

    python scripts/collect_render.py --server http://127.0.0.1:8189 --out clip.mp4
    python scripts/collect_render.py --prompt-id e47e7cf9-... --out clip.mp4

A submitted prompt keeps executing after the script that submitted it exits.
That is usually a good thing - a long video render survives an interrupted
runner - but it leaves the output stranded in ComfyUI's history with nobody
fetching it, and a naive re-run queues the same work again behind it.

With no `--prompt-id`, this attaches to whatever is currently running.

Run it detached if the wait is long:

    Start-Process powershell -WindowStyle Hidden -ArgumentList `
      '-Command',"python scripts/collect_render.py --out x.mp4"
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from lib.comfy_routing import wan_server, windows_server  # noqa: E402


def running_prompt(server: str) -> str | None:
    try:
        q = json.loads(urllib.request.urlopen(f"{server}/queue", timeout=20).read())
        r = q.get("queue_running") or []
        return r[0][1] if r else None
    except Exception:
        return None


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--server", default=None, help="default: the Wan server")
    ap.add_argument("--prompt-id", default=None, help="default: whatever is running")
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--minutes", type=float, default=120.0)
    args = ap.parse_args()

    server = (args.server or wan_server()).rstrip("/")
    pid = args.prompt_id or running_prompt(server)
    if not pid:
        print(f"nothing running on {server} and no --prompt-id given")
        return 1

    print(f"waiting on {pid} at {server}", flush=True)

    start = time.time()
    while time.time() - start < args.minutes * 60:
        try:
            # A prefix is resolved EVERY pass, not once at the start. Resolving
            # only at the start fails for the normal case: the prompt is still
            # running, so it is not in /history yet, the id stays short, and the
            # loop then polls /history/<short id> which can never match. That
            # read as "still running" for a render that had finished.
            if len(pid) < 36:
                allh = json.loads(urllib.request.urlopen(
                    f"{server}/history", timeout=60).read())
                hits = [k for k in allh if k.startswith(pid)]
                if hits:
                    print(f"  {pid} -> {hits[0]}", flush=True)
                    pid = hits[0]
            if len(pid) >= 36:
                hist = json.loads(urllib.request.urlopen(
                    f"{server}/history/{pid}", timeout=60).read())
                if pid in hist:
                    break
        except Exception:
            pass
        time.sleep(10)
    else:
        print(f"still running after {args.minutes:.0f} min")
        return 1

    entry = hist[pid]
    status = (entry.get("status") or {}).get("status_str")
    msgs = {m[0]: m[1] for m in (entry.get("status") or {}).get("messages", [])}
    took = None
    if "execution_start" in msgs and "execution_success" in msgs:
        took = round((msgs["execution_success"]["timestamp"]
                      - msgs["execution_start"]["timestamp"]) / 1000, 1)

    for node in (entry.get("outputs") or {}).values():
        for kind in ("videos", "gifs", "images"):
            for item in node.get(kind) or []:
                q = urllib.parse.urlencode({
                    "filename": item["filename"], "subfolder": item.get("subfolder", ""),
                    "type": item.get("type", "output")})
                args.out.parent.mkdir(parents=True, exist_ok=True)
                args.out.write_bytes(urllib.request.urlopen(
                    f"{server}/view?{q}", timeout=1800).read())
                probe = ""
                try:
                    r = subprocess.run(
                        ["ffprobe", "-v", "error", "-select_streams", "v:0",
                         "-show_entries", "stream=width,height,nb_frames,r_frame_rate",
                         "-of", "csv=p=0", str(args.out)],
                        capture_output=True, text=True, timeout=120)
                    probe = r.stdout.strip()
                except Exception:
                    pass
                print(f"{status} in {took}s -> {args.out}  [{probe}]")
                return 0

    print(f"{status}, but no output file was produced")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
