"""Phase 3 of the character-LoRA runbook: build the dataset as a ladder.

    python scripts/build_dataset.py                 # 36 accepted images, 2-3 h GPU
    python scripts/build_dataset.py --smoke         # one render, proves the graph
    python scripts/build_dataset.py --measure-only  # rescore what is on disk

Generate against a reference face, score every candidate against the anchor,
keep what clears the bar and replace what does not - in the same family, so the
quota table stays true. See lib/character_dataset.py for the two-anchor scoring
and why acceptance gates on the root rather than the rung below.

Nothing is thrown away. Rejected renders stay on disk and in the report next to
the score that rejected them, because "the wide family could not hold a face" is
a finding about the reference mechanism, not clutter.
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

from scripts.dataset_klein import FESTIVAL_BACKGROUNDS, SOLO  # noqa: E402
from lib.character_dataset import (  # noqa: E402
    ACCEPT_AT,
    HOLD_AT,
    LADDER,
    SEED_STEP,
    DatasetEntry,
    balance,
    classify,
    find_phash_duplicates,
    find_semantic_duplicates,
    plan_dataset,
)
from lib.face_identity import embeddings_available, face_identity_stability, faces_in  # noqa: E402
from lib.render_clock import RenderTimings, route_key  # noqa: E402
from lib.sheets import ACCENTS, SheetItem, labelled_sheet  # noqa: E402
from tools._comfyui.client import ComfyUIClient  # noqa: E402
from tools._comfyui.faceid import OUTPUT_NODE, build_faceid_graph  # noqa: E402

DEFAULT_BRIEF = (
    "A clockwork heroine with luminous pink hair and a brass filigree collar, "
    "brass and copper plating at the shoulders, cinematic photograph, intricate detail"
)


def _embed_one(path: Path) -> tuple[int, np.ndarray | None]:
    """Face count and the largest face's vector. Count is the first gate."""
    detected = faces_in(path)
    if len(detected) != 1:
        return len(detected), None
    vector = getattr(detected[0], "normed_embedding", None)
    if vector is None:
        return 0, None
    return 1, np.asarray(vector, dtype=np.float32)


def _face_fraction(path: Path) -> float | None:
    """Face box over frame area - the witness that the shot size happened."""
    detected = faces_in(path)
    if len(detected) != 1:
        return None
    try:
        from PIL import Image

        with Image.open(path) as handle:
            frame = float(handle.width * handle.height)
    except Exception:
        return None
    x1, y1, x2, y2 = detected[0].bbox
    return float(abs((x2 - x1) * (y2 - y1)) / frame) if frame else None


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project", default="character-lora")
    parser.add_argument("--character", default="Wren")
    parser.add_argument("--brief", default=DEFAULT_BRIEF)
    parser.add_argument("--checkpoint", default="juggernautXL_ragnarok.safetensors")
    parser.add_argument("--anchor", default=None, help="Defaults to Phase 2's anchor.png")
    parser.add_argument("--accept-at", type=float, default=ACCEPT_AT)
    parser.add_argument("--hold-at", type=float, default=HOLD_AT)
    parser.add_argument("--seed-base", type=int, default=500_000)
    parser.add_argument(
        "--attempts-per-image", type=float, default=3.0,
        help="Render budget per wanted image, before a family is left short.",
    )
    # Deliberately NOT the settings that maximise identity. lora_strength 1.0
    # scores highest (0.786) and idealises skin - uniform tone, heavy sheen, no
    # freckles - and a LoRA learns whatever texture it is trained on, so a glossy
    # dataset yields a permanently glossy model. 0.3 is the gentlest reference
    # that still holds identity across varied prompts (close-ups mean 0.667 where
    # no reference gives 0.374), and it is the setting Raul chose off the
    # side-by-side in projects/character-lora/realism/.
    parser.add_argument("--weight-faceidv2", type=float, default=2.0)
    parser.add_argument("--lora-strength", type=float, default=0.3)
    parser.add_argument(
        "--ladder", action="store_true",
        help=(
            "Condition each family on a promoted member of the family below it. "
            "Off by default: with an embedding reference it compounds drift "
            "(144 renders, 1 accepted) - see conditioning_for."
        ),
    )
    parser.add_argument("--smoke", action="store_true", help="One render, then stop.")
    parser.add_argument("--measure-only", action="store_true")
    args = parser.parse_args()

    project_root = ROOT / "projects" / args.project
    anchor_path = Path(args.anchor) if args.anchor else project_root / "anchor" / "anchor.png"
    out_root = project_root / "dataset"
    renders_dir = out_root / "renders"
    anchors_dir = out_root / "anchors"
    accepted_dir = out_root / "accepted"
    sheets_dir = out_root / "sheets"
    for directory in (renders_dir, anchors_dir, accepted_dir, sheets_dir):
        directory.mkdir(parents=True, exist_ok=True)

    if not anchor_path.is_file():
        print(f"FAIL: no anchor at {anchor_path}. Run scripts/anchor_select.py first.")
        return 1
    if not embeddings_available():
        print("FAIL: insightface/onnxruntime unavailable; cannot score anything.")
        return 1

    # The anchor is embedded once and reused for every candidate. Re-embedding
    # per render would add a CPU pass to each and, worse, invites the anchor to
    # be re-detected differently on a bad frame.
    faces, root_vector = _embed_one(anchor_path)
    if root_vector is None:
        print(f"FAIL: the anchor has {faces} detectable faces; expected exactly one.")
        return 1
    shutil.copyfile(anchor_path, anchors_dir / "root.png")
    print(f"root anchor: {anchor_path}")

    client = ComfyUIClient()
    if not client.is_available():
        print("FAIL: ComfyUI is not reachable.")
        return 1
    timings = RenderTimings.load()
    route = route_key("comfyui_image", "custom", "sdxl-ipadapter-faceid")

    specs = plan_dataset(LADDER, seed_base=args.seed_base, backgrounds=FESTIVAL_BACKGROUNDS)
    by_family: dict[str, list] = {}
    for spec in specs:
        by_family.setdefault(spec.family, []).append(spec)

    # Each family conditions on its own promoted image once it has one, and on
    # its parent's until then. That is the ladder: the reference always matches
    # the framing being generated as closely as it can.
    family_anchor: dict[str, tuple[Path, np.ndarray]] = {}
    family_of = {family.name: family for family in LADDER}

    entries: list[DatasetEntry] = []
    failures: list[str] = []
    started = time.time()
    render_count = 0

    def conditioning_for(family_name: str) -> tuple[Path, np.ndarray, str]:
        """What this render is conditioned on. The root anchor, by default.

        **The ladder is off by default, and the measurement is why.** The runbook
        promotes a member of each family to anchor the next, because we measured a
        *latent* reference collapsing across framings (0.932 -> 0.301, DECISIONS
        #30) and a same-framing reference is the workaround for that.

        FaceID is not the latent path. It conditions on a pose-normalised ArcFace
        vector, which is built to survive exactly the framing change the latent
        path could not - so the workaround buys nothing and costs a great deal.
        Run with the ladder on, 144 renders produced **1** usable image: every
        render matched what it was conditioned on (family cosine 0.70-0.74) while
        drifting from the anchor (root cosine 0.37-0.41), because cosine does not
        chain. A promoted anchor sitting 0.55 from the root yields renders near
        0.40, and the next rung compounds it.

        Conditioned on the root directly, the same prompts probe at 0.667
        close-up, 0.623 medium, 0.523 wide.
        """
        if not args.ladder:
            return anchor_path, root_vector, "root"
        if family_name in family_anchor:
            path, vector = family_anchor[family_name]
            return path, vector, family_name
        parent = family_of[family_name].anchored_on
        while parent:
            if parent in family_anchor:
                path, vector = family_anchor[parent]
                return path, vector, parent
            parent = family_of[parent].anchored_on
        return anchor_path, root_vector, "root"

    for family in LADDER:
        family_specs = by_family.get(family.name, [])
        if not family_specs:
            continue
        budget = int(round(family.target * args.attempts_per_image))
        accepted_here = 0
        attempt = 0
        family_dir = renders_dir / family.name
        family_dir.mkdir(parents=True, exist_ok=True)
        print(f"\n=== family {family.name}: want {family.target}, budget {budget} renders ===")

        while accepted_here < family.target and attempt < budget:
            spec = family_specs[attempt % len(family_specs)]
            # Retries past the plan reuse the plan's varying axes but must not
            # reuse its seed, or a rejected render is regenerated identically.
            retry_round = attempt // len(family_specs)
            seed = spec.seed + retry_round * SEED_STEP * 97
            spec = type(spec)(**{**spec.__dict__, "seed": seed})
            attempt += 1

            path = family_dir / f"{spec.index:02d}_r{retry_round}_s{seed}.png"
            reference, reference_vector, reference_name = conditioning_for(family.name)

            if not path.is_file() and not args.measure_only:
                graph = build_faceid_graph(
                    prompt=spec.prompt(args.brief) + ". " + spec.angle + ". " + SOLO,
                    reference_image=reference,
                    seed=seed,
                    checkpoint=args.checkpoint,
                    weight_faceidv2=args.weight_faceidv2,
                    lora_strength=args.lora_strength,
                    # Per-family, because the shot size is what decides it.
                    start_at=family.start_at,
                )
                depth = client.queue_depth()
                render_started = time.time()
                try:
                    client.generate(graph, output_node=OUTPUT_NODE, dest=path, timeout=600)
                except Exception as exc:
                    failures.append(f"{family.name} #{spec.index} seed {seed}: {exc}")
                    print(f"  [{attempt:>2}/{budget}] seed {seed} FAILED: {str(exc)[:160]}")
                    if len(failures) >= 5 and not entries:
                        print("\nFAIL: five failures and nothing rendered; stopping.")
                        return 1
                    continue
                elapsed = time.time() - render_started
                render_count += 1
                if depth == 0:
                    timings.record(route, elapsed, pixels=832 * 1216)
            elif path.is_file():
                elapsed = 0.0
            else:
                continue

            count, vector = _embed_one(path)
            entry = DatasetEntry(spec=spec, path=path, faces=count, seconds=elapsed)
            entry.notes.append(
                f"conditioned on {reference_name}, start_at {family.start_at:g}"
            )
            if vector is None:
                entry.verdict = "reject"
                entry.notes.append(f"{count} faces detected, need exactly 1")
            else:
                entry.cos_root = float(np.dot(root_vector, vector))
                entry.cos_family = float(np.dot(reference_vector, vector))
                entry.face_fraction = _face_fraction(path)
                entry.verdict = classify(
                    entry.cos_root, accept_at=args.accept_at, hold_at=args.hold_at
                )
            entries.append(entry)

            root_text = "n/a" if entry.cos_root is None else f"{entry.cos_root:.3f}"
            fam_text = "n/a" if entry.cos_family is None else f"{entry.cos_family:.3f}"
            face_text = (
                "  n/a " if entry.face_fraction is None else f"{entry.face_fraction * 100:5.1f}%"
            )
            print(
                f"  [{attempt:>2}/{budget}] seed {seed}  {elapsed:5.1f}s  "
                f"root {root_text}  fam {fam_text}  face {face_text} -> {entry.verdict}"
            )

            if entry.verdict == "accept":
                accepted_here += 1
                # The first accepted image in a family becomes its anchor, and
                # every later render in that family conditions on it. Promoting
                # on the root score (not the family score) is what stops the
                # ladder drifting away from her one rung at a time.
                if family.name not in family_anchor and vector is not None:
                    family_anchor[family.name] = (path, vector)
                    shutil.copyfile(path, anchors_dir / f"{family.name}.png")
                    entry.notes.append("promoted to family anchor")
                    print(f"       promoted to {family.name} anchor")

            if args.smoke:
                print("\nsmoke run: the graph built, rendered and scored. Stopping.")
                timings.save()
                return 0 if entry.faces == 1 else 2

        if accepted_here < family.target:
            note = (
                f"family {family.name} short: {accepted_here}/{family.target} accepted "
                f"in {attempt} renders"
            )
            failures.append(note)
            print(f"  ! {note}")

    timings.save()
    minutes = (time.time() - started) / 60
    print(f"\n{render_count} renders in {minutes:.1f} min")

    accepted = [e for e in entries if e.verdict == "accept"]
    held = [e for e in entries if e.verdict == "hold"]
    rejected = [e for e in entries if e.verdict == "reject"]
    print(f"accepted {len(accepted)}, held {len(held)}, rejected {len(rejected)}")

    if not accepted:
        print("\nFAIL: nothing was accepted; there is no dataset to report on.")
        return 1

    # ---------------------------------------------------------------- dedup
    # pHash first (cheap, catches the near-identical render), then CLIP for the
    # semantic repeat: the same pose from a different seed shares no pixels and
    # is still a repeat count in the training data.
    accepted_paths = [e.path for e in accepted]
    phash_pairs = find_phash_duplicates(accepted_paths)
    semantic_pairs = find_semantic_duplicates(accepted_paths)
    duplicate_indices: set[int] = set()
    for i, j, _ in phash_pairs:
        duplicate_indices.add(j)
    for i, j, _ in semantic_pairs:
        duplicate_indices.add(j)
    for index in duplicate_indices:
        accepted[index].verdict = "duplicate"
        accepted[index].notes.append("near-duplicate of an earlier accepted image")
    final = [e for e in accepted if e.verdict == "accept"]
    print(
        f"dedup: {len(phash_pairs)} pHash pair(s), {len(semantic_pairs)} semantic pair(s), "
        f"{len(duplicate_indices)} dropped -> {len(final)} in the set"
    )

    # --------------------------------------------------------------- measure
    composition = balance([e.spec.family for e in final])
    print(f"balance: {composition['counts']}  " + ("OK" if composition["balanced"] else
          f"OVER: {composition['over_represented']}"))

    final_paths = [e.path for e in final]
    stability = face_identity_stability(final_paths)
    vectors = []
    for entry in final:
        _, vector = _embed_one(entry.path)
        if vector is not None:
            vectors.append(vector)
    raw_mean = None
    if len(vectors) >= 2:
        matrix = np.stack(vectors)
        gram = matrix @ matrix.T
        raw_mean = float(gram[np.triu_indices(len(vectors), k=1)].mean())

    # -------------------------------------------------------------- evidence
    accepted_dir_files: list[str] = []
    for order, entry in enumerate(final):
        target = accepted_dir / f"{order:03d}_{entry.spec.family}.png"
        shutil.copyfile(entry.path, target)
        accepted_dir_files.append(str(target))

    sheets: dict[str, str] = {}
    for family in LADDER:
        items = [
            SheetItem(
                e.path,
                f"{e.spec.family[:3]} {e.verdict}",
                f"root {e.cos_root:.3f}" if e.cos_root is not None else f"{e.faces} faces",
                ACCENTS[0] if e.verdict == "accept" else ACCENTS[3] if e.verdict == "hold" else ACCENTS[7],
            )
            for e in entries
            if e.spec.family == family.name
        ]
        if not items:
            continue
        sheet = labelled_sheet(
            items,
            sheets_dir / f"{family.name}.png",
            columns=6,
            title=f"{args.character} - family {family.name}: every render, accepted or not",
        )
        if sheet:
            sheets[family.name] = str(sheet)

    accepted_sheet = labelled_sheet(
        [
            SheetItem(e.path, f"{e.spec.family}", f"root {e.cos_root:.3f}", ACCENTS[0])
            for e in final
        ],
        sheets_dir / "accepted.png",
        columns=6,
        title=(
            f"{args.character} - the dataset: {len(final)} images, "
            f"mean pairwise ArcFace {raw_mean:.3f}" if raw_mean else f"{args.character} - the dataset"
        ),
    )

    manifest = {
        "version": "1.0",
        "character": args.character,
        "trigger": None,
        "brief": args.brief,
        "checkpoint": args.checkpoint,
        "root_anchor": str(anchor_path),
        "images": [
            {
                "path": accepted_dir_files[order],
                "source": str(entry.path),
                "family": entry.spec.family,
                "seed": entry.spec.seed,
                "cos_root": round(entry.cos_root, 4) if entry.cos_root is not None else None,
                "descriptor": entry.spec.descriptor(),
                "caption": None,
            }
            for order, entry in enumerate(final)
        ],
    }
    (out_root / "dataset.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")

    report = {
        "version": "1.0",
        "phase": "runbook phase 3 - the dataset ladder",
        "character": args.character,
        "brief": args.brief,
        "checkpoint": args.checkpoint,
        "reference_mechanism": "IP-Adapter FaceID PlusV2 (embedding path), SDXL",
        "faceid": {
            "weight_faceidv2": args.weight_faceidv2,
            "lora_strength": args.lora_strength,
        },
        "bands": {"accept_at": args.accept_at, "hold_at": args.hold_at},
        "score_convention": (
            "raw ArcFace cosine against the ROOT anchor (Phase 2 medoid). "
            "cos_family is against whatever the render was conditioned on. "
            "Neither is the rescaled face_identity_stability score."
        ),
        "renders": render_count,
        "render_minutes": round(minutes, 2),
        "counts": {
            "accepted": len(final),
            "held": len(held),
            "rejected": len(rejected),
            "dropped_as_duplicate": len(duplicate_indices),
        },
        "per_family": {
            family.name: {
                "target": family.target,
                "accepted": sum(1 for e in final if e.spec.family == family.name),
                "attempts": sum(1 for e in entries if e.spec.family == family.name),
                "anchored_on": family.anchored_on,
                "start_at": family.start_at,
                # If these do not separate by family, the ladder produced one
                # framing wearing three labels and the LoRA will learn one shot
                # size. It is the composition check the dataset cannot skip.
                "mean_face_fraction": round(
                    float(
                        np.mean(
                            [
                                e.face_fraction
                                for e in final
                                if e.spec.family == family.name and e.face_fraction is not None
                            ]
                        )
                    ),
                    5,
                )
                if any(
                    e.face_fraction is not None
                    for e in final
                    if e.spec.family == family.name
                )
                else None,
                "anchor": str(anchors_dir / f"{family.name}.png")
                if (anchors_dir / f"{family.name}.png").is_file()
                else None,
                "mean_cos_root": round(
                    float(
                        np.mean(
                            [
                                e.cos_root
                                for e in entries
                                if e.spec.family == family.name and e.cos_root is not None
                            ]
                        )
                    ),
                    4,
                )
                if any(
                    e.cos_root is not None for e in entries if e.spec.family == family.name
                )
                else None,
            }
            for family in LADDER
        },
        "balance": composition,
        "dedup": {
            "phash_pairs": [[i, j, d] for i, j, d in phash_pairs],
            "semantic_pairs": [[i, j, round(c, 4)] for i, j, c in semantic_pairs],
        },
        "gate": {
            "face_identity_stability_rescaled": stability,
            "mean_pairwise_cosine_raw": None if raw_mean is None else round(raw_mean, 4),
        },
        "failures": failures,
        "entries": [e.as_dict() for e in entries],
        "sheets": {**sheets, "accepted": None if accepted_sheet is None else str(accepted_sheet)},
        "manifest": str(out_root / "dataset.json"),
    }
    report_path = out_root / "dataset_report.json"
    report_path.write_text(json.dumps(report, indent=2), encoding="utf-8")

    print(f"\nmanifest: {out_root / 'dataset.json'}")
    print(f"report  : {report_path}")
    print(f"sheet   : {accepted_sheet}")
    if raw_mean is not None:
        print(
            f"\nGATE: {len(final)} images, mean pairwise ArcFace {raw_mean:.4f} raw"
            f" / {stability:.3f} rescaled" if stability is not None else ""
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
