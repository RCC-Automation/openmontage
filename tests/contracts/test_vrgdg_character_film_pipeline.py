"""Contract tests for the vrgdg-character-film pipeline manifest.

The manifest is what Backlot draws its rail from and what the agent reads to
know the order and the gates. A manifest that names a skill nobody wrote, or
an artifact with no schema, fails much later and much worse - at checkpoint
time, mid-production, with the GPU warm.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml

from lib.pipeline_loader import load_pipeline
from schemas.artifacts import ARTIFACT_NAMES

MANIFEST = Path("pipeline_defs/vrgdg-character-film.yaml")
PIPELINE = "vrgdg-character-film"

#: The ten steps, in order. Named here rather than derived from the manifest so
#: that a reordering has to be deliberate: this list is the second opinion.
EXPECTED_STAGES = [
    "brief",
    "casting",
    "score",
    "scene_plan",
    "scene_look",
    "export",
    "render",
    "import",
    "dailies",
    "post",
]


@pytest.fixture(scope="module")
def manifest() -> dict:
    return yaml.safe_load(MANIFEST.read_text(encoding="utf-8"))


def test_the_manifest_loads_through_the_loader(manifest):
    loaded = load_pipeline(PIPELINE)
    assert loaded["name"] == PIPELINE
    assert len(loaded["stages"]) == len(EXPECTED_STAGES)


def test_the_ten_steps_are_in_the_order_the_docs_promise(manifest):
    assert [s["name"] for s in manifest["stages"]] == EXPECTED_STAGES


def test_the_score_comes_before_the_scene_plan(manifest):
    """The whole reason the step was added.

    Scene boundaries land on measured beats only if the track exists before the
    shots are planned. Reversing these two silently removes the benefit while
    leaving every artifact still validating.
    """
    names = [s["name"] for s in manifest["stages"]]
    assert names.index("score") < names.index("scene_plan")


def test_the_scene_plan_cannot_run_without_a_beat_map(manifest):
    stage = next(s for s in manifest["stages"] if s["name"] == "scene_plan")
    assert "beat_map" in stage["required_artifacts_in"]


def test_every_stage_but_import_is_gated(manifest):
    """Nine of ten stop for a human. Import is a read, so it does not."""
    gated = {s["name"] for s in manifest["stages"] if s.get("human_approval_default")}
    assert gated == set(EXPECTED_STAGES) - {"import"}


def test_every_declared_skill_exists_on_disk(manifest):
    missing = [
        name
        for name in manifest.get("required_skills", [])
        if not (Path("skills") / f"{name}.md").is_file()
    ]
    assert missing == [], f"manifest names skills nobody wrote: {missing}"


def test_every_stage_skill_exists_on_disk(manifest):
    missing = [
        f"{s['name']} -> {s['skill']}"
        for s in manifest["stages"]
        if not (Path("skills") / f"{s['skill']}.md").is_file()
    ]
    assert missing == [], f"stages point at skills nobody wrote: {missing}"


def test_every_produced_artifact_has_a_registered_schema(manifest):
    """An artifact absent from ARTIFACT_NAMES is written to a checkpoint unchecked.

    `lib.checkpoint._validate_artifacts_for_stage` skips unknown names
    *silently*. That is how cast_record went through a whole production with no
    schema and nobody noticed - so the manifest is the place to catch it.
    """
    unregistered = sorted(
        {
            artifact
            for stage in manifest["stages"]
            for artifact in stage.get("produces", []) or []
            if artifact not in ARTIFACT_NAMES
        }
    )
    assert unregistered == [], (
        f"stages produce artifacts with no registered schema, so nothing "
        f"validates them: {unregistered}"
    )


def test_every_required_input_is_produced_by_an_earlier_stage(manifest):
    """No stage may need something the film has not made yet."""
    produced: set[str] = set()
    problems: list[str] = []
    for stage in manifest["stages"]:
        for needed in stage.get("required_artifacts_in", []) or []:
            if needed not in produced:
                problems.append(f"{stage['name']} needs {needed}, produced by nothing before it")
        produced.update(stage.get("produces", []) or [])
    assert problems == [], problems


def test_each_stage_states_how_it_will_be_judged(manifest):
    """review_focus and success_criteria are what a self-review reads."""
    thin = [
        s["name"]
        for s in manifest["stages"]
        if not s.get("review_focus") or not s.get("success_criteria")
    ]
    assert thin == [], f"stages with nothing to review against: {thin}"


def test_the_skills_carry_the_contract_shape():
    """Every production skill answers the same six questions.

    The shape is what makes them interchangeable and a pipeline only an
    ordering. A skill missing a section is one a reader has to guess at.
    """
    required = ("## triggers", "## needs", "## produces", "## does", "## presents")
    problems = []
    for path in sorted(Path("skills/production").glob("*.md")):
        text = path.read_text(encoding="utf-8")
        for heading in required:
            if heading not in text:
                problems.append(f"{path.name} has no {heading!r}")
    assert problems == [], problems


def test_every_loop_skill_says_it_is_a_loop():
    """The four loops are where quality comes from; a reader must spot them."""
    loops = {"casting.md", "score.md", "scene-look.md", "dailies.md"}
    for name in sorted(loops):
        text = (Path("skills/production") / name).read_text(encoding="utf-8")
        assert "*(loop)*" in text.splitlines()[0], f"{name} does not announce itself as a loop"
