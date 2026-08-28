"""Run the image benchmark: one prompt across every installed model.

    python workflows/image-bench/run_bench.py --out projects/image-bench
    python workflows/image-bench/run_bench.py --only zimage,klein
    python workflows/image-bench/run_bench.py --export-graphs

Renders are ordered so the two memory-heavy Flux files never share residency
(system RAM is 63.6 GiB with --disable-mmap; loading them together killed the
backend on 2026-08-28), and the seed varies per cell because ComfyUI returns a
cached non-render for a byte-identical graph.
"""

from __future__ import annotations

import argparse
import ctypes
import json
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from graphs import MODELS, build  # noqa: E402

SRV = "http://127.0.0.1:8188"

PROMPT = ("A close-up portrait photograph of a woman in her thirties with freckled skin and "
          "copper hair, lit by a single soft window light from the left, catchlights in her "
          "eyes, shallow depth of field, shot on an 85mm lens at f/1.8, natural skin texture "
          "with visible pores, calm direct gaze.")
NEGATIVE = "blurry, low quality, deformed, plastic skin, oversaturated, watermark"


class _MemStatus(ctypes.Structure):
    _fields_ = [("dwLength", ctypes.c_ulong), ("dwMemoryLoad", ctypes.c_ulong),
                ("ullTotalPhys", ctypes.c_ulonglong), ("ullAvailPhys", ctypes.c_ulonglong),
                ("ullTotalPageFile", ctypes.c_ulonglong), ("ullAvailPageFile", ctypes.c_ulonglong),
                ("ullTotalVirtual", ctypes.c_ulonglong), ("ullAvailVirtual", ctypes.c_ulonglong),
                ("ullAvailExtendedVirtual", ctypes.c_ulonglong)]


def ram_free_gib() -> float:
    m = _MemStatus()
    m.dwLength = ctypes.sizeof(_MemStatus)
    ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(m))
    return m.ullAvailPhys / 2 ** 30


def flush() -> None:
    try:
        req = urllib.request.Request(
            SRV + "/free", data=json.dumps({"unload_models": True, "free_memory": True}).encode(),
            headers={"Content-Type": "application/json"})
        urllib.request.urlopen(req, timeout=180).read()
        time.sleep(4)
    except Exception as exc:  # a flush that fails is a warning, not a stop
        print(f"    flush failed: {exc}")


def submit(graph: dict, out_dir: Path, stem: str, timeout_s: int = 1800) -> dict | None:
    try:
        q = json.load(urllib.request.urlopen(SRV + "/queue", timeout=15))
    except Exception as exc:
        print(f"    ABORT: ComfyUI unreachable ({exc})")
        return None
    if len(q.get("queue_running", [])) + len(q.get("queue_pending", [])):
        print("    SKIP: queue busy")
        return None
    started = time.time()
    try:
        req = urllib.request.Request(
            SRV + "/prompt", data=json.dumps({"prompt": graph, "client_id": "image-bench"}).encode(),
            headers={"Content-Type": "application/json"})
        pid = json.load(urllib.request.urlopen(req, timeout=60))["prompt_id"]
    except urllib.error.HTTPError as exc:
        print(f"    FAIL on submit: {exc.read().decode()[:400]}")
        return None
    while True:
        if time.time() - started > timeout_s:
            print(f"    TIMEOUT after {timeout_s}s")
            return None
        time.sleep(3)
        try:
            hist = json.load(urllib.request.urlopen(f"{SRV}/history/{pid}", timeout=120))
        except Exception:
            print(f"    LOST: backend died after {time.time() - started:.0f}s")
            return None
        if pid in hist:
            break
    seconds = time.time() - started
    entry = hist[pid]
    if not entry.get("status", {}).get("completed", True):
        msgs = json.dumps(entry.get("status", {}).get("messages", []))[-400:]
        print(f"    FAIL: {msgs}")
        return None
    saved = None
    for _nid, out in entry.get("outputs", {}).items():
        for image in out.get("images", []):
            qs = urllib.parse.urlencode({"filename": image["filename"],
                                         "subfolder": image.get("subfolder", ""),
                                         "type": image.get("type", "output")})
            dest = out_dir / f"{stem}.png"
            dest.write_bytes(urllib.request.urlopen(f"{SRV}/view?{qs}", timeout=300).read())
            saved = str(dest)
    return {"seconds": round(seconds, 1), "image": saved}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--out", default="projects/image-bench")
    ap.add_argument("--width", type=int, default=1280)
    ap.add_argument("--height", type=int, default=720)
    ap.add_argument("--seed", type=int, default=7777)
    ap.add_argument("--prompt", default=PROMPT)
    ap.add_argument("--negative", default=NEGATIVE)
    ap.add_argument("--only", default="", help="comma-separated families or keys")
    ap.add_argument("--export-graphs", action="store_true",
                    help="write each graph as API JSON and exit without rendering")
    ap.add_argument("--resume", action="store_true",
                    help="skip models whose PNG already exists, keeping seeds stable")
    args = ap.parse_args()

    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    wanted = {w.strip() for w in args.only.split(",") if w.strip()}
    pool = [m for m in MODELS if not wanted or m["family"] in wanted or m["key"] in wanted]

    # heavy files last, so nothing else is resident when they load
    pool.sort(key=lambda m: (bool(m.get("heavy")), m["family"]))

    common = dict(prompt=args.prompt, negative=args.negative,
                  width=args.width, height=args.height)

    if args.export_graphs:
        gdir = out_dir / "graphs"
        gdir.mkdir(exist_ok=True)
        for spec in pool:
            g = build(spec, seed=args.seed, prefix=f"bench/{spec['key']}", **common)
            (gdir / f"{spec['key']}.json").write_text(json.dumps(g, indent=1), encoding="utf-8")
        print(f"wrote {len(pool)} graphs to {gdir}")
        return 0

    results = []
    print(f"{len(pool)} models | {args.width}x{args.height} | host RAM free {ram_free_gib():.1f} GiB\n")
    for index, spec in enumerate(pool, 1):
        # Resume keeps the FULL pool so `index` - and therefore every seed - is
        # unchanged; only the rendering is skipped. Filtering the pool instead
        # would renumber the survivors and silently reseed them.
        existing = out_dir / f"{spec['key']}.png"
        if args.resume and existing.is_file():
            print(f"[{index:2}/{len(pool)}] {spec['label']:38} already rendered, skipping")
            results.append({**{k: spec[k] for k in ("key", "label", "family", "steps", "cfg", "source")},
                            "seconds": 0.0, "image": str(existing), "seed": args.seed + index,
                            "resumed": True})
            continue
        if spec.get("heavy"):
            flush()
        seed = args.seed + index  # vary per cell: an identical graph returns a cached non-render
        graph = build(spec, seed=seed, prefix=f"bench/{spec['key']}", **common)
        print(f"[{index:2}/{len(pool)}] {spec['label']:38} {spec['family']:7} "
              f"{spec['steps']:>2}st cfg{spec['cfg']:<4} ({spec['source']})")
        got = submit(graph, out_dir, spec["key"])
        if got:
            print(f"    {got['seconds']:7.1f}s   RAM free {ram_free_gib():.1f} GiB")
            results.append({**{k: spec[k] for k in ("key", "label", "family", "steps", "cfg", "source")},
                            **got, "seed": seed})
        else:
            results.append({**{k: spec[k] for k in ("key", "label", "family")}, "failed": True})
    (out_dir / "results.json").write_text(json.dumps(results, indent=1), encoding="utf-8")
    ok = [r for r in results if not r.get("failed")]
    print(f"\n{len(ok)}/{len(results)} rendered -> {out_dir}")
    for r in sorted(ok, key=lambda r: r["seconds"]):
        print(f"  {r['seconds']:7.1f}s  {r['label']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
