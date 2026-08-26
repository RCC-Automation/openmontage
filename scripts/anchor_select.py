"""Phase 2 of the character-LoRA runbook: choose the anchor.

    python scripts/anchor_select.py                    # 48 renders, ~20 min GPU
    python scripts/anchor_select.py --n 60
    python scripts/anchor_select.py --embed-only       # recluster, render nothing

Render many close-ups of the character from the description alone, embed every
face with ArcFace, cluster with k-means++, and promote the tightest cluster's
medoid to be the anchor. See lib/character_anchor.py for why the medoid and not
a favourite, and wiki/character/runbook-first-lora.md for where this sits.

Everything is kept: every render, the embeddings, the cluster assignment, both
contact sheets and a report that carries the numbers the gate was judged on.
Re-running skips renders that already exist, so a crash costs minutes not hours,
and --embed-only re-derives the whole decision without touching the GPU.
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

from lib.character_anchor import ANCHOR_GATE, choose_anchor, suggested_k  # noqa: E402
from lib.face_identity import embeddings_available, faces_in  # noqa: E402
from lib.render_clock import RenderTimings, route_key  # noqa: E402
from lib.screen_test import build_prompt  # noqa: E402
from lib.sheets import ACCENTS, SheetItem, labelled_sheet  # noqa: E402
from tools._comfyui.client import ComfyUIClient  # noqa: E402
from tools.graphics.comfyui_image import ComfyUIImage  # noqa: E402

#: The brief the WP2 casting session actually ran, so Phase 2 measures the same
#: character that was cast rather than a paraphrase of her.
DEFAULT_BRIEF = (
    "A clockwork heroine with luminous pink hair and a brass filigree collar, "
    "brass and copper plating at the shoulders, warm amber workshop light, "
    "cinematic portrait, intricate detail"
)
DEFAULT_MODEL = "juggernautXL_ragnarok.safetensors"

#: Close-up, key light, front on - the most diagnostic frame for a face, and the
#: same condition the casting round judged these models under.
CONDITION = {"shot_size": "close_up", "lighting": "key", "angle": "front"}

#: Renders differ only by seed. A prime step keeps the sequence from landing on
#: any structure in the sampler's noise, and the seeds are written into the
#: report so the whole population is reproducible.
SEED_STEP = 1009

#: KSampler's declared range: 0 .. 2^64 - 1.
SEED_MAX = 18_446_744_073_709_551_615


def _seeds(n: int, base: int, mode: str = "arithmetic") -> list[int]:
    """The sweep's seeds, either an arithmetic run or scattered over 2^64.

    Both are reproducible - `base` seeds the draw in scattered mode - because a
    population you cannot regenerate is a population you cannot re-measure.

    Why both exist: seed distance provably carries no signal (r = +0.010 over
    1128 pairs of the arithmetic sweep), but that test cannot see whether an
    arithmetic *progression* is itself slightly less varied than scattered
    draws. A first probe of 8 scattered seeds landed at the 1.6th percentile of
    the bootstrap distribution of 8-subsets of the arithmetic sweep, which is a
    hint and not a finding. This flag is how the two are compared at equal n.
    """
    if mode == "arithmetic":
        return [base + i * SEED_STEP for i in range(n)]
    if mode == "scattered":
        rng = np.random.default_rng(base)
        # Drawn without replacement in a space of 2^64: a collision would be an
        # accidental duplicate render, and at n=48 it will never happen, but the
        # check costs nothing and the alternative is a silent repeat.
        drawn: list[int] = []
        seen: set[int] = set()
        while len(drawn) < n:
            value = int(rng.integers(0, SEED_MAX, dtype=np.uint64))
            if value not in seen:
                seen.add(value)
                drawn.append(value)
        return drawn
    raise ValueError(f"unknown seed mode {mode!r}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project", default="character-lora")
    parser.add_argument("--character", default="Wren")
    parser.add_argument("--brief", default=DEFAULT_BRIEF)
    parser.add_argument("--model", default=DEFAULT_MODEL)
    parser.add_argument("--n", type=int, default=48, help="Renders. Runbook asks 40-60.")
    parser.add_argument("--seed-base", type=int, default=100_000)
    parser.add_argument(
        "--seed-mode", default="arithmetic", choices=["arithmetic", "scattered"],
        help="Consecutive-ish run, or drawn across the whole 64-bit space.",
    )
    parser.add_argument(
        "--label", default="anchor",
        help="Output subdirectory, so two sweeps can be compared side by side.",
    )
    parser.add_argument("--k", type=int, default=None, help="Clusters. Default ~n/8.")
    parser.add_argument("--gate", type=float, default=ANCHOR_GATE)
    parser.add_argument("--steps", type=int, default=None)
    parser.add_argument("--guidance", type=float, default=None)
    parser.add_argument(
        "--embed-only",
        action="store_true",
        help="Skip rendering; embed and cluster whatever is already on disk.",
    )
    parser.add_argument(
        "--largest-face",
        action="store_true",
        help=(
            "Embed the largest face when a render holds several, instead of "
            "discarding the render. A festival or street prompt puts bystanders "
            "in most frames; the subject is still the biggest face, and dropping "
            "33 of 48 renders over it leaves too little to cast from."
        ),
    )
    args = parser.parse_args()

    out_root = ROOT / "projects" / args.project / args.label
    renders_dir = out_root / "renders"
    sheets_dir = out_root / "sheets"
    renders_dir.mkdir(parents=True, exist_ok=True)
    sheets_dir.mkdir(parents=True, exist_ok=True)

    prompt = build_prompt(args.brief, CONDITION)
    seeds = _seeds(args.n, args.seed_base, args.seed_mode)
    span = max(seeds) - min(seeds)
    print(f"anchor selection: {args.n} close-ups on {args.model}")
    print(f"seeds: {args.seed_mode}, spanning {span:,}")
    print(f"prompt: {prompt}\n")

    # ---------------------------------------------------------------- render
    timings = RenderTimings.load()
    route = route_key("comfyui_image", "bundled", "juggernaut-xl-ragnarok-txt2img.json")
    image_client = ComfyUIClient()
    generator = ComfyUIImage()

    records: list[dict] = []
    failures: list[str] = []
    contended = 0
    started = time.time()

    for index, seed in enumerate(seeds):
        path = renders_dir / f"cu_s{seed}.png"
        if path.is_file():
            records.append({"index": index, "seed": seed, "path": str(path), "reused": True})
            continue
        if args.embed_only:
            continue

        request = {
            "prompt": prompt,
            "workflow_variant": "juggernaut_xl_ragnarok",
            "checkpoint_name": args.model,
            "seed": int(seed),
            "output_path": str(path),
        }
        if args.steps is not None:
            request["steps"] = args.steps
        if args.guidance is not None:
            request["guidance"] = args.guidance

        # Timed from submission, so a busy machine would record the queue as our
        # render. Measure first and decline to record rather than poison the
        # median - see the timings trap in HANDOFF.
        depth = image_client.queue_depth()
        render_started = time.time()
        outcome = generator.execute(request)
        elapsed = time.time() - render_started

        if not outcome.success:
            failures.append(f"seed {seed}: {outcome.error}")
            print(f"  [{index + 1:>2}/{args.n}] seed {seed} FAILED: {outcome.error}")
            continue
        if depth == 0:
            timings.record(route, elapsed, pixels=832 * 1216)
        else:
            contended += 1
        records.append(
            {"index": index, "seed": seed, "path": str(path), "seconds": round(elapsed, 2)}
        )
        done = len(records)
        rate = (time.time() - started) / max(1, done)
        left = (args.n - done) * rate / 60
        print(
            f"  [{index + 1:>2}/{args.n}] seed {seed}  {elapsed:5.1f}s"
            f"   ~{left:.0f} min left"
        )

    if not args.embed_only:
        timings.save()
    render_minutes = (time.time() - started) / 60
    print(f"\nrendered {len(records)} of {args.n} in {render_minutes:.1f} min")
    if failures:
        print(f"{len(failures)} failure(s):")
        for line in failures[:10]:
            print("   ", line)

    # ----------------------------------------------------------------- embed
    if not embeddings_available():
        print("\nFAIL: insightface/onnxruntime unavailable in this venv; cannot embed.")
        return 1

    print("\nembedding faces (CPU ArcFace)...")
    vectors: list[np.ndarray] = []
    usable: list[dict] = []
    for record in records:
        faces = faces_in(record["path"])
        record["faces"] = len(faces)
        if len(faces) == 0 or (len(faces) > 1 and not args.largest_face):
            continue
        # faces_in sorts largest first, so [0] is the subject in a portrait.
        record["bystanders"] = len(faces) - 1
        embedding = getattr(faces[0], "normed_embedding", None)
        if embedding is None:
            record["faces"] = 0
            continue
        record["vector_index"] = len(vectors)
        vectors.append(np.asarray(embedding, dtype=np.float32))
        usable.append(record)

    no_face = [r for r in records if r.get("faces") == 0]
    many_face = [r for r in records if r.get("faces", 0) > 1]
    print(
        f"  {len(usable)} usable (exactly one face), "
        f"{len(no_face)} with no detectable face, "
        f"{len(many_face)} with more than one"
    )
    if len(vectors) < 4:
        print("\nFAIL: fewer than four embeddable renders; nothing to cluster.")
        return 1

    matrix = np.stack(vectors)
    np.savez(
        out_root / "embeddings.npz",
        vectors=matrix,
        paths=np.array([r["path"] for r in usable]),
        seeds=np.array([r["seed"] for r in usable]),
        bystanders=np.array([r.get("bystanders", 0) for r in usable]),
    )

    # --------------------------------------------------------------- cluster
    k = args.k if args.k is not None else suggested_k(len(vectors))
    print(f"\nclustering {len(vectors)} embeddings into k={k} (k-means++)...")
    selection = choose_anchor(matrix, k=k, gate=args.gate)

    for stats in selection.clusters:
        cos = stats.mean_pairwise_cos
        cos_text = "n/a" if cos is None else f"{cos:.4f}"
        marker = " <- chosen" if selection.chosen and stats.label == selection.chosen.label else ""
        print(
            f"  cluster {stats.label}: {stats.size:>2} members  "
            f"msd {stats.mean_sq_distance:.4f}  mean pairwise cos {cos_text}{marker}"
        )
    for note in selection.notes:
        print(f"  ! {note}")

    anchor_path: Path | None = None
    if selection.anchor_index is not None:
        anchor_record = usable[selection.anchor_index]
        anchor_path = out_root / "anchor.png"
        shutil.copyfile(anchor_record["path"], anchor_path)
        print(f"\nanchor: seed {anchor_record['seed']}  ->  {anchor_path}")

    # -------------------------------------------------------------- evidence
    label_by_vector: dict[int, int] = {}
    for stats in selection.clusters:
        for member in stats.members:
            label_by_vector[member] = stats.label

    all_items = []
    for record in records:
        vector_index = record.get("vector_index")
        if vector_index is None:
            caption = f"s{record['seed']}"
            sub = f"{record.get('faces', 0)} faces - not clustered"
            accent = None
        else:
            label = label_by_vector.get(vector_index, -1)
            caption = f"s{record['seed']}  c{label}"
            sub = "MEDOID" if vector_index == selection.anchor_index else ""
            accent = ACCENTS[label % len(ACCENTS)] if label >= 0 else None
        all_items.append(SheetItem(Path(record["path"]), caption, sub, accent))

    all_sheet = labelled_sheet(
        all_items,
        sheets_dir / "all_renders.png",
        columns=8,
        title=f"{args.character} - {len(records)} renders, {args.model}, coloured by cluster",
    )

    chosen_sheet = None
    if selection.chosen is not None:
        accent = ACCENTS[selection.chosen.label % len(ACCENTS)]
        cos = selection.chosen.mean_pairwise_cos or 0.0
        items = []
        for member in selection.chosen.members:
            record = usable[member]
            items.append(
                SheetItem(
                    Path(record["path"]),
                    f"s{record['seed']}",
                    "MEDOID -> anchor" if member == selection.anchor_index else "",
                    accent,
                )
            )
        chosen_sheet = labelled_sheet(
            items,
            sheets_dir / "chosen_cluster.png",
            columns=6,
            title=(
                f"chosen cluster {selection.chosen.label} - {selection.chosen.size} members, "
                f"mean pairwise ArcFace {cos:.3f} "
                f"({'PASS' if selection.passed else 'FAIL'} vs {args.gate:.2f})"
            ),
        )

    report = {
        "version": "1.0",
        "phase": "runbook phase 2 - choose the anchor",
        "character": args.character,
        "brief": args.brief,
        "prompt": prompt,
        "model": args.model,
        "condition": CONDITION,
        "requested_renders": args.n,
        "seed_base": args.seed_base,
        "seed_step": SEED_STEP,
        "seed_mode": args.seed_mode,
        "seed_span": span,
        "render_minutes": round(render_minutes, 2),
        "contended_renders": contended,
        "failures": failures,
        "face_detection": {
            "usable_one_face": len(usable),
            "no_face": [r["seed"] for r in no_face],
            "multiple_faces": [r["seed"] for r in many_face],
        },
        "k": k,
        "selection": selection.as_dict(),
        "gate_convention": (
            "raw mean pairwise ArcFace cosine, NOT the rescaled "
            "face_identity_stability score (which maps 0.21-0.70 onto 0-1)"
        ),
        "anchor": None
        if anchor_path is None
        else {
            "path": str(anchor_path),
            "source": usable[selection.anchor_index]["path"],
            "seed": usable[selection.anchor_index]["seed"],
        },
        "renders": records,
        "sheets": {
            "all": None if all_sheet is None else str(all_sheet),
            "chosen_cluster": None if chosen_sheet is None else str(chosen_sheet),
        },
    }
    report_path = out_root / "anchor_report.json"
    report_path.write_text(json.dumps(report, indent=2), encoding="utf-8")

    print(f"\nreport: {report_path}")
    print(f"sheets: {all_sheet}")
    if chosen_sheet:
        print(f"        {chosen_sheet}")
    verdict = "PASSED" if selection.passed else "FAILED"
    chosen_cos = (
        selection.chosen.mean_pairwise_cos
        if selection.chosen and selection.chosen.mean_pairwise_cos is not None
        else 0.0
    )
    print(f"\nGATE {verdict}: {chosen_cos:.4f} vs {args.gate:.2f} required")
    return 0 if selection.passed else 2


if __name__ == "__main__":
    raise SystemExit(main())
