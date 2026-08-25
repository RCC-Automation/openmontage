"""Contract tests for the casting conversation.

The instrument was already built and calibrated. What these cover is the
translation layer: a person says something in their own words, and that has to
become a matrix without guessing. A wrong guess costs a whole round, and rounds
are the expensive thing in casting.
"""

from __future__ import annotations

import pytest

from lib.casting_loop import (
    AXES,
    Reading,
    interpret,
    next_brief,
    next_matrix,
    phone_sheet,
)

BRIEF = "a clockwork heroine with luminous pink hair and a brass filigree collar"


# ---------------------------------------------------------------------------
# reading a reaction
# ---------------------------------------------------------------------------

def test_the_canonical_reaction_is_read_as_three_instructions():
    """"more like #3, warmer, keep the collar" is a pick, an adjustment and a pin.

    Every rule runs against the whole sentence rather than stopping at the
    first match, because people say several things at once.
    """
    r = interpret("more like #3, warmer, keep the collar")
    assert r.picks == ["#3"]
    assert r.adjust == {"color_temperature": "warm"}
    assert r.pins == ["collar"]
    assert r.unknown == []


@pytest.mark.parametrize(
    "text,expected",
    [
        ("warmer", {"color_temperature": "warm"}),
        ("cooler please", {"color_temperature": "cool"}),
        ("darker", {"lighting_key": "low_key"}),
        ("brighter", {"lighting_key": "high_key"}),
        ("sharper", {"detail": "sharp"}),
        ("a bit closer", {"shot_size": "close_up"}),
    ],
)
def test_adjustments_map_to_fields(text, expected):
    assert interpret(text).adjust == expected


def test_several_picks_in_one_reaction():
    r = interpret("I like #2 and #5")
    assert r.picks == ["#2", "#5"]


def test_case_and_punctuation_do_not_matter():
    assert interpret("MORE LIKE #3, Warmer!").picks == ["#3"]
    assert interpret("MORE LIKE #3, Warmer!").adjust == {"color_temperature": "warm"}


@pytest.mark.parametrize(
    "text,axis",
    [
        ("different face", "seeds"),
        ("does it hold?", "seeds"),
        ("try the loras", "loras"),
        ("reword it", "prompt"),
        ("more models", "models"),
    ],
)
def test_widening_phrases_open_the_right_axis(text, axis):
    assert interpret(text).widen == axis
    assert axis in AXES


def test_different_face_is_not_eaten_by_a_shorter_phrase():
    """Longest-match-first, or "different face" becomes "different prompt"."""
    assert interpret("give me a different face").widen == "seeds"


@pytest.mark.parametrize("phrase", ["that's her", "thats her", "lock it", "cast her"])
def test_a_decision_is_read_as_done(phrase):
    assert interpret(phrase).done is True


def test_liking_one_is_not_deciding():
    """"I like #3" narrows. "That's her" decides. Confusing them casts by accident."""
    r = interpret("I like #3")
    assert r.picks == ["#3"]
    assert r.done is False


def test_pins_and_drops_are_read():
    r = interpret("keep the brass collar, lose the goggles")
    assert r.pins == ["brass collar"]
    assert r.drops == ["goggles"]


def test_a_phrase_it_does_not_know_is_reported_not_guessed():
    """The whole point of the unknown list.

    A wrong guess costs a round. Asking back costs a sentence.
    """
    r = interpret("make her more like the one from that film we watched")
    assert r.understood is False
    assert r.unknown == ["make her more like the one from that film we watched"]


def test_an_empty_reaction_reports_nothing_rather_than_everything():
    r = interpret("")
    assert r.understood is False
    assert r.unknown == []


def test_the_reading_serialises_for_the_loop_history():
    r = interpret("more like #3, warmer, keep the collar")
    assert r.as_dict() == {
        "picks": ["#3"],
        "pinned": ["collar"],
        "color_temperature": "warm",
    }


# ---------------------------------------------------------------------------
# building the next round
# ---------------------------------------------------------------------------

CANDIDATES = [
    {"model": "alpha.safetensors"},
    {"model": "beta.safetensors"},
    {"model": "gamma.safetensors"},
]


def test_a_pick_resolves_against_the_sheet_position_not_an_id():
    """"#3" is the number under the picture. Anything else casts the wrong model."""
    matrix, _ = next_matrix({"models": ["a", "b", "c"], "seeds": [7777]},
                            interpret("more like #3"), candidates=CANDIDATES)
    assert matrix["models"] == ["gamma.safetensors"]


def test_a_pick_out_of_range_is_ignored_rather_than_wrapping():
    matrix, _ = next_matrix({"models": ["a"], "seeds": [7777]},
                            interpret("#9"), candidates=CANDIDATES)
    assert matrix["models"] == ["a"]


def test_round_two_opens_seeds_by_default():
    """The question round one cannot answer.

    One seed shows what a model does with a prompt; three show whether it does
    the same thing twice. A model that makes one beautiful portrait and a
    different face every seed is useless for a film.
    """
    matrix, question = next_matrix({"models": ["a"], "seeds": [7777]},
                                   interpret("more like #1"), candidates=CANDIDATES)
    assert len(matrix["seeds"]) == 3
    assert "hold across seeds" in question


def test_loras_open_after_seeds_have_been_asked():
    matrix, question = next_matrix(
        {"models": ["a"], "seeds": [7777, 1234, 9090]},
        interpret("more like #1"),
        candidates=CANDIDATES,
        lora_pool=["detail.safetensors", "skin.safetensors"],
    )
    assert matrix["lora_sets"] == [[], [["detail.safetensors", 0.8]], [["skin.safetensors", 0.8]]]
    assert "LoRA" in question


def test_the_lora_round_always_includes_no_lora():
    """The thing under test is a whole stack, so the bare stack has to be in it."""
    matrix, _ = next_matrix(
        {"models": ["a"], "seeds": [7777, 1234]}, interpret("try the loras"),
        candidates=CANDIDATES, lora_pool=["x.safetensors"],
    )
    assert [] in matrix["lora_sets"]


def test_every_round_can_say_what_it_is_asking():
    """A round whose purpose cannot be said in a sentence varies too much."""
    for reaction in ("more like #1", "different face", "try the loras", "reword it"):
        _, question = next_matrix({"models": ["a"], "seeds": [7777]},
                                  interpret(reaction), candidates=CANDIDATES,
                                  lora_pool=["x"])
        assert question and question.endswith("?")


# ---------------------------------------------------------------------------
# carrying the description forward
# ---------------------------------------------------------------------------

def test_a_pinned_phrase_survives_verbatim():
    """DECISIONS #29: the description carries the identity, not the seed.

    Paraphrasing "the brass collar" into "ornate neckwear" is how a character
    stops being herself between rounds.
    """
    out = next_brief(BRIEF, interpret("keep the brass filigree collar"))
    assert "brass filigree collar" in out


def test_a_pin_already_present_is_not_duplicated():
    out = next_brief(BRIEF, interpret("keep the brass filigree collar"))
    assert out.count("brass filigree collar") == 1


def test_a_drop_removes_the_phrase():
    brief = BRIEF + ", brass goggles on her forehead"
    out = next_brief(brief, interpret("lose the goggles"))
    assert "goggles" not in out.lower()
    assert "brass filigree collar" in out


def test_an_adjustment_becomes_words_a_model_can_render():
    """"darker" is what a person says; the prompt needs what renders."""
    out = next_brief(BRIEF, interpret("darker"))
    assert "low-key" in out
    assert "darker" not in out


def test_the_brief_is_unchanged_when_nothing_was_understood():
    out = next_brief(BRIEF, interpret("hmm"))
    assert out == BRIEF


# ---------------------------------------------------------------------------
# the sheet
# ---------------------------------------------------------------------------

def test_the_sheet_is_skipped_when_no_image_exists(tmp_path):
    assert phone_sheet([("nope.png", "a", "b")], tmp_path / "s.png") is None


def test_the_sheet_is_built_and_is_portrait_friendly(tmp_path):
    pytest.importorskip("PIL")
    from PIL import Image

    picks = []
    for i in range(4):
        p = tmp_path / f"{i}.png"
        Image.new("RGB", (512, 512), (60, 40, 30)).save(p)
        picks.append((str(p), f"model_{i}", "face 0.90"))
    out = phone_sheet(picks, tmp_path / "sheet.png", title="Round 1", columns=2)
    assert out is not None and out.is_file()
    with Image.open(out) as img:
        # Two columns and four picks means it is taller than it is wide, which
        # is the shape a phone scrolls comfortably.
        assert img.height > img.width
