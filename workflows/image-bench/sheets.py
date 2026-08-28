"""Turn a benchmark run into contact sheets a human can judge.

    python workflows/image-bench/sheets.py --dir projects/image-bench

One sheet per family (2-7 columns, readable), plus a cross-family sheet. Prints
the recipe and the wall-clock under every cell, because a comparison where the
settings vary is only honest if it says so.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from lib.sheets import SheetItem, labelled_sheet  # noqa: E402

FAMILY_TITLE = {
    "sdxl": "SDXL — 7 checkpoints, each at its own recipe",
    "zimage": "Z-Image — 5 Turbo-derived merges and the Base model",
    "klein": "FLUX.2 Klein — distilled vs Base",
    "flux1": "Flux.1 — dev and the all-in-one",
    "chroma": "Chroma",
}


def _secs(r: dict) -> str:
    return "not timed" if not r.get("seconds") else f"{r['seconds']:.0f}s"


def _sub(r: dict) -> str:
    return f"{r['steps']}st cfg {r['cfg']:g} · {_secs(r)} · {r['source']}"


def build(run_dir: Path, out_dir: Path, cell: int = 430) -> list[Path]:
    results = json.loads((run_dir / "results.json").read_text(encoding="utf-8"))
    ok = [r for r in results if not r.get("failed") and (run_dir / f"{r['key']}.png").is_file()]
    out_dir.mkdir(parents=True, exist_ok=True)
    made: list[Path] = []

    by_family: dict[str, list[dict]] = {}
    for r in ok:
        by_family.setdefault(r["family"], []).append(r)

    for family, rows in by_family.items():
        rows.sort(key=lambda r: r["seconds"] or 1e9)
        items = [SheetItem(path=run_dir / f"{r['key']}.png", caption=r["label"],
                           subcaption=_sub(r))
                 for r in rows]
        dest = out_dir / f"family_{family}.png"
        if labelled_sheet(items, dest, columns=min(4, len(items)), cell=cell,
                          title=FAMILY_TITLE.get(family, family)):
            made.append(dest)

    # one representative per family, fastest first, for the cross-family view
    picks = [min(rows, key=lambda r: r["seconds"] or 1e9) for rows in by_family.values()]
    picks.sort(key=lambda r: r["seconds"] or 1e9)
    items = [SheetItem(path=run_dir / f"{r['key']}.png", caption=r["label"],
                       subcaption=f"{r['family']} · {_secs(r)}")
             for r in picks]
    dest = out_dir / "cross_family.png"
    if labelled_sheet(items, dest, columns=min(5, len(items)), cell=cell,
                      title="One per family — the cheapest good option in each"):
        made.append(dest)

    # everything, small, ranked by speed
    allrows = sorted(ok, key=lambda r: r["seconds"] or 1e9)
    items = [SheetItem(path=run_dir / f"{r['key']}.png", caption=r["label"],
                       subcaption=_secs(r))
             for r in allrows]
    dest = out_dir / "all_models.png"
    if labelled_sheet(items, dest, columns=5, cell=330,
                      title=f"All {len(allrows)} models — same prompt, 1280x720, fastest first"):
        made.append(dest)
    return made


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--dir", default="projects/image-bench")
    ap.add_argument("--out", default="projects/image-bench/sheets")
    ap.add_argument("--cell", type=int, default=430)
    args = ap.parse_args()
    made = build(Path(args.dir), Path(args.out), cell=args.cell)
    for p in made:
        print(p)
    return 0 if made else 1


if __name__ == "__main__":
    raise SystemExit(main())
