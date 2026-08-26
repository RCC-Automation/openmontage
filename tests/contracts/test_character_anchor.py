"""Contracts for anchor selection: clustering, cohesion, the medoid, the gate.

The expensive failure this guards against is a gate that reads as passed when it
was not measured - a cluster of two scoring 1.0, or a rescaled score compared
against a raw threshold. Both would send hours of GPU at a dataset built on a
face the model cannot actually reproduce.
"""

from __future__ import annotations

import numpy as np
import pytest

from lib.character_anchor import (
    ANCHOR_GATE,
    choose_anchor,
    cluster_embeddings,
    cluster_stats,
    mean_pairwise_cosine,
    medoid_index,
    suggested_k,
)


def _unit(vector) -> np.ndarray:
    array = np.asarray(vector, dtype=np.float32)
    return array / np.linalg.norm(array)


def _tight_group(center, n, jitter, rng) -> list[np.ndarray]:
    """n unit vectors clustered around `center` - a stand-in for one face."""
    base = _unit(center)
    return [_unit(base + rng.normal(0, jitter, size=len(base))) for _ in range(n)]


class TestSuggestedK:
    def test_follows_the_runbooks_n_over_eight(self):
        assert suggested_k(48) == 6
        assert suggested_k(40) == 5

    def test_never_below_two_or_above_the_population(self):
        assert suggested_k(3) == 2
        assert suggested_k(1) == 1
        assert suggested_k(0) == 1


class TestMeanPairwiseCosine:
    def test_identical_vectors_score_one(self):
        vectors = [_unit([1.0, 0.0, 0.0])] * 4
        assert mean_pairwise_cosine(vectors) == pytest.approx(1.0, abs=1e-5)

    def test_orthogonal_vectors_score_zero(self):
        vectors = [_unit([1.0, 0.0]), _unit([0.0, 1.0])]
        assert mean_pairwise_cosine(vectors) == pytest.approx(0.0, abs=1e-5)

    def test_none_below_two_vectors(self):
        # Not 0.0 and not 1.0: a single member has no measured cohesion, and
        # either number would be read as one by whatever prints the report.
        assert mean_pairwise_cosine([_unit([1.0, 0.0])]) is None
        assert mean_pairwise_cosine([]) is None


class TestMedoid:
    def test_picks_the_member_closest_to_all_others(self):
        # Three near-identical vectors plus one outlier; the medoid must be one
        # of the three, never the outlier.
        rng = np.random.default_rng(0)
        vectors = _tight_group([1.0, 0.0, 0.0], 3, 0.01, rng)
        vectors.append(_unit([0.0, 1.0, 0.0]))
        assert medoid_index(vectors) < 3

    def test_single_vector_is_its_own_medoid(self):
        assert medoid_index([_unit([1.0, 0.0])]) == 0


class TestClustering:
    def test_separates_two_populations(self):
        rng = np.random.default_rng(1)
        vectors = _tight_group([1.0, 0.0, 0.0], 6, 0.02, rng) + _tight_group(
            [0.0, 1.0, 0.0], 6, 0.02, rng
        )
        labels, centroids = cluster_embeddings(vectors, 2, random_state=0)
        assert len(set(labels.tolist())) == 2
        assert len(set(labels[:6].tolist())) == 1
        assert len(set(labels[6:].tolist())) == 1
        assert centroids.shape == (2, 3)

    def test_is_reproducible_across_runs(self):
        # The evidence has to be re-derivable without re-rendering, so the same
        # embeddings must always give the same partition.
        rng = np.random.default_rng(2)
        vectors = _tight_group([1.0, 0.0, 0.0], 5, 0.05, rng) + _tight_group(
            [0.0, 0.0, 1.0], 5, 0.05, rng
        )
        first, _ = cluster_embeddings(vectors, 2, random_state=0)
        second, _ = cluster_embeddings(vectors, 2, random_state=0)
        assert first.tolist() == second.tolist()

    def test_k_cannot_exceed_the_population(self):
        vectors = [_unit([1.0, 0.0]), _unit([0.0, 1.0])]
        labels, centroids = cluster_embeddings(vectors, 9)
        assert centroids.shape[0] == 2

    def test_stats_are_ordered_tightest_first(self):
        rng = np.random.default_rng(3)
        vectors = _tight_group([1.0, 0.0, 0.0], 5, 0.005, rng) + _tight_group(
            [0.0, 1.0, 0.0], 5, 0.08, rng
        )
        labels, centroids = cluster_embeddings(vectors, 2, random_state=0)
        stats = cluster_stats(vectors, labels, centroids)
        assert stats[0].mean_sq_distance <= stats[1].mean_sq_distance
        assert sum(s.size for s in stats) == 10
        assert all(s.medoid in s.members for s in stats)


class TestChooseAnchor:
    def test_passes_when_a_cluster_is_genuinely_tight(self):
        rng = np.random.default_rng(4)
        vectors = _tight_group([1.0, 0.0, 0.0], 8, 0.005, rng) + _tight_group(
            [0.0, 1.0, 0.0], 8, 0.30, rng
        )
        selection = choose_anchor(vectors, k=2)
        assert selection.passed
        assert selection.chosen is not None
        assert selection.chosen.mean_pairwise_cos >= ANCHOR_GATE
        assert selection.anchor_index in selection.chosen.members

    def test_fails_loudly_when_nothing_is_tight_enough(self):
        # The Phase 2 case: renders that resemble each other but are not one
        # person. A failed gate must report, never raise and never silently pass.
        rng = np.random.default_rng(5)
        vectors = [_unit(rng.normal(0, 1, size=16)) for _ in range(24)]
        selection = choose_anchor(vectors, k=3)
        assert not selection.passed
        assert any("GATE FAILED" in note for note in selection.notes)
        # Still yields an anchor: the best available is what Phase 3 conditions
        # on, and refusing to name one would lose the measurement.
        assert selection.anchor_index is not None

    def test_a_tight_pair_cannot_win_on_size_two(self):
        # Two renders that happen to match score ~1.0 and mean nothing. The floor
        # exists so that number never becomes the anchor's justification.
        rng = np.random.default_rng(6)
        vectors = _tight_group([1.0, 0.0, 0.0], 2, 0.001, rng) + _tight_group(
            [0.0, 1.0, 0.0], 8, 0.05, rng
        )
        selection = choose_anchor(vectors, k=2, min_size=4)
        assert selection.chosen is not None
        assert selection.chosen.size >= 4
        assert any("below the" in note for note in selection.notes)

    def test_reports_rather_than_raises_on_too_little_data(self):
        selection = choose_anchor([_unit([1.0, 0.0])])
        assert not selection.passed
        assert selection.anchor_index is None
        assert selection.clusters == []
        assert selection.notes

    def test_gate_is_configurable_and_recorded(self):
        rng = np.random.default_rng(7)
        vectors = _tight_group([1.0, 0.0, 0.0], 6, 0.20, rng)
        strict = choose_anchor(vectors, k=1, gate=0.99)
        lenient = choose_anchor(vectors, k=1, gate=0.10)
        assert not strict.passed
        assert lenient.passed
        assert strict.as_dict()["gate"] == 0.99
        assert lenient.as_dict()["gate"] == 0.10
