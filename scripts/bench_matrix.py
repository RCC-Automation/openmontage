"""Run the full platform matrix and print one comparison table.

    python scripts/bench_matrix.py --quick        # image + ltx, ~30 min
    python scripts/bench_matrix.py --full         # adds wan, ~3.5 h
    python scripts/bench_matrix.py --report       # re-print from saved results

Three workflows on two servers, three runs each, on a quiet machine. Both
servers must be up: Windows on 8188, WSL on 8189.

**There is no backend variable.** `TORCH_ROCM_FA_PREFER_CK=1` was the lever
worth testing - AMD measured +50% on Strix Halo with it - but PyTorch refuses it
on this GPU on *both* platforms: "architecture supported for CK: 0". flash-attn
has no gfx1151 wheel, and AMD measured SageAttention at -34% to -36% on this
hardware. AOTriton is the only backend available to us, so the only variable
left is the platform itself.

Order matters: the cheap discriminating workflows run first, so a clear result
on image and LTX can stop the expensive Wan runs before they start.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from lib.machine_paths import project_dir, repo_root  # noqa: E402

REPO = repo_root()
SUITE = Path(__file__).resolve().parent / "bench_suite.py"
OUT: Path  # set in main(), once the project is known

PLATFORMS = [("windows", 8188), ("wsl", 8189)]
#: (workflow, extra args, rough minutes per run) - cheapest first.
PLAN = [
    ("image", ["--width", "1280", "--height", "720"], 0.4),
    ("ltx", [], 4.5),
    ("video", ["--frames", "81", "--width", "640", "--height", "640"], 27.0),
]


def up(port: int) -> bool:
    try:
        urllib.request.urlopen(f"http://127.0.0.1:{port}/system_stats", timeout=8)
        return True
    except Exception:
        return False


def idle(port: int) -> bool:
    try:
        q = json.loads(urllib.request.urlopen(f"http://127.0.0.1:{port}/queue", timeout=8).read())
        return not q.get("queue_running") and not q.get("queue_pending")
    except Exception:
        return False


def report() -> None:
    rows = []
    for f in sorted(OUT.glob("*_*.json")):
        try:
            d = json.loads(f.read_text(encoding="utf-8"))
        except Exception:
            continue
        if "workflow" not in d:
            continue
        rows.append(d)
    if not rows:
        print("no results yet")
        return

    by_wf: dict[str, dict] = {}
    for d in rows:
        by_wf.setdefault(d["workflow"], {})[d.get("platform", d["label"])] = d

    print(f"\n{'workflow':8} {'platform':9} {'cold':>8} {'warm':>8} {'sample':>8} "
          f"{'peakRSS':>8} {'stable':>7}  output")
    print("-" * 78)
    for wf in ("image", "ltx", "video"):
        for plat in ("windows", "wsl"):
            d = by_wf.get(wf, {}).get(plat)
            if not d:
                continue
            ok = d["runs_detail"][0].get("check", {}) if d.get("runs_detail") else {}
            shape = (f"{ok.get('width','?')}x{ok.get('height','?')}"
                     + (f" {ok['frames']}f" if ok.get("frames") else ""))
            print(f"{wf:8} {plat:9} {str(d.get('cold_s','-')):>8} "
                  f"{str(d.get('warm_mean_s','-')):>8} {str(d.get('sample_mean_s','-')):>8} "
                  f"{str(d.get('peak_rss_gib','-')):>8} {str(d.get('stable')):>7}  {shape}")
        w = by_wf.get(wf, {}).get("windows")
        l = by_wf.get(wf, {}).get("wsl")
        if w and l and w.get("warm_mean_s") and l.get("warm_mean_s"):
            d = 100 * (w["warm_mean_s"] - l["warm_mean_s"]) / w["warm_mean_s"]
            faster = "WSL" if d > 0 else "Windows"
            print(f"{'':8} {'-> ':>9} {faster} faster by {abs(d):.1f}% on warm runs")
    print()
    for wf in ("image", "ltx", "video"):
        for plat in ("windows", "wsl"):
            d = by_wf.get(wf, {}).get(plat)
            fr = (d or {}).get("free") or {}
            if fr:
                print(f"  {wf}/{plat}: /free released {fr.get('vram_released_gib','?')} GiB VRAM")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--full", action="store_true", help="include the 81-frame Wan runs")
    ap.add_argument("--quick", action="store_true", help="image and ltx only")
    ap.add_argument("--runs", type=int, default=3)
    ap.add_argument("--report", action="store_true")
    ap.add_argument("--project", default=None, help="project id for the results directory")
    args = ap.parse_args()

    global OUT
    OUT = project_dir(args.project) / "scene_look" / "bench-suite"
    OUT.mkdir(parents=True, exist_ok=True)

    if args.report:
        report()
        return 0

    plan = PLAN if args.full else PLAN[:2]
    for name, port in PLATFORMS:
        if not up(port):
            print(f"{name} on {port} is not responding - start it first")
            return 1
        if not idle(port):
            print(f"{name} on {port} is busy - a benchmark on a busy machine measures nothing")
            return 1

    est = sum(m * args.runs for _, _, m in plan) * len(PLATFORMS)
    print(f"{len(plan)} workflows x {len(PLATFORMS)} platforms x {args.runs} runs "
          f"~ {est:.0f} min\n")

    for wf, extra, _ in plan:
        for name, port in PLATFORMS:
            label = f"{name}-{wf}"
            print(f"--- {label} " + "-" * (60 - len(label)))
            cmd = [sys.executable, "-u", str(SUITE), "--workflow", wf,
                   "--port", str(port), "--label", name, "--runs", str(args.runs)]
            if args.project:
                cmd += ["--project", args.project]
            subprocess.run(cmd + extra, cwd=str(REPO))
    report()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
