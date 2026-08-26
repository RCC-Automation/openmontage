"""Phase 3, native: generate with no reference, keep what matches the anchor.

    python scripts/build_dataset_native.py
    python scripts/build_dataset_native.py --threshold 0.55
    python scripts/build_dataset_native.py --measure-only

Every image is a plain text-to-image render from the same checkpoint that made
the anchor, so every image looks like that checkpoint's output. ArcFace is used
as a filter, never as a target - nothing in the render is pulled toward a face
embedding, which is what made the reference-conditioned version glossy.

See lib/rejection_dataset for the trade this accepts and the measured yield it
is budgeted from. In short: identity per image falls from ~0.72 to ~0.58, and
the LoRA trained on the result is the thing that puts identity back, because
identity is addable and photographic skin is not.

Existing renders are reused, including the two anchor sweeps' close-ups, which
were generated at exactly this prompt and condition and are already on disk.
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

from lib.character_dataset import (  # noqa: E402
    LADDER,
    SEED_STEP,
    DatasetEntry,
    balance,
    find_phash_duplicates,
    find_semantic_duplicates,
    plan_dataset,
)
from lib.face_identity import embeddings_available, faces_in  # noqa: E402
from lib.rejection_dataset import (  # noqa: E402
    REJECTION_ACCEPT,
    REJECTION_HOLD,
    estimate_yield,
    plan_budget,
)
from lib.render_clock import RenderTimings, route_key  # noqa: E402
from lib.sheets import ACCENTS, SheetItem, labelled_sheet  # noqa: E402
from tools._comfyui.client import ComfyUIClient  # noqa: E402
from tools.graphics.comfyui_image import ComfyUIImage  # noqa: E402

DEFAULT_BRIEF = (
    "A clockwork heroine with luminous pink hair and a brass filigree collar, "
    "brass and copper plating at the shoulders, cinematic photograph, intricate detail"
)

#: Every framing other than the anchor's own is harder, because changing the
#: prompt drifts the face more than changing the seed does (DECISIONS #29). These
#: scale the measured close-up yield so each family is funded for the job it
#: actually has. They are estimates and the report says so; the run corrects them
#: as it goes.
FAMILY_YIELD_PENALTY = {"close_up": 1.0, "medium": 0.45, "wide": 0.30, "variation": 0.7}


def _embed(path: Path) -> tuple[int, np.ndarray | None, float | None]:
    """Face count, vector, and the face's share of the frame."""
    detected = faces_in(path)
    if len(detected) != 1:
        return len(detected), None, None
    vector = getattr(detected[0], "normed_embedding", None)
    if vector is None:
        return 0, None, None
    share = None
    try:
        from PIL import Image

        with Image.open(path) as handle:
            frame = float(handle.width * handle.height)
        x1, y1, x2, y2 = detected[0].bbox
        share = float(abs((x2 - x1) * (y2 - y1)) / frame) if frame else None
    except Exception:
        share = None
    return 1, np.asarray(vector, dtype=np.float32), share


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project", default="character-lora")
    parser.add_argument("--character", default="Wren")
    parser.add_argument("--brief", default=DEFAULT_BRIEF)
    parser.add_argument("--model", default="juggernautXL_ragnarok.safetensors")
    parser.add_argument("--anchor", default=None)
    parser.add_argument("--threshold", type=float, default=REJECTION_ACCEPT)
    parser.add_argument("--hold-at", type=float, default=REJECTION_HOLD)
    parser.add_argument("--seed-base", type=int, default=900_000)
    parser.add_argument("--slack", type=float, default=1.6)
    parser.add_argument("--measure-only", action="store_true")
    args = parser.parse_args()

    project_root = ROOT / "projects" / args.project
    anchor_path = Path(args.anchor) if args.anchor else project_root / "anchor" / "anchor.png"
    out_root = project_root / "dataset-native"
    renders_dir = out_root / "renders"
    accepted_dir = out_root / "accepted"
    sheets_dir = out_root / "sheets"
    for directory in (renders_dir, accepted_dir, sheets_dir):
        directory.mkdir(parents=True, exist_ok=True)

    if not anchor_path.is_file():
        print(f"FAIL: no anchor at {anchor_path}")
        return 1
    if not embeddings_available():
        print("FAIL: insightface unavailable")
        return 1

    faces, anchor_vector, _ = _embed(anchor_path)
    if anchor_vector is None:
        print(f"FAIL: anchor has {faces} faces, need exactly 1")
        return 1
    print(f"anchor: {anchor_path}")

    # The yield the budget is built from comes from renders already on disk at
    # this exact prompt and condition, not from a guess.
    prior: list[float] = []
    for label in ("anchor", "anchor-scattered"):
        npz = project_root / label / "embeddings.npz"
        if npz.is_file():
            data = np.load(npz)
            vectors = data["vectors"].astype(np.float32)
            prior.extend((vectors @ anchor_vector).tolist())
    prior = [s for s in prior if s < 0.999]  # drop the anchor matching itself
    measured = estimate_yield(prior, args.threshold)
    print(
        f"prior: {measured.sample_size} close-ups already rendered at this prompt, "
        f"{measured.pass_rate:.1%} clear {args.threshold:g}"
    )

    budgets = {
        b.family: b
        for b in plan_budget(
            [(f.name, f.target) for f in LADDER],
            prior,
            threshold=args.threshold,
            slack=args.slack,
            penalty=FAMILY_YIELD_PENALTY,
        )
    }
    total_budget = sum(b.budget for b in budgets.values())
    print(f"budget: {total_budget} renders (~{total_budget * 25 / 60:.0f} min)\n")

    specs = plan_dataset(LADDER, seed_base=args.seed_base)
    by_family: dict[str, list] = {}
    for spec in specs:
        by_family.setdefault(spec.family, []).append(spec)

    client = ComfyUIClient()
    generator = ComfyUIImage()
    timings = RenderTimings.load()
    route = route_key("comfyui_image", "bundled", "juggernaut-xl-ragnarok-txt2img.json")

    entries: list[DatasetEntry] = []
    started = time.time()
    render_count = 0

    for family in LADDER:
        budget = budgets[family.name]
        family_specs = by_family.get(family.name, [])
        family_dir = renders_dir / family.name
        family_dir.mkdir(parents=True, exist_ok=True)
        print(
            f"=== {family.name}: want {family.target}, budget {budget.budget} "
            f"(expected yield {budget.estimate.pass_rate:.0%}) ==="
        )

        while not budget.complete and not budget.exhausted:
            spec = family_specs[budget.spent % len(family_specs)]
            retry_round = budget.spent // len(family_specs)
            seed = spec.seed + retry_round * SEED_STEP * 97
            spec = type(spec)(**{**spec.__dict__, "seed": seed})
            budget.spent += 1

            path = family_dir / f"{spec.index:02d}_r{retry_round}_s{seed}.png"
            if not path.is_file() and not args.measure_only:
                depth = client.queue_depth()
                render_started = time.time()
                outcome = generator.execute(
                    {
                        "prompt": spec.prompt(args.brief),
                        "workflow_variant": "juggernaut_xl_ragnarok",
                        "checkpoint_name": args.model,
                        "seed": int(seed),
                        "output_path": str(path),
                    }
                )
                elapsed = time.time() - render_started
                if not outcome.success:
                    budget.notes.append(f"seed {seed}: {str(outcome.error)[:160]}")
                    print(f"  [{budget.spent:>3}/{budget.budget}] FAILED {str(outcome.error)[:90]}")
                    continue
                render_count += 1
                if depth == 0:
                    timings.record(route, elapsed, pixels=832 * 1216)
            elif path.is_file():
                elapsed = 0.0
            else:
                continue

            count, vector, share = _embed(path)
            entry = DatasetEntry(spec=spec, path=path, faces=count, seconds=elapsed)
            entry.face_fraction = share
            if vector is None:
                entry.verdict = "reject"
                entry.notes.append(f"{count} faces, need exactly 1")
            else:
                entry.cos_root = float(np.dot(anchor_vector, vector))
                entry.verdict = (
                    "accept"
                    if entry.cos_root >= args.threshold
                    else "hold"
                    if entry.cos_root >= args.hold_at
                    else "reject"
                )
            entries.append(entry)
            if entry.verdict == "accept":
                budget.accepted += 1

            score = "  n/a" if entry.cos_root is None else f"{entry.cos_root:.3f}"
            face = "  n/a" if share is None else f"{share * 100:5.1f}%"
            print(
                f"  [{budget.spent:>3}/{budget.budget}] seed {seed}  {elapsed:5.1f}s  "
                f"cos {score}  face {face}  -> {entry.verdict}"
                f"   ({budget.accepted}/{family.target})"
            )

        if not budget.complete:
            budget.notes.append(
                f"short: {budget.accepted}/{family.target} in {budget.spent} renders "
                f"(actual yield {budget.accepted / max(1, budget.spent):.1%})"
            )
            print(f"  ! {budget.notes[-1]}")
        print()

    timings.save()
    minutes = (time.time() - started) / 60
    accepted = [e for e in entries if e.verdict == "accept"]
    print(f"{render_count} renders in {minutes:.1f} min, {len(accepted)} accepted")
    if not accepted:
        print("FAIL: nothing accepted")
        return 1

    phash_pairs = find_phash_duplicates([e.path for e in accepted])
    semantic_pairs = find_semantic_duplicates([e.path for e in accepted])
    dupes = {j for _, j, _ in phash_pairs} | {j for _, j, _ in semantic_pairs}
    for index in dupes:
        accepted[index].verdict = "duplicate"
    final = [e for e in accepted if e.verdict == "accept"]
    print(f"dedup: dropped {len(dupes)} -> {len(final)} in the set")

    composition = balance([e.spec.family for e in final])
    vectors = []
    for entry in final:
        _, vector, _ = _embed(entry.path)
        if vector is not None:
            vectors.append(vector)
    raw_mean = None
    if len(vectors) >= 2:
        matrix = np.stack(vectors)
        gram = matrix @ matrix.T
        raw_mean = float(gram[np.triu_indices(len(vectors), k=1)].mean())

    files = []
    for order, entry in enumerate(final):
        target = accepted_dir / f"{order:03d}_{entry.spec.family}.png"
        shutil.copyfile(entry.path, target)
        files.append(str(target))

    sheet = labelled_sheet(
        [
            SheetItem(e.path, e.spec.family, f"cos {e.cos_root:.3f}", ACCENTS[0])
            for e in final
        ],
        sheets_dir / "accepted.png",
        columns=6,
        title=(
            f"{args.character} - native dataset, {len(final)} images, no reference "
            f"conditioning. mean pairwise {raw_mean:.3f}" if raw_mean else "dataset"
        ),
    )

    manifest = {
        "version": "1.0",
        "character": args.character,
        "trigger": None,
        "brief": args.brief,
        "checkpoint": args.model,
        "mechanism": "native text-to-image, ArcFace rejection sampling (no reference adapter)",
        "root_anchor": str(anchor_path),
        "threshold": args.threshold,
        "images": [
            {
                "path": files[order],
                "source": str(e.path),
                "family": e.spec.family,
                "seed": e.spec.seed,
                "cos_root": round(e.cos_root, 4) if e.cos_root is not None else None,
                "face_fraction": e.face_fraction,
                "descriptor": e.spec.descriptor(),
                "caption": None,
            }
            for order, e in enumerate(final)
        ],
    }
    (out_root / "dataset.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")

    report = {
        "version": "1.0",
        "phase": "runbook phase 3, native variant - rejection sampling",
        "why_not_reference": (
            "Every FaceID setting produced glossier, more idealised skin than the "
            "base model's own output; a two-pass refinement kept identity (0.735) "
            "and recovered none of the look. Identity is what the LoRA adds, so "
            "the dataset carries the realism instead. DECISIONS #38, one level down."
        ),
        "threshold": args.threshold,
        "renders": render_count,
        "render_minutes": round(minutes, 2),
        "counts": {
            "accepted": len(final),
            "held": sum(1 for e in entries if e.verdict == "hold"),
            "rejected": sum(1 for e in entries if e.verdict == "reject"),
            "duplicates": len(dupes),
        },
        "per_family": {b.family: b.as_dict() for b in budgets.values()},
        "family_face_fraction": {
            f.name: round(
                float(
                    np.mean(
                        [
                            e.face_fraction
                            for e in final
                            if e.spec.family == f.name and e.face_fraction is not None
                        ]
                    )
                ),
                5,
            )
            for f in LADDER
            if any(
                e.face_fraction is not None for e in final if e.spec.family == f.name
            )
        },
        "balance": composition,
        "identity": {"mean_pairwise_cosine_raw": None if raw_mean is None else round(raw_mean, 4)},
        "entries": [e.as_dict() for e in entries],
        "sheet": None if sheet is None else str(sheet),
        "manifest": str(out_root / "dataset.json"),
    }
    (out_root / "dataset_report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")

    print(f"\nmanifest: {out_root / 'dataset.json'}")
    print(f"report  : {out_root / 'dataset_report.json'}")
    print(f"sheet   : {sheet}")
    print(f"balance : {composition['counts']}")
    if raw_mean:
        print(f"identity: mean pairwise {raw_mean:.4f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
