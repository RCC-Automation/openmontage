"""Contracts for the screen test - casting a look by measured comparison."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from lib.screen_test import (
    DEFAULT_CONDITIONS,
    Candidate,
    CandidateResult,
    ScreenTestError,
    Shot,
    build_prompt,
    cast_record,
    condition_id,
    contact_sheet,
    expand_matrix,
    resolve_conditions,
    score_candidates,
    shortlist,
    slugify,
    technical_score,
    write_report,
)


# ---------------------------------------------------------------------------
# the matrix
# ---------------------------------------------------------------------------

def test_matrix_is_the_product_of_models_and_lora_combinations():
    candidates = expand_matrix(
        {"models": ["a.safetensors", "b.safetensors"],
         "lora_sets": [[], [["style.safetensors", 0.6]]]}
    )
    assert len(candidates) == 4


def test_a_lora_set_is_a_combination_not_a_single_lora():
    # The thing under test is a whole stack, so one entry can hold several LoRAs.
    candidates = expand_matrix(
        {"models": ["a.safetensors"],
         "lora_sets": [[["one.safetensors", 0.6], ["two.safetensors", 0.3]]]}
    )
    assert len(candidates) == 1
    assert len(candidates[0].loras) == 2


def test_lora_entries_accept_both_shapes():
    from_list = expand_matrix({"models": ["m"], "lora_sets": [[["a", 0.5]]]})[0]
    from_dict = expand_matrix({"models": ["m"], "lora_sets": [[{"name": "a", "strength": 0.5}]]})[0]
    assert from_list.loras == from_dict.loras == (("a", 0.5),)


def test_a_matrix_without_models_is_rejected():
    with pytest.raises(ScreenTestError, match="models"):
        expand_matrix({"lora_sets": [[]]})


def test_an_unreadable_lora_entry_is_rejected():
    with pytest.raises(ScreenTestError, match="unreadable LoRA"):
        expand_matrix({"models": ["m"], "lora_sets": [[42]]})


def test_candidate_ids_are_stable_and_filename_safe():
    a = Candidate("Z Image Turbo.safetensors", (("ZIT Radiant.safetensors", 0.6),))
    b = Candidate("Z Image Turbo.safetensors", (("ZIT Radiant.safetensors", 0.6),))
    assert a.id == b.id
    assert "/" not in a.id and " " not in a.id


def test_different_lora_strengths_are_different_candidates():
    a = Candidate("m", (("l", 0.6),))
    b = Candidate("m", (("l", 0.3),))
    assert a.id != b.id


def test_candidate_label_reads_like_a_person_wrote_it():
    c = Candidate("zImageTurbo_turbo.safetensors", (("ZIT_Radiant.safetensors", 0.6),))
    assert c.label == "zImageTurbo_turbo + ZIT_Radiant @ 0.6"


def test_default_conditions_span_shot_sizes():
    # A face that holds in close-up and falls apart in a wide is the wrong cast.
    sizes = {c["shot_size"] for c in DEFAULT_CONDITIONS}
    assert {"close_up", "wide"} <= sizes


def test_an_unknown_condition_value_is_rejected():
    with pytest.raises(ScreenTestError, match="unknown shot_size"):
        resolve_conditions({"conditions": [{"shot_size": "extreme_potato"}]})


def test_prompt_holds_the_brief_and_adds_the_condition():
    prompt = build_prompt("a clockwork heroine", {"shot_size": "close_up", "lighting": "low_key"})
    assert prompt.startswith("a clockwork heroine")
    assert "close-up" in prompt and "low-key" in prompt


def test_condition_id_is_readable():
    assert condition_id({"shot_size": "wide", "lighting": "key", "angle": "front"}) == "wide-key-front"


@pytest.mark.parametrize("raw,expected", [("Wren, the Heroine", "wren-the-heroine"), ("", "unnamed")])
def test_slugify(raw, expected):
    assert slugify(raw) == expected


# ---------------------------------------------------------------------------
# measurement
# ---------------------------------------------------------------------------

def _image(path: Path, *, noise: bool = True) -> Path:
    """A stand-in render. `noise=True` gives gentle texture over a gradient -
    what a real image looks like to a sharpness metric - not pure static, which
    is a failure mode rather than a detailed picture."""
    from PIL import Image
    import numpy as np

    path.parent.mkdir(parents=True, exist_ok=True)
    if noise:
        rng = np.random.default_rng(abs(hash(path.name)) % (2**32))
        gradient = np.linspace(0, 255, 64)[None, :, None] * np.ones((64, 1, 3))
        data = np.clip(gradient + rng.integers(-12, 12, (64, 64, 3)), 0, 255).astype(np.uint8)
    else:
        data = np.full((64, 64, 3), 128, dtype=np.uint8)
    Image.fromarray(data).save(path)
    return path


def test_a_flat_image_scores_zero_technically(tmp_path):
    assert technical_score(_image(tmp_path / "flat.png", noise=False)) == 0.0


def test_a_detailed_image_scores_above_a_flat_one(tmp_path):
    detailed = technical_score(_image(tmp_path / "textured.png"))
    flat = technical_score(_image(tmp_path / "flat.png", noise=False))
    assert detailed > flat


def test_an_unreadable_file_scores_none(tmp_path):
    broken = tmp_path / "broken.png"
    broken.write_bytes(b"not an image")
    assert technical_score(broken) is None


def test_ranking_never_invents_a_missing_metric(tmp_path):
    # CLIP may be unavailable; the ranking must reweight rather than assume.
    result = CandidateResult(
        candidate=Candidate("m"),
        shots=[Shot("c", "close_up-key-front", 1, _image(tmp_path / "a.png"), 10.0)],
    )
    ranked = score_candidates([result], prompt="a heroine")
    scored = ranked[0]
    assert 0.0 <= scored.total <= 1.0
    for axis, value in scored.scores.items():
        assert value is None or 0.0 <= value <= 1.0
    if any(v is None for v in scored.scores.values()):
        assert any("not measured" in n for n in scored.notes)


def test_a_faster_candidate_scores_higher_on_speed(tmp_path):
    fast = CandidateResult(Candidate("fast"), [Shot("f", "c", 1, _image(tmp_path / "f.png"), 10.0)])
    slow = CandidateResult(Candidate("slow"), [Shot("s", "c", 1, _image(tmp_path / "s.png"), 100.0)])
    ranked = score_candidates([fast, slow], prompt="x")
    by_label = {r.candidate.model: r.scores["speed"] for r in ranked}
    assert by_label["fast"] > by_label["slow"]


def test_shortlist_narrows_but_does_not_choose(tmp_path):
    results = [
        CandidateResult(Candidate(f"m{i}"), [Shot("c", "c", 1, _image(tmp_path / f"{i}.png"), 10.0)])
        for i in range(12)
    ]
    picked = shortlist(score_candidates(results, prompt="x"), keep=8)
    assert len(picked) == 8            # narrowed
    assert len(picked) > 1             # never reduced to a single winner


# ---------------------------------------------------------------------------
# outputs
# ---------------------------------------------------------------------------

def test_contact_sheet_is_built_from_the_ranking(tmp_path):
    results = [
        CandidateResult(Candidate(f"m{i}"), [Shot("c", "c", 1, _image(tmp_path / f"{i}.png"), 5.0)])
        for i in range(3)
    ]
    sheet = contact_sheet(results, tmp_path / "sheet.png")
    assert sheet is not None and sheet.is_file()


def test_contact_sheet_survives_a_candidate_with_no_usable_image(tmp_path):
    ok = CandidateResult(Candidate("ok"), [Shot("c", "c", 1, _image(tmp_path / "ok.png"), 5.0)])
    gone = CandidateResult(Candidate("gone"), [Shot("c", "c", 1, tmp_path / "missing.png", 5.0)])
    assert contact_sheet([ok, gone], tmp_path / "sheet.png") is not None


def test_report_records_that_a_human_decides(tmp_path):
    result = CandidateResult(Candidate("m"), [Shot("c", "c", 1, _image(tmp_path / "a.png"), 5.0)])
    path = write_report(
        tmp_path / "casting_report.json",
        character="Wren", brief="a heroine",
        ranked=score_candidates([result], prompt="a heroine"),
        conditions=DEFAULT_CONDITIONS, seeds=[1, 2, 3],
        elapsed_minutes=12.3, contact_sheet_path=None,
    )
    payload = json.loads(path.read_text(encoding="utf-8"))
    assert "does not choose" in payload["decided_by"]
    assert payload["candidates"][0]["rank"] == 1


def test_cast_record_locks_an_identity_not_a_model(tmp_path):
    result = CandidateResult(
        Candidate("zImageTurbo.safetensors", (("radiant.safetensors", 0.6),)),
        [Shot("c", "c", 24082301, _image(tmp_path / "hero.png"), 160.0)],
    )
    score_candidates([result], prompt="a heroine")
    record = cast_record(
        "Wren", "a clockwork heroine", result,
        reference_path="assets/casting/wren/hero.png", seed=24082301,
    )
    assert record["candidate"]["loras"][0]["strength"] == 0.6
    assert record["seed"] == 24082301          # the seed is part of the identity
    assert record["reference"].endswith("hero.png")
    assert record["chosen_by"] == "human"


# ---------------------------------------------------------------------------
# tool wiring
# ---------------------------------------------------------------------------

def test_tool_declares_that_it_does_not_pick_a_winner():
    from tools.graphics.screen_test import ScreenTest

    tool = ScreenTest()
    assert tool.supports["picks_a_winner"] is False
    assert tool.capability == "casting"
    assert "nothing" in tool.get_info()["decides"]


def test_tool_refuses_too_few_seeds_to_measure_stability(tmp_path):
    from tools.graphics.screen_test import ScreenTest

    result = ScreenTest().execute(
        {
            "project_dir": str(tmp_path),
            "character": "Wren",
            "brief": "a heroine",
            "matrix": {"models": ["a.safetensors"]},
            "seeds": [1],
        }
    )
    assert result.success is False
    assert "identity stability" in result.error


def test_dry_run_costs_the_plan_without_generating(tmp_path):
    from tools.graphics.screen_test import ScreenTest

    result = ScreenTest().execute(
        {
            "project_dir": str(tmp_path),
            "character": "Wren",
            "brief": "a heroine",
            "matrix": {"models": ["a.safetensors", "b.safetensors"]},
            "seeds": [1, 2, 3],
            "dry_run": True,
        }
    )
    assert result.success is True
    assert result.data["plan"]["preset"] == "shortlist"     # the default rung
    assert result.data["plan"]["candidates"] == 2
    assert result.data["plan"]["renders"] == 2 * 1 * 3      # candidates x conditions x seeds
    assert result.data["plan"]["estimated_minutes"] > 0
    assert result.data["plan"]["question"]


def test_renders_on_unmeasured_routes_are_declared_not_hidden(tmp_path):
    """A route with no history costs 0 in the estimate, which must not read as free.

    Mixing families makes this reachable: the Z-Image route has history and the
    bundled SDXL route does not, so a silent total would understate the sweep.
    """
    from tools.graphics.screen_test import ScreenTest

    result = ScreenTest().execute(
        {
            "project_dir": str(tmp_path),
            "character": "Wren",
            "brief": "a heroine",
            "matrix": {"models": ["never-seen-before.safetensors"]},
            "preset": "quick",
            "kind": "krea2",          # a real route this machine has never run
            "dry_run": True,
        }
    )
    assert result.success is True
    plan = result.data["plan"]
    assert plan["unmeasured_renders"] == plan["renders"]
    assert plan["estimate_warnings"], "unmeasured renders must be stated"
    assert "never measured" in plan["estimate_warnings"][0]


def test_a_sweep_over_budget_is_refused_before_anything_renders(tmp_path):
    from tools.graphics.screen_test import ScreenTest

    result = ScreenTest().execute(
        {
            "project_dir": str(tmp_path),
            "character": "Wren",
            "brief": "a heroine",
            "matrix": {"models": [f"m{i}.safetensors" for i in range(9)]},
            "seeds": [1, 2, 3],
            "budget_minutes": 5,
        }
    )
    assert result.success is False
    assert "GPU-minutes" in result.error
    assert result.data["suggestions"]


# ---------------------------------------------------------------------------
# presets - the three rungs of the funnel
# ---------------------------------------------------------------------------

from lib.screen_test import PRESETS, apply_preset, comparison_sheet  # noqa: E402


def test_every_preset_states_the_question_it_answers():
    for name, preset in PRESETS.items():
        assert preset["question"], name
        assert preset["conditions"] and preset["seeds"], name


def test_quick_is_one_condition_on_one_shared_seed():
    # Same prompt, same noise, only the model differs - that is the comparison.
    conditions, seeds, _, _ = apply_preset("quick", {}, None)
    assert len(conditions) == 1 and len(seeds) == 1


def test_quick_uses_the_close_up_because_it_is_the_diagnostic_frame():
    conditions, _, _, _ = apply_preset("quick", {}, None)
    assert conditions[0]["shot_size"] == "close_up"


def test_quick_renders_smaller_so_it_finishes_in_minutes():
    _, _, quick_settings, _ = apply_preset("quick", {}, None)
    _, _, full_settings, _ = apply_preset("full", {}, None)
    quick_pixels = quick_settings["second_pass_width"] * quick_settings["second_pass_height"]
    assert quick_pixels < 1920 * 1080
    assert full_settings == {}          # full accepts the graph's own resolution


def test_quick_admits_what_it_cannot_measure():
    _, _, _, preset = apply_preset("quick", {}, None)
    assert "identity_stability" in preset["cannot_measure"]
    assert "cannot measure" in preset["caveat"]


def test_shortlist_adds_seeds_so_stability_becomes_measurable():
    _, seeds, _, preset = apply_preset("shortlist", {}, None)
    assert len(seeds) >= 3
    assert preset["cannot_measure"] == []


def test_full_spans_shot_sizes():
    conditions, _, _, _ = apply_preset("full", {}, None)
    assert len({c["shot_size"] for c in conditions}) >= 2


def test_explicit_input_overrides_the_preset():
    # A preset is a starting point, not a cage.
    conditions, seeds, settings, _ = apply_preset(
        "quick",
        {"conditions": [{"shot_size": "wide"}], "settings": {"second_pass_width": 3840}},
        [1, 2, 3, 4],
    )
    assert conditions[0]["shot_size"] == "wide"
    assert seeds == [1, 2, 3, 4]
    assert settings["second_pass_width"] == 3840


def test_an_unknown_preset_lists_the_known_ones():
    with pytest.raises(ScreenTestError, match="quick"):
        apply_preset("turbo", {}, None)


def test_a_skipped_metric_is_reported_as_not_applicable(tmp_path):
    result = CandidateResult(
        Candidate("m"), [Shot("c", "close_up-key-front", 7777, _image(tmp_path / "a.png"), 40.0)]
    )
    ranked = score_candidates([result], prompt="a heroine", skip=["identity_stability"])
    assert ranked[0].scores["identity_stability"] is None
    assert any("not applicable at this preset" in n for n in ranked[0].notes)
    assert 0.0 <= ranked[0].total <= 1.0


def test_comparison_sheet_records_what_was_held_constant(tmp_path):
    results = [
        CandidateResult(Candidate(f"model_{i}.safetensors"),
                        [Shot("c", "c", 7777, _image(tmp_path / f"{i}.png"), 40.0)])
        for i in range(3)
    ]
    score_candidates(results, prompt="a heroine", skip=["identity_stability"])
    sheet = comparison_sheet(
        results, tmp_path / "cmp.png", prompt="a clockwork heroine", seed=7777
    )
    assert sheet is not None and sheet.is_file()
    from PIL import Image
    with Image.open(sheet) as img:
        assert img.width > 512 and img.height > 512      # large cells, not thumbnails


def test_comparison_sheet_handles_a_missing_render(tmp_path):
    ok = CandidateResult(Candidate("ok"), [Shot("c", "c", 1, _image(tmp_path / "ok.png"), 5.0)])
    gone = CandidateResult(Candidate("gone"), [Shot("c", "c", 1, tmp_path / "nope.png", 5.0)])
    assert comparison_sheet([ok, gone], tmp_path / "cmp.png", prompt="x", seed=1) is not None


def test_quick_preset_accepts_a_single_seed(tmp_path):
    from tools.graphics.screen_test import ScreenTest

    result = ScreenTest().execute(
        {
            "project_dir": str(tmp_path),
            "character": "Wren",
            "brief": "a heroine",
            "matrix": {"models": ["a.safetensors", "b.safetensors"]},
            "preset": "quick",
            "dry_run": True,
        }
    )
    assert result.success is True
    assert result.data["plan"]["renders"] == 2          # one per model
    assert "cannot measure" in result.data["plan"]["caveat"]


def test_other_presets_still_refuse_a_single_seed(tmp_path):
    from tools.graphics.screen_test import ScreenTest

    result = ScreenTest().execute(
        {
            "project_dir": str(tmp_path),
            "character": "Wren",
            "brief": "a heroine",
            "matrix": {"models": ["a.safetensors"]},
            "preset": "shortlist",
            "seeds": [1],
        }
    )
    assert result.success is False
    assert "preset='quick'" in result.error


def test_quick_is_dramatically_cheaper_than_full(tmp_path):
    from tools.graphics.screen_test import ScreenTest

    tool = ScreenTest()
    base = {
        "project_dir": str(tmp_path),
        "character": "Wren",
        "brief": "a heroine",
        "matrix": {"models": [f"m{i}.safetensors" for i in range(9)]},
        "dry_run": True,
    }
    quick = tool.execute({**base, "preset": "quick"}).data["plan"]
    full = tool.execute({**base, "preset": "full"}).data["plan"]
    assert quick["renders"] == 9 and full["renders"] == 81
    assert quick["estimated_minutes"] < full["estimated_minutes"] / 8


def test_sharpness_peaks_in_the_band_real_renders_occupy(tmp_path):
    # A monotonic sharpness score ranks a noise-blasted failure as the crispest
    # image in the sweep. The curve has to come back down.
    import numpy as np
    from PIL import Image

    def make(name, array):
        path = tmp_path / name
        Image.fromarray(array).save(path)
        return path

    rng = np.random.default_rng(3)
    size = (128, 128, 3)
    flat = np.full(size, 128, dtype=np.uint8)
    # A gentle gradient with mild texture stands in for a real render.
    grad = (np.linspace(0, 255, 128)[None, :, None] * np.ones((128, 1, 3))).astype(np.uint8)
    textured = np.clip(grad.astype(int) + rng.integers(-12, 12, size), 0, 255).astype(np.uint8)
    garbled = rng.integers(0, 255, size, dtype=np.uint8)

    flat_score = technical_score(make("flat.png", flat))
    real_score = technical_score(make("real.png", textured))
    garbled_score = technical_score(make("garbled.png", garbled))

    assert flat_score == 0.0
    assert garbled_score < real_score
