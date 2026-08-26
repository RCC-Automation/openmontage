"""Show every version of the character so a human can cast one.

    python scripts/anchor_chooser.py
    python scripts/anchor_chooser.py --pick 12      # promote #12 to be the anchor

The seed is the variant generator: one prompt across 48 seeds is 48 different
women, because on this model the seed and not the description decides who she is
(DECISIONS #29). Phase 2 measured that population; this shows it, numbered, so
the choice is made by the person who has to like the result.

**The machine narrows, the human casts** (DECISIONS #15). What the clustering
adds is not taste, it is *reproducibility*: a version with six near-siblings is a
better anchor than an equally good one-off, because the siblings are evidence the
model can hit that face again and they drop straight into the dataset as extra
close-ups. So each tile carries its sibling count. It is a tiebreaker between
faces you like, never a reason to take one you do not.

The count is **this render's own**, not its cluster's size. Reporting cluster
size put "15 siblings" under every member of a 15-member cluster including the
ones sitting at its edge, which is the sort of number that reads as measured and
is not. Here a sibling is another render whose ArcFace cosine to this one clears
`SIBLING_AT`, counted per image.
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from lib.sheets import ACCENTS, SheetItem, labelled_sheet  # noqa: E402

#: Raw ArcFace cosine above which two renders count as the same face for the
#: sibling tally. Calibrated against this machine's populations: genuinely
#: different people sit at 0.10-0.21 and one character across seeds at 0.36-0.67,
#: so 0.55 sits well clear of the negatives while staying reachable - the
#: dataset's own 0.80 accept band would score every render zero siblings, since
#: no description-only pair in the 48 got near it.
SIBLING_AT = 0.55


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project", default="character-lora")
    parser.add_argument(
        "--label", default="anchor",
        help="Which sweep to choose from, matching anchor_select's --label.",
    )
    parser.add_argument("--pick", type=int, default=None, help="Tile number to promote.")
    parser.add_argument("--columns", type=int, default=6)
    parser.add_argument("--cell", type=int, default=340)
    parser.add_argument("--sibling-at", type=float, default=SIBLING_AT)
    args = parser.parse_args()

    anchor_root = ROOT / "projects" / args.project / args.label
    report_path = anchor_root / "anchor_report.json"
    if not report_path.is_file():
        print(f"FAIL: no Phase 2 report at {report_path}")
        return 1
    report = json.loads(report_path.read_text(encoding="utf-8"))

    data = np.load(anchor_root / "embeddings.npz")
    paths = [Path(p) for p in data["paths"]]
    seeds = [int(s) for s in data["seeds"]]
    # Present only when the sweep embedded the largest face of multi-face
    # renders; a bystander in frame is worth knowing before picking an anchor.
    bystanders = [int(b) for b in data["bystanders"]] if "bystanders" in data else [0] * len(paths)

    # Cluster label and size per render, so a tile can say how reproducible its
    # face is without the reader opening the report.
    label_of: dict[int, int] = {}
    size_of: dict[int, int] = {}
    for cluster in report["selection"]["clusters"]:
        for member in cluster["members"]:
            label_of[member] = cluster["label"]
            size_of[member] = cluster["size"]
    medoid_of = {
        cluster["medoid"]: cluster["label"]
        for cluster in report["selection"]["clusters"]
        if cluster["medoid"] is not None
    }

    # Per-render sibling tally and nearest neighbour. Both are about this image,
    # so a version at the edge of a big cluster reports honestly instead of
    # inheriting its cluster's headcount.
    vectors = np.asarray(data["vectors"], dtype=np.float32)
    gram = vectors @ vectors.T
    np.fill_diagonal(gram, -1.0)
    siblings = (gram >= args.sibling_at).sum(axis=1)
    nearest = gram.max(axis=1)

    if args.pick is not None:
        if not 1 <= args.pick <= len(paths):
            print(f"FAIL: --pick must be 1..{len(paths)}")
            return 1
        chosen = paths[args.pick - 1]
        target = anchor_root / "anchor.png"
        shutil.copyfile(chosen, target)
        # The cast is recorded beside the anchor: which tile, which seed, and
        # that a human chose it rather than the clustering. Phase 3 reads the
        # image; the next person reads this.
        (anchor_root / "anchor_choice.json").write_text(
            json.dumps(
                {
                    "tile": args.pick,
                    "seed": seeds[args.pick - 1],
                    "source": str(chosen),
                    "anchor": str(target),
                    "cluster": label_of.get(args.pick - 1),
                    "cluster_size": size_of.get(args.pick - 1),
                    "siblings": int(siblings[args.pick - 1]),
                    "sibling_threshold": args.sibling_at,
                    "nearest_cosine": round(float(nearest[args.pick - 1]), 4),
                    "decided_by": "human",
                },
                indent=2,
            ),
            encoding="utf-8",
        )
        print(f"anchor set from tile {args.pick} (seed {seeds[args.pick - 1]})")
        print(f"  {chosen}")
        print(f"  -> {target}")
        return 0

    items = []
    for index, path in enumerate(paths):
        label = label_of.get(index, -1)
        mark = " *" if index in medoid_of else ""
        extra = f"  +{bystanders[index]} in frame" if bystanders[index] else ""
        items.append(
            SheetItem(
                path,
                f"{index + 1}.  seed {seeds[index]}",
                f"{int(siblings[index])} sib  near {nearest[index]:.2f}{mark}{extra}",
                ACCENTS[label % len(ACCENTS)] if label >= 0 else None,
            )
        )

    sheet = labelled_sheet(
        items,
        anchor_root / "sheets" / "choose.png",
        columns=args.columns,
        cell=args.cell,
        title=(
            f"{report['character']} - {len(items)} versions from {len(items)} seeds. "
            f"sib = other renders within {args.sibling_at:g} ArcFace cosine of THIS one; "
            "near = closest of all. Border = cluster. * = cluster's most typical. Pick by number."
        ),
    )
    print(f"chooser: {sheet}")

    # Phone-sized parts, split on row boundaries. The geometry mirrors
    # lib/sheets.labelled_sheet: title 30, pad 8, each row cell + 32 + 8 tall.
    # Splitting at half height cut a row of faces through the middle, which is
    # the one thing a chooser must not do.
    if sheet is not None:
        try:
            from PIL import Image

            with Image.open(sheet) as whole:
                row_h = args.cell + 32 + 8
                top = 8 + 30
                rows = (len(items) + args.columns - 1) // args.columns
                per_part = 4
                for part, first_row in enumerate(range(0, rows, per_part), start=1):
                    y0 = top + first_row * row_h - 8 if first_row else 0
                    last_row = min(rows, first_row + per_part)
                    y1 = top + last_row * row_h
                    piece = whole.crop((0, y0, whole.width, min(y1, whole.height)))
                    piece.save(sheet.parent / f"choose_{part}.png")
                print(f"parts  : {sheet.parent / 'choose_1.png'} .. choose_{part}.png ({per_part} rows each)")
        except Exception as exc:
            print(f"(could not split the sheet: {exc})")
    order = np.argsort(-siblings)
    print(f"\nmost reproducible versions (siblings at cosine >= {args.sibling_at:g}):")
    for rank in order[:8]:
        print(
            f"  #{rank + 1:<3} seed {seeds[rank]}  "
            f"{int(siblings[rank]):>2} siblings, nearest {nearest[rank]:.3f}"
        )
    print(f"\n{len(items)} versions. Promote one with:")
    print("  python scripts/anchor_chooser.py --pick <number>")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
