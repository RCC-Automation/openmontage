"""Steps 3 and 4 of the character workflow: generate candidates, then curate.

    python scripts/dataset_klein.py --project burningman                      # generate ~60, sheet them
    python scripts/dataset_klein.py --project burningman --pick close_up=1,4,7 medium=2,5 wide=3 variation=1

Every candidate is generated from the three masters and nothing else - the
face for close-ups, the face plus the matching full-body master for wider
framings - on FLUX.2 Klein's multi-reference route. Never from a previous
candidate: identity errors compound down a chain, which is how the ladder
produced one usable image in 144.

Each render is scored against the face master (ArcFace, raw cosine) and
measured for framing (face box as a share of the frame), and every candidate
lands on a numbered sheet per family. **The scores sort; they do not decide.**
You pick, per family, by number - rejecting a narrower face, different eyes, a
different age, a hairstyle that changed, a bystander, or skin that stopped
looking photographed. The picks become `dataset/accepted/` and `dataset.json`
with each image's descriptor (shot, angle, expression, background, lighting)
kept for captioning.

Quotas follow lib/character_dataset.LADDER; `--multiplier` sets how many
candidates per wanted image (1.7 gives ~60 for a 36-image target).
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
import time
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from lib.character_dataset import LADDER, balance, plan_dataset  # noqa: E402
from lib.face_identity import faces_in  # noqa: E402
from lib.sheets import ACCENTS, SheetItem, labelled_sheet  # noqa: E402
from scripts.masters import KLEIN, _reference_guard  # noqa: E402
from tools._comfyui.client import ComfyUIClient  # noqa: E402
from tools._comfyui.vrgdg import VRGDGClient, node_class_types  # noqa: E402

SEED_MAX = 18_446_744_073_709_551_615


def _face(path: Path) -> tuple[int, np.ndarray | None, float | None]:
    """Count, the LARGEST face's vector, its share of the frame (see masters.py)."""
    found = faces_in(path)
    if not found:
        return 0, None, None
    vector = getattr(found[0], "normed_embedding", None)
    share = None
    try:
        from PIL import Image

        with Image.open(path) as handle:
            frame = float(handle.width * handle.height)
        x1, y1, x2, y2 = found[0].bbox
        share = float(abs((x2 - x1) * (y2 - y1)) / frame) if frame else None
    except Exception:
        pass
    return len(found), (None if vector is None else np.asarray(vector, dtype=np.float32)), share


#: Backgrounds for an outdoor festival character. The defaults in
#: lib/character_dataset are the clockwork heroine's (workshops, orreries) and
#: would be absurd here. Every image gets a different one so nothing constant
#: is learned as part of her - and none of them contains other people.
FESTIVAL_BACKGROUNDS: tuple[str, ...] = (
    "on the open desert playa, flat dust to the horizon, nobody else in sight",
    "in front of a giant wooden effigy under construction, empty ground around her",
    "beside a parked art car covered in mirrors, deserted",
    "against a wall of shipping containers painted with murals, alone",
    "on a dune at dawn, pale sky, no one around",
    "under a shade structure of white fabric, empty",
    "beside a row of colourful bicycles leaning on a rail, nobody near",
    "in front of a geodesic dome tent, alone",
    "at the edge of a dust storm, figures far away and blurred out",
    "on cracked salt flats at midday, empty in every direction",
    "beside a tall LED light tower at dusk, deserted",
    "in front of a hand-painted sign on plywood, empty lot",
    "in an empty camp of tents and camping chairs, no one else",
    "against the bare metal of a water truck, alone",
    "on the playa at night lit by a single string of bulbs, nobody else",
    "in front of a wooden temple structure, empty steps",
    "beside a scaffold tower with prayer flags, deserted",
    "under a clear evening sky with the first stars, alone",
)

#: Appended to every prompt. A training set that keeps showing her with a
#: crowd teaches the LoRA the crowd; the recommendation's own rule is that an
#: image with another person in it is rejected.
SOLO = "she is alone in the frame, no other people"


def _references(family: str, angle: str, masters: dict) -> list[str]:
    """Which masters condition this family. Close-ups: the face only.

    Wider framings add the body master whose view is nearest the requested
    angle, so the reference always matches the framing as closely as the
    three masters allow - the workaround for reference collapse across
    framings, done with masters instead of a promoted chain.
    """
    face = masters["face"]
    if family == "close_up":
        return [face]
    body = masters["body_front"] if "straight on" in angle or "front" in angle else masters["body_three_quarter"]
    return [face, body]


def _payload(prompt: str, seed: int, refs: list[str], width: int, height: int) -> dict:
    return {
        **KLEIN,
        "prompt": prompt,
        "seed": int(seed),
        "seed_mode": "fixed",
        "width": width,
        "height": height,
        "images": [{"path": str(Path(r).resolve())} for r in refs],
    }


def _sheet_parts(sheet: Path, columns: int, cell: int, n_items: int, per_part: int = 4) -> list[Path]:
    """Phone-sized parts split on row boundaries, as anchor_chooser does."""
    try:
        from PIL import Image
    except Exception:
        return []
    parts: list[Path] = []
    with Image.open(sheet) as whole:
        row_h = cell + 32 + 8
        top = 8 + 30
        rows = (n_items + columns - 1) // columns
        for part, first in enumerate(range(0, rows, per_part), start=1):
            y0 = top + first * row_h - 8 if first else 0
            y1 = min(whole.height, top + min(rows, first + per_part) * row_h)
            out = sheet.with_name(f"{sheet.stem}_{part}.png")
            whole.crop((0, y0, whole.width, y1)).save(out)
            parts.append(out)
    return parts


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project", required=True)
    parser.add_argument("--brief", default=None, help="Defaults to masters.json's brief.")
    parser.add_argument("--multiplier", type=float, default=1.7, help="Candidates per wanted image.")
    parser.add_argument("--seed", type=int, default=424242, help="Seeds the scattered draw.")
    parser.add_argument("--width", type=int, default=832)
    parser.add_argument("--height", type=int, default=1216)
    parser.add_argument("--pick", nargs="*", default=None, help="family=1,4,7 ...")
    parser.add_argument(
        "--backgrounds", nargs="*", default=None,
        help="Background phrases, one per image in rotation. Default: the festival set.",
    )
    parser.add_argument("--no-solo", action="store_true", help="Do not append the 'alone in frame' phrase.")
    args = parser.parse_args()

    project = ROOT / "projects" / args.project
    masters_path = project / "masters" / "masters.json"
    out = project / "dataset"
    cand_dir = out / "candidates"
    sheets_dir = out / "sheets"
    for d in (cand_dir, sheets_dir):
        d.mkdir(parents=True, exist_ok=True)

    if not masters_path.is_file():
        print(f"FAIL: no masters at {masters_path}. Run scripts/masters.py --pick first.")
        return 1
    masters = json.loads(masters_path.read_text(encoding="utf-8"))
    brief = args.brief or masters.get("brief")
    if not brief:
        print("FAIL: no brief")
        return 1
    for key in ("face", "body_front", "body_three_quarter"):
        if not Path(masters[key]).is_file():
            print(f"FAIL: master {key} missing: {masters[key]}")
            return 1

    # ------------------------------------------------------------------ pick
    if args.pick:
        listing = json.loads((out / "candidates.json").read_text(encoding="utf-8"))
        picks = {}
        for item in args.pick:
            fam, nums = item.split("=", 1)
            picks[fam] = [int(n) for n in nums.split(",") if n.strip()]
        accepted_dir = out / "accepted"
        if accepted_dir.exists():
            shutil.rmtree(accepted_dir)
        accepted_dir.mkdir(parents=True)
        images = []
        order = 0
        for fam, nums in picks.items():
            rows = [r for r in listing["candidates"] if r["family"] == fam]
            for n in nums:
                if not 1 <= n <= len(rows):
                    print(f"FAIL: {fam} has {len(rows)} candidates; {n} is out of range")
                    return 1
                row = rows[n - 1]
                target = accepted_dir / f"{order:03d}_{fam}.png"
                shutil.copyfile(row["path"], target)
                images.append({
                    "path": str(target), "source": row["path"], "family": fam, "tile": n,
                    "seed": row["seed"], "cos_face": row["cos_face"], "face_fraction": row["face_fraction"],
                    "descriptor": row["descriptor"], "caption": None,
                })
                order += 1
        comp = balance([i["family"] for i in images])
        manifest = {
            "version": "1.0",
            "character": listing["character"],
            "trigger": None,
            "brief": brief,
            "masters": {k: masters[k] for k in ("face", "body_front", "body_three_quarter")},
            "engine": "flux_klein multi-reference, from the masters only",
            "decided_by": "human",
            "balance": comp,
            "images": images,
        }
        (out / "dataset.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
        sheet = labelled_sheet(
            [SheetItem(Path(i["path"]), f"{i['family']}  cos {i['cos_face']:.2f}" if i["cos_face"] is not None else i["family"], "", ACCENTS[0]) for i in images],
            sheets_dir / "accepted.png", columns=6, cell=340,
            title=f"{listing['character']} - the dataset: {len(images)} images, chosen by hand",
        )
        print(f"accepted {len(images)} -> {accepted_dir}")
        print(f"balance : {comp['counts']}  {'OK' if comp['balanced'] else 'OVER: ' + ', '.join(comp['over_represented'])}")
        print(f"manifest: {out / 'dataset.json'}")
        print(f"sheet   : {sheet}")
        return 0

    # -------------------------------------------------------------- generate
    vrgdg = VRGDGClient()
    if not vrgdg.is_available():
        print("FAIL:", vrgdg.unavailable_reason())
        return 1
    client = ComfyUIClient()
    _, face_vector, _ = _face(Path(masters["face"]))
    if face_vector is None:
        print("FAIL: the face master does not hold exactly one face")
        return 1

    added = _reference_guard(vrgdg, f"{brief}. full body shot, standing", Path(masters["face"]), args.width, args.height)
    if not added:
        print("FAIL: the reference was silently dropped by the route; see HANDOFF")
        return 1
    print(f"reference guard: {sorted(added)}")

    # Expand the quota table by the multiplier, then draw scattered seeds so
    # the population is as varied as the prompt allows (wiki/practice/seeds.md).
    scaled = [type(f)(f.name, f.shot, max(1, round(f.target * args.multiplier)), f.anchored_on, f.start_at) for f in LADDER]
    backgrounds = tuple(args.backgrounds) if args.backgrounds else FESTIVAL_BACKGROUNDS
    specs = plan_dataset(scaled, seed_base=0, backgrounds=backgrounds)
    rng = np.random.default_rng(args.seed)
    seeds = [int(s) for s in rng.integers(0, SEED_MAX, size=len(specs), dtype=np.uint64)]
    print(f"plan: {len(specs)} candidates - " + ", ".join(f"{f.name} {f.target}" for f in scaled) + "\n")

    rows: list[dict] = []
    started = time.time()
    per_family_index: dict[str, int] = {}
    for spec, seed in zip(specs, seeds):
        fam = spec.family
        per_family_index[fam] = per_family_index.get(fam, 0) + 1
        index = per_family_index[fam]
        fam_dir = cand_dir / fam
        fam_dir.mkdir(parents=True, exist_ok=True)
        path = fam_dir / f"{index:02d}_s{seed}.png"
        refs = _references(fam, spec.angle, masters)
        prompt = spec.prompt(brief) + ". " + spec.angle + ("" if args.no_solo else ". " + SOLO)
        elapsed = 0.0
        if not path.is_file():
            graph = vrgdg.build("flux_klein", _payload(prompt, seed, refs, args.width, args.height))
            if not (node_class_types(graph.prompt) & added):
                print(f"  {fam:10s} {index:>2}: reference dropped on build; skipped")
                continue
            output_node = graph.output_node(prefer="image")
            graph.prune(output_node)
            t = time.time()
            try:
                client.generate(graph.prompt, output_node=output_node, dest=path, timeout=600)
            except Exception as exc:
                print(f"  {fam:10s} {index:>2}: FAILED {str(exc)[:100]}")
                continue
            elapsed = time.time() - t
        faces, vector, share = _face(path)
        cos = None if vector is None else float(np.dot(face_vector, vector))
        rows.append({
            "family": fam, "index": index, "seed": seed, "path": str(path), "faces": faces,
            "cos_face": None if cos is None else round(cos, 4),
            "face_fraction": None if share is None else round(share, 5),
            "references": [Path(r).name for r in refs],
            "descriptor": spec.descriptor(),
        })
        cos_t = "no face" if cos is None else f"{cos:.3f}"
        share_t = "" if share is None else f"  face {share * 100:4.1f}%"
        print(f"  {fam:10s} {index:>2}  seed {seed:<20d} {elapsed:5.1f}s  cos {cos_t}{share_t}  refs={len(refs)}")

    minutes = (time.time() - started) / 60
    sheets: dict[str, list[str]] = {}
    for f in scaled:
        items = [
            SheetItem(
                Path(r["path"]),
                f"{r['index']}.  cos {r['cos_face']:.2f}" if r["cos_face"] is not None else f"{r['index']}.  {r['faces']} faces",
                (f"face {r['face_fraction'] * 100:.1f}%" if r["face_fraction"] else "")
                + (f"  +{r['faces'] - 1} in frame" if r["faces"] > 1 else ""),
                ACCENTS[0] if (r["cos_face"] or 0) >= 0.60 else ACCENTS[3] if (r["cos_face"] or 0) >= 0.50 else ACCENTS[7],
            )
            for r in rows if r["family"] == f.name
        ]
        if not items:
            continue
        sheet = labelled_sheet(items, sheets_dir / f"{f.name}.png", columns=6, cell=340,
                               title=f"{args.project} - {f.name}: pick by number. cos = ArcFace vs the face master.")
        parts = _sheet_parts(sheet, 6, 340, len(items)) if sheet else []
        sheets[f.name] = [str(p) for p in parts] or ([str(sheet)] if sheet else [])

    (out / "candidates.json").write_text(json.dumps({
        "version": "1.0", "character": args.project, "brief": brief, "engine": "flux_klein",
        "masters": {k: masters[k] for k in ("face", "body_front", "body_three_quarter")},
        "reference_nodes": sorted(added), "minutes": round(minutes, 2),
        "candidates": rows, "sheets": sheets,
    }, indent=2), encoding="utf-8")

    print(f"\n{len(rows)} candidates in {minutes:.1f} min")
    for fam, parts in sheets.items():
        print(f"  {fam:10s} " + "  ".join(parts))
    print("\npick with:  python scripts/dataset_klein.py --project", args.project, "--pick close_up=1,4 medium=2 wide=3 variation=1")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
