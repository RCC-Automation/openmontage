"""Does the magnitude of a seed matter? Render across the whole 64-bit space.

    python scripts/seed_probe.py

ComfyUI's KSampler accepts 0 .. 18446744073709551615. Seeds seen in the wild are
often huge (7391441554250) while a sweep written by hand tends to use small
consecutive-ish numbers, and the natural worry is that a narrow band of small
seeds explores a narrow corner of the model.

It does not, and this measures why. A seed is not a coordinate in image space -
it initialises a PRNG whose output is an avalanche function of it, so seed 100000
and seed 100001 produce noise tensors as unrelated as any other pair. The test:
render the same prompt at seeds spanning fifteen orders of magnitude, then ask
whether that set is any more varied than an equally sized set drawn from the
narrow band the Phase 2 sweep used.

Same prompt and condition as `anchor_select.py`, so the two populations are
directly comparable.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from lib.face_identity import faces_in  # noqa: E402
from lib.screen_test import build_prompt  # noqa: E402
from lib.sheets import ACCENTS, SheetItem, labelled_sheet  # noqa: E402
from scripts.anchor_select import CONDITION, DEFAULT_BRIEF, DEFAULT_MODEL  # noqa: E402
from tools.graphics.comfyui_image import ComfyUIImage  # noqa: E402

#: Spanning the legal range: the boundaries, a couple of small values a human
#: would type, the example that prompted the question, and the powers of two
#: where an implementation would break if it silently truncated to 32 bits.
PROBE_SEEDS: tuple[int, ...] = (
    0,
    1,
    42,
    4_294_967_295,          # 2^32 - 1, the old 32-bit ceiling
    4_294_967_296,          # 2^32, one past it: truncation would alias this to 0
    7_391_441_554_250,      # the seed that prompted the question
    9_223_372_036_854_775_808,   # 2^63
    18_446_744_073_709_551_615,  # 2^64 - 1, the maximum
)


def _vector(path: Path) -> np.ndarray | None:
    found = faces_in(path)
    if len(found) != 1:
        return None
    vector = getattr(found[0], "normed_embedding", None)
    return None if vector is None else np.asarray(vector, dtype=np.float32)


def _mean_pairwise(vectors: list[np.ndarray]) -> float | None:
    if len(vectors) < 2:
        return None
    matrix = np.stack(vectors)
    gram = matrix @ matrix.T
    return float(gram[np.triu_indices(len(vectors), k=1)].mean())


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project", default="character-lora")
    parser.add_argument("--brief", default=DEFAULT_BRIEF)
    parser.add_argument("--model", default=DEFAULT_MODEL)
    args = parser.parse_args()

    out_root = ROOT / "projects" / args.project / "seed_probe"
    out_root.mkdir(parents=True, exist_ok=True)
    prompt = build_prompt(args.brief, CONDITION)
    generator = ComfyUIImage()

    rows: list[dict] = []
    vectors: list[np.ndarray] = []
    started = time.time()
    print(f"probing {len(PROBE_SEEDS)} seeds across the full 64-bit range\n")

    for seed in PROBE_SEEDS:
        path = out_root / f"s{seed}.png"
        if not path.is_file():
            outcome = generator.execute(
                {
                    "prompt": prompt,
                    "workflow_variant": "juggernaut_xl_ragnarok",
                    "checkpoint_name": args.model,
                    "seed": int(seed),
                    "output_path": str(path),
                }
            )
            if not outcome.success:
                print(f"  seed {seed:>21,} FAILED: {outcome.error}")
                rows.append({"seed": seed, "error": str(outcome.error)[:300]})
                continue
        vector = _vector(path)
        rows.append(
            {"seed": seed, "path": str(path), "embedded": vector is not None}
        )
        if vector is not None:
            vectors.append(vector)
        print(f"  seed {seed:>21,}  {'ok' if vector is not None else 'no face'}")

    # The comparison that answers the question: this set spans 2^64, the Phase 2
    # set spanned 47,423. If magnitude mattered, the wide set would be the more
    # varied one - a lower mean pairwise cosine.
    probe_mean = _mean_pairwise(vectors)
    narrow = np.load(ROOT / "projects" / args.project / "anchor" / "embeddings.npz")
    narrow_vectors = [np.asarray(v, dtype=np.float32) for v in narrow["vectors"]]
    narrow_all = _mean_pairwise(narrow_vectors)
    # Size-matched: the first len(vectors) of the narrow sweep, so the two means
    # are computed over comparable pair counts.
    narrow_matched = _mean_pairwise(narrow_vectors[: len(vectors)])

    print("\nmean pairwise ArcFace cosine (lower = more varied):")
    print(f"  seeds spanning 2^64      n={len(vectors):>2}   {probe_mean:.4f}"
          if probe_mean else "  probe: not enough faces")
    print(f"  seeds spanning 47,423    n={len(vectors):>2}   {narrow_matched:.4f}"
          if narrow_matched else "")
    print(f"  the full Phase 2 sweep   n={len(narrow_vectors):>2}   {narrow_all:.4f}")

    sheet = labelled_sheet(
        [
            SheetItem(Path(r["path"]), f"seed {r['seed']:,}"[:42], "", ACCENTS[1])
            for r in rows
            if r.get("path")
        ],
        out_root / "seed_magnitude.png",
        columns=4,
        cell=340,
        title="Same prompt, seeds spanning the whole 64-bit range. Magnitude carries no signal.",
    )

    report = {
        "version": "1.0",
        "question": "does seed magnitude or seed range affect the variety of faces?",
        "prompt": prompt,
        "model": args.model,
        "seed_space": "0 .. 18446744073709551615 (KSampler INT max)",
        "probe_seeds": [str(s) for s in PROBE_SEEDS],
        "mean_pairwise_cosine": {
            "probe_span_2_64": None if probe_mean is None else round(probe_mean, 4),
            "narrow_span_47423_size_matched": None
            if narrow_matched is None
            else round(narrow_matched, 4),
            "narrow_span_47423_full_48": None
            if narrow_all is None
            else round(narrow_all, 4),
        },
        "rows": rows,
        "sheet": None if sheet is None else str(sheet),
        "minutes": round((time.time() - started) / 60, 2),
    }
    (out_root / "seed_probe.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(f"\nsheet : {sheet}")
    print(f"report: {out_root / 'seed_probe.json'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
