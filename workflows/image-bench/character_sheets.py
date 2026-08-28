"""Contact sheets for a character bench, with the identity score on every cell.

    python workflows/image-bench/character_sheets.py --dir projects/burningman/model-bench

The score is ArcFace cosine against the approved anchor. It is printed on every
cell because the whole point of a character sweep is that "best picture" and
"most like her" are different questions with different winners.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from lib.sheets import ACCENTS, SheetItem, labelled_sheet  # noqa: E402

# Bands measured on this machine - wiki/character/measuring-identity.md
GOOD, FAIR = 0.70, 0.45


def _accent(r: dict) -> tuple[int, int, int] | None:
    """Green when it is really her, amber a family resemblance, red somebody
    else - and GREY when the face is too small for the number to mean anything.
    A cosine off a 0.4%-of-frame face is noise that looks like a measurement."""
    score = r.get("identity")
    if score is None:
        return (110, 110, 120)
    if not r.get("measurable", True):
        return (110, 110, 120)
    if score >= GOOD:
        return (140, 214, 132)
    if score >= FAIR:
        return (232, 186, 96)
    return (232, 106, 122)


def _sub(r: dict) -> str:
    score, frac = r.get("identity"), r.get("face_fraction")
    face = "" if frac is None else f" · face {frac * 100:.1f}%"
    if score is None:
        return f"no face found{face}"
    if not r.get("measurable", True):
        return f"({score:.3f}) NOT MEASURABLE{face}"
    return f"identity {score:.3f}{face}"


def build(run_dir: Path, anchor: Path, out_dir: Path, cell: int = 430) -> list[Path]:
    rows = json.loads((run_dir / "results.json").read_text(encoding="utf-8"))
    rows = [r for r in rows if (run_dir / f"{r['key']}.png").is_file()]
    out_dir.mkdir(parents=True, exist_ok=True)
    made: list[Path] = []

    def sheet(items, name, title, columns=5, c=cell):
        dest = out_dir / name
        if labelled_sheet(items, dest, columns=columns, cell=c, title=title):
            made.append(dest)

    anchor_item = [SheetItem(path=anchor, caption="THE ANCHOR", subcaption="who she is supposed to be",
                             accent=(106, 176, 232))] if anchor.is_file() else []

    # 1. prompt-only, ranked by identity
    prompt_only = sorted([r for r in rows if r.get("mode") == "prompt only"],
                         key=lambda r: (not r.get("measurable", False), -(r.get("identity") or -1)))
    sheet(anchor_item + [SheetItem(path=run_dir / f"{r['key']}.png", caption=r["label"],
                                   subcaption=_sub(r), accent=_accent(r))
                         for r in prompt_only],
          "char_prompt_only.png",
          "Her description alone, across every model - ranked by how much it is actually her",
          columns=5, c=330)

    # 2. the identity mechanisms
    mechanisms = sorted([r for r in rows if r.get("mode") in ("conditioned", "swapped")],
                        key=lambda r: (not r.get("measurable", False), -(r.get("identity") or -1)))
    if mechanisms:
        sheet(anchor_item + [SheetItem(path=run_dir / f"{r['key']}.png", caption=r["label"],
                                       subcaption=_sub(r), accent=_accent(r))
                             for r in mechanisms],
              "char_mechanisms.png",
              "Identity mechanisms - reference conditioning, a trained LoRA, and a face swap",
              columns=min(4, len(mechanisms) + 1))

    # 3. the headline: best picture vs best likeness
    scored = [r for r in rows if r.get("identity") is not None and r.get("measurable")]
    if scored:
        best_id = max(scored, key=lambda r: r["identity"])
        best_prompt = max([r for r in scored if r.get("mode") == "prompt only"],
                          key=lambda r: r["identity"], default=None)
        picks = [r for r in (best_prompt, best_id) if r]
        seen, uniq = set(), []
        for r in picks:
            if r["key"] not in seen:
                seen.add(r["key"])
                uniq.append(r)
        sheet(anchor_item + [SheetItem(path=run_dir / f"{r['key']}.png", caption=r["label"],
                                       subcaption=_sub(r), accent=_accent(r))
                             for r in uniq],
              "char_verdict.png",
              "The anchor, the best a description alone can do, and the best any mechanism does",
              columns=min(3, len(uniq) + 1), c=470)
    return made


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--dir", default="projects/burningman/model-bench")
    ap.add_argument("--anchor", default="projects/burningman/anchor/anchor.png")
    ap.add_argument("--out", default="projects/burningman/model-bench/sheets")
    args = ap.parse_args()
    for p in build(Path(args.dir), Path(args.anchor), Path(args.out)):
        print(p)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
