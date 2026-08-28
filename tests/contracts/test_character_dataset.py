"""Contracts for the dataset ladder: the plan, the bands, dedup, balance.

Most of what makes a character dataset bad is invisible in any single image and
obvious in the composition: one background repeated, one framing dominating, the
same pose counted three times. These are the checks that see the set rather than
the picture.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from lib.character_dataset import (
    ACCEPT_AT,
    BACKGROUNDS,
    HOLD_AT,
    LADDER,
    MAX_FAMILY_SHARE,
    DatasetEntry,
    balance,
    classify,
    find_phash_duplicates,
    hamming,
    phash,
    plan_dataset,
)


class TestPlan:
    def test_expands_the_quota_table_exactly(self):
        specs = plan_dataset()
        assert len(specs) == sum(family.target for family in LADDER)
        for family in LADDER:
            assert sum(1 for s in specs if s.family == family.name) == family.target

    def test_every_shot_varies_its_background(self):
        # Anything constant across the set is learned as part of the character.
        # With 36 shots over 18 backgrounds each may appear twice, never more.
        specs = plan_dataset()
        counts: dict[str, int] = {}
        for spec in specs:
            counts[spec.background] = counts.get(spec.background, 0) + 1
        assert max(counts.values()) <= 2
        assert len(counts) == len(BACKGROUNDS)

    def test_no_two_shots_share_every_axis(self):
        specs = plan_dataset()
        tuples = {
            (s.shot, s.background, s.lighting, s.angle, s.expression) for s in specs
        }
        assert len(tuples) == len(specs)

    def test_seeds_are_unique_and_reproducible(self):
        first = plan_dataset()
        second = plan_dataset()
        assert [s.seed for s in first] == [s.seed for s in second]
        assert len({s.seed for s in first}) == len(first)

    def test_the_variation_family_borrows_the_real_framings(self):
        # "Expression and lighting variation, spread across families" - not a
        # fourth look of its own.
        specs = plan_dataset()
        real = {f.shot for f in LADDER if f.shot}
        variation = [s for s in specs if s.family == "variation"]
        assert variation
        assert all(s.shot in real for s in variation)
        assert len({s.shot for s in variation}) > 1

    def test_prompt_carries_the_brief_and_every_axis(self):
        spec = plan_dataset()[0]
        prompt = spec.prompt("a clockwork heroine")
        assert prompt.startswith("a clockwork heroine")
        for part in (spec.shot, spec.background, spec.lighting, spec.expression):
            assert part in prompt

    def test_descriptor_records_what_varied_for_captioning(self):
        spec = plan_dataset()[5]
        descriptor = spec.descriptor()
        assert descriptor["family"] == spec.family
        assert descriptor["shot"] == spec.shot
        assert set(descriptor) == {
            "family", "shot", "pose", "expression", "background", "lighting", "angle"
        }

    def test_pose_varies_across_the_plan(self):
        # A reference adapter overrides pose the way it overrides framing. Unless
        # the prompt names an action, a FaceID-generated set comes back as one
        # standing smile repeated - and the LoRA learns the stance, not just her.
        specs = plan_dataset()
        assert len({s.pose for s in specs}) >= 8
        assert all(s.pose for s in specs)

    def test_pose_reaches_the_prompt(self):
        spec = plan_dataset()[3]
        assert spec.pose in spec.prompt("a character")


class TestBands:
    def test_the_three_bands(self):
        # Expressed against the constants, not against the numbers they happen
        # to hold: the bands were recalibrated once already (0.80/0.70 came from
        # a latent-reference measurement and no embedding-path render could
        # reach it), and a test written in literals fails on the recalibration
        # rather than on a regression.
        assert classify(1.0) == "accept"
        assert classify(ACCEPT_AT) == "accept"
        assert classify((ACCEPT_AT + HOLD_AT) / 2) == "hold"
        assert classify(HOLD_AT) == "hold"
        assert classify(HOLD_AT - 0.05) == "reject"

    def test_the_bands_are_ordered_and_reachable(self):
        # A gate nothing can pass is a bug, not a standard. The embedding path's
        # measured ceiling on this machine is 0.786.
        assert 0.0 < HOLD_AT < ACCEPT_AT < 0.786

    def test_unmeasured_is_not_a_rejection(self):
        # No detectable face is missing data, not evidence of a different person.
        assert classify(None) == "unmeasured"

    def test_bands_are_configurable(self):
        assert classify(0.65, accept_at=0.6, hold_at=0.5) == "accept"


class TestPerceptualHash:
    def test_identical_images_hash_identically(self, tmp_path: Path):
        pytest.importorskip("PIL")
        from PIL import Image

        rng = np.random.default_rng(0)
        pixels = (rng.random((64, 64, 3)) * 255).astype(np.uint8)
        first = tmp_path / "a.png"
        second = tmp_path / "b.png"
        Image.fromarray(pixels).save(first)
        Image.fromarray(pixels).save(second)
        assert phash(first) == phash(second)
        assert hamming(phash(first), phash(second)) == 0

    def test_different_images_differ(self, tmp_path: Path):
        pytest.importorskip("PIL")
        from PIL import Image

        rng = np.random.default_rng(1)
        a = tmp_path / "a.png"
        b = tmp_path / "b.png"
        Image.fromarray((rng.random((64, 64, 3)) * 255).astype(np.uint8)).save(a)
        Image.fromarray((rng.random((64, 64, 3)) * 255).astype(np.uint8)).save(b)
        assert hamming(phash(a), phash(b)) > 6

    def test_unreadable_path_is_none_not_an_exception(self, tmp_path: Path):
        assert phash(tmp_path / "missing.png") is None

    def test_duplicate_pairs_are_found(self, tmp_path: Path):
        pytest.importorskip("PIL")
        from PIL import Image

        rng = np.random.default_rng(2)
        pixels = (rng.random((64, 64, 3)) * 255).astype(np.uint8)
        paths = []
        for name in ("a", "b"):
            path = tmp_path / f"{name}.png"
            Image.fromarray(pixels).save(path)
            paths.append(path)
        other = tmp_path / "c.png"
        Image.fromarray((rng.random((64, 64, 3)) * 255).astype(np.uint8)).save(other)
        paths.append(other)

        pairs = find_phash_duplicates(paths)
        assert (0, 1, 0) in [(i, j, d) for i, j, d in pairs]
        assert not any(2 in (i, j) for i, j, _ in pairs)


class TestBalance:
    def test_flags_an_over_represented_family(self):
        report = balance(["close_up"] * 8 + ["medium"] * 2)
        assert not report["balanced"]
        assert report["over_represented"] == ["close_up"]
        assert report["shares"]["close_up"] == pytest.approx(0.8)

    def test_an_even_spread_passes(self):
        report = balance(["close_up"] * 3 + ["medium"] * 3 + ["wide"] * 3)
        assert report["balanced"]
        assert report["over_represented"] == []

    def test_the_ladder_itself_is_balanced_at_full_quota(self):
        # If the quota table could not pass its own rule the plan would be wrong
        # before a single render.
        names = [f.name for f in LADDER for _ in range(f.target)]
        report = balance(names)
        assert report["balanced"], report["shares"]

    def test_empty_input_does_not_divide_by_zero(self):
        report = balance([])
        assert report["total"] == 0
        assert report["balanced"]


class TestEntry:
    def test_serialises_both_scores_and_the_descriptor(self):
        spec = plan_dataset()[0]
        entry = DatasetEntry(
            spec=spec, path=Path("x.png"), faces=1, cos_root=0.83, cos_family=0.91
        )
        entry.verdict = classify(entry.cos_root)
        payload = entry.as_dict()
        assert payload["verdict"] == "accept"
        assert payload["cos_root"] == 0.83
        assert payload["cos_family"] == 0.91
        assert payload["descriptor"]["family"] == spec.family

    def test_max_family_share_is_the_documented_forty_percent(self):
        assert MAX_FAMILY_SHARE == pytest.approx(0.40)
