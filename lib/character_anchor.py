"""Choosing a character's anchor image: cluster the renders, promote the medoid.

A character LoRA needs 20-40 images of one person. You start with none. The
obvious move is to render a batch from the description and pick the one you
like, and it is the wrong move twice over: taste is not a measurement, and one
image is a worse starting point than eight mutually consistent ones.

This is "The Chosen One" adapted to what we measured here. Render many from the
description alone, embed every face with ArcFace, cluster, and take the tightest
cluster's *medoid* - the member closest to all the others. The cluster is the
evidence that the face is reproducible at all; the medoid is its most typical
member, which is a different thing from its most flattering one.

Why it works on a model that drifts: `juggernautXL_ragnarok` scores 0.31 on
identity across seeds (DECISIONS #38), which is a statement about the *whole*
population of its renders. Inside that population there are still neighbourhoods
where the same face recurs. Clustering finds one; the population mean cannot.

Everything here is cosine on unit-norm ArcFace vectors, so Euclidean k-means is
spherical k-means up to centroid normalisation: for unit a, b,
``||a - b||^2 == 2 - 2 * cos(a, b)``. Distance and similarity are the same
ranking, which is why the runbook's mean-squared-distance criterion and the
mean-pairwise-cosine gate never disagree about which cluster is tightest.

**Numbers here are raw cosines, never the rescaled score.** `face_identity`
exposes `face_identity_stability`, which maps [0.21, 0.70] onto [0, 1] for
reporting; a raw 0.80 would clamp to 1.0 there. The gate is on the raw value,
and a report that shows one without the other invites exactly that confusion -
so `anchor_report` carries both, labelled.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Sequence

import numpy as np

__all__ = [
    "ANCHOR_GATE",
    "AnchorSelection",
    "ClusterStats",
    "choose_anchor",
    "cluster_embeddings",
    "cluster_stats",
    "mean_pairwise_cosine",
    "medoid_index",
    "suggested_k",
]

#: Raw mean pairwise ArcFace cosine the promoted cluster must reach.
#:
#: Not a rescaled score. Calibrated context from this machine: genuinely
#: different people sit at 0.10-0.21, one character across seeds at 0.36-0.67,
#: and a matched-framing reference render reached 0.93. A cluster below 0.80 is
#: not a character, it is a neighbourhood - and the runbook's instruction when
#: it fails is to tighten the description rather than lower the bar.
ANCHOR_GATE = 0.80

#: A cluster smaller than this is not a dataset seed even if it is tight.
#: Two renders that happen to resemble each other will score near 1.0 and mean
#: nothing; the runbook wants "~8 mutually consistent images" to start from.
MIN_COHESIVE_CLUSTER = 4


def suggested_k(n: int) -> int:
    """The runbook's k ~ n/8, floored at 2 and never exceeding the population."""
    if n < 2:
        return 1
    return max(2, min(n, round(n / 8)))


def mean_pairwise_cosine(vectors: Sequence[np.ndarray]) -> float | None:
    """Mean cosine over every unordered pair. None below two vectors.

    None rather than 0.0 or 1.0: a single-member cluster has no measured
    cohesion, and either number would be read as one.
    """
    matrix = np.asarray(vectors, dtype=np.float32)
    if matrix.ndim != 2 or matrix.shape[0] < 2:
        return None
    gram = matrix @ matrix.T
    upper = gram[np.triu_indices(matrix.shape[0], k=1)]
    return float(upper.mean())


def medoid_index(vectors: Sequence[np.ndarray]) -> int:
    """Index of the member with the highest mean cosine to the others.

    The medoid, not the mean. A centroid is an average of faces and is not a
    face; the anchor has to be an image we can actually condition on.
    """
    matrix = np.asarray(vectors, dtype=np.float32)
    if matrix.shape[0] == 1:
        return 0
    gram = matrix @ matrix.T
    np.fill_diagonal(gram, 0.0)
    means = gram.sum(axis=1) / (matrix.shape[0] - 1)
    return int(np.argmax(means))


def cluster_embeddings(
    vectors: Sequence[np.ndarray], k: int, *, random_state: int = 0
) -> tuple[np.ndarray, np.ndarray]:
    """k-means++ over unit-norm face vectors. Returns (labels, centroids).

    `random_state` is pinned so a rerun over the same embeddings reproduces the
    same partition - the evidence has to be re-derivable without re-rendering.
    """
    from sklearn.cluster import KMeans

    matrix = np.asarray(vectors, dtype=np.float32)
    k = max(1, min(int(k), matrix.shape[0]))
    model = KMeans(n_clusters=k, init="k-means++", n_init=10, random_state=random_state)
    labels = model.fit_predict(matrix)
    return labels.astype(int), model.cluster_centers_.astype(np.float32)


@dataclass
class ClusterStats:
    """One cluster, measured both ways the runbook asks for."""

    label: int
    members: list[int]
    #: Mean squared Euclidean distance to the k-means centroid. Lower is tighter.
    #: This is the runbook's cohesion criterion.
    mean_sq_distance: float
    #: Mean pairwise cosine among members. This is what the gate reads.
    mean_pairwise_cos: float | None
    #: Index into `members` of the medoid, and the original render index.
    medoid: int | None

    @property
    def size(self) -> int:
        return len(self.members)

    def as_dict(self) -> dict[str, Any]:
        return {
            "label": self.label,
            "size": self.size,
            "members": list(self.members),
            "mean_sq_distance": round(self.mean_sq_distance, 5),
            "mean_pairwise_cos": (
                None if self.mean_pairwise_cos is None else round(self.mean_pairwise_cos, 4)
            ),
            "medoid": self.medoid,
        }


def cluster_stats(
    vectors: Sequence[np.ndarray],
    labels: Sequence[int],
    centroids: Sequence[np.ndarray],
) -> list[ClusterStats]:
    """Measure every cluster. Ordered tightest first by mean squared distance."""
    matrix = np.asarray(vectors, dtype=np.float32)
    label_array = np.asarray(labels, dtype=int)
    centroid_array = np.asarray(centroids, dtype=np.float32)

    stats: list[ClusterStats] = []
    for label in sorted(set(label_array.tolist())):
        members = np.flatnonzero(label_array == label)
        member_vectors = matrix[members]
        deltas = member_vectors - centroid_array[label]
        msd = float((deltas * deltas).sum(axis=1).mean())
        local_medoid = medoid_index(member_vectors)
        stats.append(
            ClusterStats(
                label=int(label),
                members=[int(i) for i in members],
                mean_sq_distance=msd,
                mean_pairwise_cos=mean_pairwise_cosine(member_vectors),
                medoid=int(members[local_medoid]),
            )
        )
    return sorted(stats, key=lambda s: s.mean_sq_distance)


@dataclass
class AnchorSelection:
    """The outcome: which cluster won, which render is the anchor, did it pass."""

    clusters: list[ClusterStats]
    chosen: ClusterStats | None
    anchor_index: int | None
    gate: float = ANCHOR_GATE
    min_size: int = MIN_COHESIVE_CLUSTER
    notes: list[str] = field(default_factory=list)

    @property
    def passed(self) -> bool:
        return bool(
            self.chosen is not None
            and self.chosen.mean_pairwise_cos is not None
            and self.chosen.mean_pairwise_cos >= self.gate
        )

    def as_dict(self) -> dict[str, Any]:
        return {
            "gate": self.gate,
            "min_cluster_size": self.min_size,
            "passed": self.passed,
            "chosen_cluster": None if self.chosen is None else self.chosen.as_dict(),
            "anchor_index": self.anchor_index,
            "clusters": [c.as_dict() for c in self.clusters],
            "notes": list(self.notes),
        }


def choose_anchor(
    vectors: Sequence[np.ndarray],
    *,
    k: int | None = None,
    min_size: int = MIN_COHESIVE_CLUSTER,
    gate: float = ANCHOR_GATE,
    random_state: int = 0,
) -> AnchorSelection:
    """Cluster, pick the tightest cluster big enough to be a seed, promote its medoid.

    Reports rather than raises when the gate fails: a failed gate is a finding
    about the description, and the caller needs the numbers to act on it.
    """
    matrix = np.asarray(vectors, dtype=np.float32)
    notes: list[str] = []
    if matrix.ndim != 2 or matrix.shape[0] < 2:
        return AnchorSelection(
            clusters=[],
            chosen=None,
            anchor_index=None,
            gate=gate,
            min_size=min_size,
            notes=["fewer than two embeddable renders; nothing to cluster"],
        )

    resolved_k = suggested_k(matrix.shape[0]) if k is None else max(1, int(k))
    labels, centroids = cluster_embeddings(matrix, resolved_k, random_state=random_state)
    stats = cluster_stats(matrix, labels, centroids)

    eligible = [s for s in stats if s.size >= min_size]
    if not eligible:
        biggest = max(stats, key=lambda s: s.size) if stats else None
        notes.append(
            f"no cluster reached the {min_size}-member minimum "
            f"(largest was {biggest.size if biggest else 0}); "
            "the renders did not converge on any one face"
        )
        return AnchorSelection(
            clusters=stats,
            chosen=None,
            anchor_index=None,
            gate=gate,
            min_size=min_size,
            notes=notes,
        )

    chosen = eligible[0]
    # Worth saying out loud: the tightest cluster overall may be a pair that the
    # size floor excluded. Silently promoting the runner-up would read as if it
    # had won outright.
    if stats and stats[0].label != chosen.label:
        notes.append(
            f"cluster {stats[0].label} is tighter (msd {stats[0].mean_sq_distance:.4f}) "
            f"but has only {stats[0].size} member(s), below the {min_size} floor"
        )
    if chosen.mean_pairwise_cos is not None and chosen.mean_pairwise_cos < gate:
        notes.append(
            f"GATE FAILED: chosen cluster mean pairwise cosine "
            f"{chosen.mean_pairwise_cos:.4f} < {gate:.2f}. The runbook's reading is "
            "that the description is not specific enough - tighten it before "
            "spending GPU on a dataset."
        )
    return AnchorSelection(
        clusters=stats,
        chosen=chosen,
        anchor_index=chosen.medoid,
        gate=gate,
        min_size=min_size,
        notes=notes,
    )
