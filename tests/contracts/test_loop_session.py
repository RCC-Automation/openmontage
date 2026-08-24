"""Contract tests for the shared loop state.

Three of the film's ten steps are loops that end when a human says so. What
they share is not the subject but the *history* - the record of what was tried,
what was said about it, and what that turned into. These tests are mostly about
that record surviving.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from lib.loop_session import (
    LOOP_KINDS,
    LoopSession,
    LoopSessionError,
    Round,
)


@pytest.fixture
def project(tmp_path: Path) -> Path:
    return tmp_path


# ---------------------------------------------------------------------------
# lifecycle
# ---------------------------------------------------------------------------

def test_a_loop_that_has_never_run_loads_empty(project):
    s = LoopSession.load(project, "casting")
    assert s.rounds == []
    assert s.decided is False


def test_an_unknown_loop_kind_is_refused(project):
    with pytest.raises(LoopSessionError, match="Unknown loop kind"):
        LoopSession.load(project, "colour_grading")


@pytest.mark.parametrize("kind", LOOP_KINDS)
def test_every_loop_kind_gets_its_own_folder(project, kind):
    s = LoopSession.load(project, kind)
    s.subject = "x"
    path = s.save()
    assert path == project / kind / "session.json"


def test_two_loops_coexist_without_knowing_about_each_other(project):
    cast = LoopSession.load(project, "casting")
    cast.subject = "clockwork heroine"
    cast.start_round({"models": ["a", "b"]})
    cast.save()

    look = LoopSession.load(project, "scene_look")
    look.subject = "sc1"
    look.start_round({"directions": ["dawn", "night"]})
    look.save()

    assert LoopSession.load(project, "casting").subject == "clockwork heroine"
    assert LoopSession.load(project, "scene_look").subject == "sc1"
    assert len(LoopSession.load(project, "casting").rounds) == 1


def test_a_corrupt_session_is_reported_not_swallowed(project):
    path = LoopSession.path_for(project, "score")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("{not json", encoding="utf-8")
    with pytest.raises(LoopSessionError, match="Unreadable"):
        LoopSession.load(project, "score")


# ---------------------------------------------------------------------------
# rounds and reactions
# ---------------------------------------------------------------------------

def test_rounds_are_numbered_from_one_and_never_reused(project):
    s = LoopSession.load(project, "casting")
    assert s.start_round().number == 1
    assert s.start_round().number == 2
    assert s.start_round().number == 3


def test_the_reaction_is_kept_verbatim_alongside_what_was_made_of_it(project):
    """Both halves, or the history cannot show a misreading.

    Storing only the parameters loses what the human reached for; storing only
    their words loses what the skill did about it. The pair is the audit trail.
    """
    s = LoopSession.load(project, "casting")
    s.start_round()
    s.record_reaction(
        "more like #3, warmer, keep the collar",
        applied={"seed_from": "cand_3", "color_temperature": "warm", "pinned": "brass collar"},
        favourites=["cand_3"],
    )
    rnd = s.current
    assert rnd.reaction == "more like #3, warmer, keep the collar"
    assert rnd.applied["color_temperature"] == "warm"
    assert rnd.favourites == ["cand_3"]


def test_reacting_before_a_round_exists_is_an_error(project):
    s = LoopSession.load(project, "score")
    with pytest.raises(LoopSessionError, match="No round to react to"):
        s.record_reaction("slower")


def test_favourites_accumulate_newest_first_without_duplicates(project):
    s = LoopSession.load(project, "casting")
    s.start_round(); s.record_reaction("a", favourites=["c1", "c2"])
    s.start_round(); s.record_reaction("b", favourites=["c2", "c5"])
    assert s.favourites_so_far() == ["c2", "c5", "c1"]


def test_cost_and_time_accumulate_across_rounds(project):
    s = LoopSession.load(project, "casting")
    r1 = s.start_round(); r1.cost_usd = 0.0; r1.seconds = 210.5
    r2 = s.start_round(); r2.cost_usd = 0.0; r2.seconds = 95.25
    assert s.total_seconds() == 305.8
    assert s.total_cost_usd() == 0.0


# ---------------------------------------------------------------------------
# the verdict - the machine narrows, the human picks
# ---------------------------------------------------------------------------

def test_a_decision_records_who_made_it(project):
    s = LoopSession.load(project, "casting")
    s.start_round()
    verdict = s.decide({"model": "darkBeast30.safetensors", "seed": 7777})
    assert verdict["chosen_by"] == "human"
    assert verdict["after_rounds"] == 1
    assert s.decided is True


def test_an_agent_may_only_draft_a_verdict_never_forge_one(project):
    """DECISIONS #15: a ranking is input to a decision, not the decision.

    Both values are allowed so an agent can propose, but the field exists so a
    later reader can tell the difference. Anything else is refused rather than
    coerced, because a silently-defaulted `chosen_by` is exactly how a ranking
    would become a decision.
    """
    s = LoopSession.load(project, "casting")
    s.start_round()
    s.decide({"model": "x"}, chosen_by="agent")
    assert s.verdict["chosen_by"] == "agent"
    with pytest.raises(LoopSessionError, match="chosen_by"):
        s.decide({"model": "x"}, chosen_by="the vibes")


def test_a_decided_loop_refuses_a_new_round_until_reopened(project):
    s = LoopSession.load(project, "score")
    s.start_round()
    s.decide({"track": "take_2.mp3"})
    with pytest.raises(LoopSessionError, match="already decided"):
        s.start_round()
    s.reopen("the chorus is too busy under dialogue")
    assert s.start_round().number == 2


def test_reopening_keeps_the_reversed_decision_visible(project):
    """A history that loses a reversal reads as if the loop went straight there."""
    s = LoopSession.load(project, "score")
    s.start_round()
    s.decide({"track": "take_1.mp3"}, notes="best hook")
    s.reopen("too busy under dialogue")
    assert s.decided is False
    assert "verdict reopened" in (s.current.notes or "")
    assert "take_1.mp3" in (s.current.notes or "")
    assert "too busy under dialogue" in (s.current.notes or "")


def test_reopening_a_loop_that_was_never_decided_does_nothing(project):
    s = LoopSession.load(project, "casting")
    s.start_round()
    s.reopen("nothing to undo")
    assert s.decided is False
    assert s.current.notes is None


# ---------------------------------------------------------------------------
# persistence - the part that makes the history worth keeping
# ---------------------------------------------------------------------------

def test_a_loop_survives_being_closed_and_reopened_cold(project):
    s = LoopSession.load(project, "casting")
    s.subject = "clockwork heroine"
    s.brief = "pink hair, brass filigree collar"
    r = s.start_round({"models": ["a", "b", "c"]})
    r.candidates = [{"id": "c1"}, {"id": "c2"}]
    r.contact_sheet = "casting/round_1/sheet.png"
    r.seconds = 212.0
    s.record_reaction("more like #2", applied={"seed_from": "c2"}, favourites=["c2"])
    s.save()

    back = LoopSession.load(project, "casting")
    assert back.subject == "clockwork heroine"
    assert back.brief == "pink hair, brass filigree collar"
    assert len(back.rounds) == 1
    rnd = back.rounds[0]
    assert rnd.number == 1
    assert rnd.reaction == "more like #2"
    assert rnd.applied == {"seed_from": "c2"}
    assert rnd.favourites == ["c2"]
    assert rnd.contact_sheet == "casting/round_1/sheet.png"
    assert rnd.candidates == [{"id": "c1"}, {"id": "c2"}]
    assert rnd.seconds == 212.0


def test_the_verdict_survives_a_reload(project):
    s = LoopSession.load(project, "scene_look")
    s.start_round()
    s.decide({"scene": "sc1", "still": "assets/images/sc1_hero.png"}, notes="the lamp one")
    s.save()
    back = LoopSession.load(project, "scene_look")
    assert back.decided is True
    assert back.verdict["pick"]["still"] == "assets/images/sc1_hero.png"
    assert back.verdict["notes"] == "the lamp one"


def test_the_saved_file_is_readable_json_with_a_version(project):
    s = LoopSession.load(project, "casting")
    s.start_round()
    path = s.save()
    data = json.loads(path.read_text(encoding="utf-8"))
    assert data["version"] == "1.0"
    assert data["kind"] == "casting"
    assert isinstance(data["rounds"], list)


# ---------------------------------------------------------------------------
# reading it back for a human or a board
# ---------------------------------------------------------------------------

def test_history_retells_the_loop_in_order(project):
    s = LoopSession.load(project, "casting")
    s.start_round(); s.record_reaction("warmer", applied={"color_temperature": "warm"})
    s.start_round(); s.record_reaction("that's her", favourites=["c7"])
    told = s.history()
    assert [h["round"] for h in told] == ["1", "2"]
    assert told[0]["reaction"] == "warmer"
    assert told[0]["applied"] == "color_temperature=warm"
    assert told[1]["favourites"] == "c7"


def test_summary_leaves_the_candidate_bulk_behind(project):
    """A board panel wants the shape of the loop, not every render in it."""
    s = LoopSession.load(project, "casting")
    s.subject = "heroine"
    r = s.start_round()
    r.candidates = [{"id": f"c{i}", "images": ["x"] * 9} for i in range(40)]
    r.seconds = 300.0
    s.record_reaction("more like #3", favourites=["c3"])
    summary = s.summary()
    assert summary == {
        "kind": "casting",
        "subject": "heroine",
        "rounds": 1,
        "decided": False,
        "chosen_by": None,
        "favourites": ["c3"],
        "cost_usd": 0.0,
        "seconds": 300.0,
    }
    assert "candidates" not in json.dumps(summary)
