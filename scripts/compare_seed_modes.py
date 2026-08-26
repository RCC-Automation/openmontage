"""Arithmetic seeds versus scattered seeds: does the pattern change the variety?

    python scripts/compare_seed_modes.py

Two sweeps, same prompt, same model, same condition, same n. The only difference
is how the seeds were chosen: `base + i * 1009` against 48 draws from the whole
64-bit space. Everything else is held so the comparison means something.

The question is not whether seed *distance* matters - it does not, measured at
r = +0.010 over the 1128 pairs inside the arithmetic sweep. It is whether an
arithmetic *progression* explores slightly less than scattered draws, which that
test structurally cannot see because every pair in it comes from the same
progression. An 8-seed probe hinted that it might, at the 1.6th percentile of the
bootstrap. Eight is not enough to conclude anything, so this runs it at 48.

Reported with a permutation test rather than a t-test: the pairwise cosines
within a set are not independent - every render appears in n-1 pairs - so the
usual standard error is wrong and would overstate significance.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def _load(path: Path) -> tuple[np.ndarray, np.ndarray]:
    data = np.load(path)
    return data["vectors"].astype(np.float64), data["seeds"]


def _mean_pairwise(vectors: np.ndarray) -> float:
    gram = vectors @ vectors.T
    return float(gram[np.triu_indices(len(vectors), k=1)].mean())


def _distinct_faces(vectors: np.ndarray, threshold: float) -> int:
    """Single-linkage components at `threshold` - how many faces were found."""
    gram = vectors @ vectors.T
    np.fill_diagonal(gram, -1.0)
    adjacent = gram >= threshold
    seen: set[int] = set()
    components = 0
    for start in range(len(vectors)):
        if start in seen:
            continue
        components += 1
        stack = [start]
        while stack:
            node = stack.pop()
            if node in seen:
                continue
            seen.add(node)
            stack.extend(np.flatnonzero(adjacent[node]).tolist())
    return components


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project", default="character-lora")
    parser.add_argument("--a", default="anchor", help="First sweep's label.")
    parser.add_argument("--b", default="anchor-scattered", help="Second sweep's label.")
    parser.add_argument("--threshold", type=float, default=0.55)
    parser.add_argument("--permutations", type=int, default=20000)
    args = parser.parse_args()

    root = ROOT / "projects" / args.project
    paths = {args.a: root / args.a / "embeddings.npz", args.b: root / args.b / "embeddings.npz"}
    for label, path in paths.items():
        if not path.is_file():
            print(f"FAIL: no embeddings for {label} at {path}")
            return 1

    va, seeds_a = _load(paths[args.a])
    vb, seeds_b = _load(paths[args.b])
    print(f"{args.a:20s} n={len(va):<3} span {int(max(seeds_a) - min(seeds_a)):,}")
    print(f"{args.b:20s} n={len(vb):<3} span {int(max(seeds_b) - min(seeds_b)):,}\n")

    mean_a, mean_b = _mean_pairwise(va), _mean_pairwise(vb)
    faces_a = _distinct_faces(va, args.threshold)
    faces_b = _distinct_faces(vb, args.threshold)

    print(f"{'':20s} {'mean pairwise':>14} {'distinct faces':>15}")
    print(f"{args.a:20s} {mean_a:>14.4f} {faces_a:>15}")
    print(f"{args.b:20s} {mean_b:>14.4f} {faces_b:>15}")
    print(f"{'difference':20s} {mean_b - mean_a:>+14.4f} {faces_b - faces_a:>+15}")

    # Permutation test. Pool both populations, re-split at the observed sizes,
    # and ask how often chance produces a gap this large. This respects the
    # dependence between pairs because whole renders are reshuffled, not pairs.
    pooled = np.vstack([va, vb])
    observed = abs(mean_b - mean_a)
    rng = np.random.default_rng(0)
    extreme = 0
    for _ in range(args.permutations):
        order = rng.permutation(len(pooled))
        left = pooled[order[: len(va)]]
        right = pooled[order[len(va) :]]
        if abs(_mean_pairwise(right) - _mean_pairwise(left)) >= observed:
            extreme += 1
    p_value = (extreme + 1) / (args.permutations + 1)

    print(f"\npermutation test, {args.permutations:,} reshuffles")
    print(f"  observed |difference| = {observed:.4f}")
    print(f"  p = {p_value:.4f}")
    verdict = (
        "the two seed patterns explore differently"
        if p_value < 0.05
        else "no detectable difference: seed pattern does not change the variety"
    )
    print(f"  -> {verdict}")

    report = {
        "version": "1.0",
        "question": "does an arithmetic seed progression explore less than scattered draws?",
        "sweeps": {
            args.a: {
                "n": len(va),
                "span": int(max(seeds_a) - min(seeds_a)),
                "mean_pairwise": round(mean_a, 4),
                "distinct_faces": faces_a,
            },
            args.b: {
                "n": len(vb),
                "span": int(max(seeds_b) - min(seeds_b)),
                "mean_pairwise": round(mean_b, 4),
                "distinct_faces": faces_b,
            },
        },
        "distinct_face_threshold": args.threshold,
        "permutation_test": {
            "permutations": args.permutations,
            "observed_abs_difference": round(observed, 4),
            "p_value": round(p_value, 4),
            "significant_at_0.05": bool(p_value < 0.05),
        },
        "verdict": verdict,
    }
    out = root / "seed_mode_comparison.json"
    out.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(f"\nreport: {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
