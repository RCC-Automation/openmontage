"""Contracts for the render clock - budgeting local generation in GPU-minutes."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from lib.render_clock import (
    BASELINE_SAMPLES,
    PlanItem,
    RenderBudget,
    RenderTimings,
    check_budget,
    estimate_plan,
    route_key,
)


def test_route_key_separates_the_same_model_through_different_graphs():
    assert route_key("comfyui_image", "vrgdg", "zimage") != route_key(
        "comfyui_image", "custom", "zimage"
    )


def test_a_fresh_install_can_already_estimate():
    # The seeded baseline is real measurement from this workstation; an empty
    # clock that refuses to estimate would be useless on day one.
    timings = RenderTimings.load(Path("/nonexistent/render_timings.json"))
    estimate = timings.estimate(route_key("comfyui_image", "vrgdg", "zimage"))
    assert estimate.known
    assert 1.0 < estimate.minutes < 10.0


def test_a_route_never_run_here_stays_unknown():
    # Inventing a plausible number defeats the purpose of costing a plan.
    estimate = RenderTimings().estimate("comfyui_video:vrgdg:never_run")
    assert not estimate.known
    assert "no estimate" in estimate.describe()


def test_measurements_accumulate_and_move_the_estimate():
    timings = RenderTimings()
    for seconds in (100, 100, 100, 100, 100):
        timings.record("t:s:v", seconds)
    assert timings.estimate("t:s:v").seconds == pytest.approx(100)
    assert timings.estimate("t:s:v").confident


def test_confidence_requires_several_samples():
    timings = RenderTimings()
    timings.record("t:s:v", 60)
    estimate = timings.estimate("t:s:v")
    assert estimate.known and not estimate.confident
    assert "low confidence" in estimate.describe()


def test_nonsense_durations_are_rejected():
    timings = RenderTimings()
    assert timings.record("t:s:v", 0) is False
    assert timings.record("t:s:v", -5) is False
    assert timings.record("t:s:v", float("inf")) is False


def test_the_same_event_is_never_counted_twice():
    timings = RenderTimings()
    assert timings.record("t:s:v", 10, event_id="e1") is True
    assert timings.record("t:s:v", 10, event_id="e1") is False


def test_estimate_scales_with_resolution_once_history_spans_two():
    timings = RenderTimings()
    timings.record("t:s:v", 60, pixels=1000)
    timings.record("t:s:v", 120, pixels=2000)
    estimate = timings.estimate("t:s:v", pixels=4000)
    assert estimate.scaled_by_pixels
    assert estimate.seconds == pytest.approx(240, rel=0.1)


def test_one_resolution_is_not_extrapolated_from():
    # Extrapolating from a single data point is a guess wearing a formula.
    timings = RenderTimings()
    timings.record("t:s:v", 60, pixels=1000)
    timings.record("t:s:v", 62, pixels=1000)
    assert not timings.estimate("t:s:v", pixels=8000).scaled_by_pixels


def test_video_estimates_scale_with_frame_count():
    timings = RenderTimings()
    timings.record("t:s:v", 100, frames=81)
    assert timings.estimate("t:s:v", frames=162).seconds == pytest.approx(200, rel=0.05)


def test_timings_round_trip_through_disk(tmp_path):
    path = tmp_path / "render_timings.json"
    timings = RenderTimings()
    timings.record("t:s:v", 42)
    timings.save(path)
    assert RenderTimings.load(path).estimate("t:s:v").seconds == pytest.approx(42)


def test_a_corrupt_timings_file_never_blocks_a_render(tmp_path):
    path = tmp_path / "render_timings.json"
    path.write_text("{ not json", encoding="utf-8")
    assert RenderTimings.load(path).estimate(
        route_key("comfyui_image", "vrgdg", "zimage")
    ).known


def test_learning_from_an_event_stream(tmp_path):
    (tmp_path / "events.jsonl").write_text(
        "\n".join(
            [
                json.dumps({"ts": "t1", "tool": "comfyui_image", "event": "start"}),
                json.dumps({"ts": "t1", "tool": "comfyui_image", "event": "finish",
                            "success": True, "duration_s": 57.5, "output_path": "a.png"}),
                json.dumps({"ts": "t2", "tool": "comfyui_video", "event": "finish",
                            "success": False, "duration_s": 3.0, "output_path": "b.mp4"}),
                "not json at all",
            ]
        ),
        encoding="utf-8",
    )
    timings = RenderTimings()
    assert timings.learn_from_events(tmp_path) == 1          # failures are not measurements
    assert timings.learn_from_events(tmp_path) == 0          # and re-reading adds nothing


# ---------------------------------------------------------------------------
# plans and budgets
# ---------------------------------------------------------------------------

def _timings() -> RenderTimings:
    t = RenderTimings()
    for _ in range(5):
        t.record("img", 150)          # 2.5 min
        t.record("vid", 3960)         # 66 min
    return t


def test_a_plan_costs_what_its_lines_cost():
    cost = estimate_plan(_timings(), [PlanItem("stills", "img", count=10)])
    assert cost.renders == 10
    assert cost.total_minutes == pytest.approx(25, rel=0.01)


def test_unknown_lines_are_reported_not_silently_zero():
    cost = estimate_plan(_timings(), [PlanItem("stills", "img", 4), PlanItem("new", "mystery", 2)])
    assert cost.has_unknowns
    verdict = check_budget(cost, 60)
    assert any("never run on this machine" in w for w in verdict.warnings)


def test_a_plan_that_fits_says_so():
    verdict = check_budget(estimate_plan(_timings(), [PlanItem("stills", "img", 10)]), 60)
    assert verdict.fits
    assert "fits" in verdict.describe()


def test_an_over_budget_plan_names_what_to_cut():
    # "do less" is useless; the decision is always *which* item.
    cost = estimate_plan(
        _timings(), [PlanItem("stills", "img", 10), PlanItem("the long clip", "vid", 3)]
    )
    verdict = check_budget(cost, 60)
    assert not verdict.fits
    assert verdict.over_by_minutes > 100
    assert any("the long clip" in s for s in verdict.suggestions)


def test_budget_spends_down_and_reports():
    budget = RenderBudget(total_minutes=10)
    budget.spend(300)
    assert budget.remaining_minutes == pytest.approx(5)
    assert not budget.exhausted
    budget.spend(600)
    assert budget.exhausted
    assert "of 10 min used" in budget.describe()


def test_budget_refuses_a_render_it_cannot_afford():
    budget = RenderBudget(total_minutes=1)
    assert not budget.affords(_timings().estimate("vid"))
    assert budget.affords(RenderTimings().estimate("img"))   # unknown route allowed through


def test_an_unknown_route_is_allowed_so_the_clock_can_learn():
    # Refusing to run the very thing that would teach the clock its cost would
    # leave it permanently blind to that route.
    budget = RenderBudget(total_minutes=5)
    assert budget.affords(RenderTimings().estimate("never:seen:before"))


def test_baseline_covers_the_routes_measured_on_this_machine():
    keys = {s["route_key"] for s in BASELINE_SAMPLES}
    assert "comfyui_image:vrgdg:zimage" in keys
    assert "comfyui_video:custom:wan21-scail2" in keys
