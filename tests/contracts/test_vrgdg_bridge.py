"""Contracts for the VRGDG session -> OpenMontage artifact bridge.

The artifacts produced here are validated against the real JSON schemas rather
than spot-checked, because a manifest that does not validate fails much later,
at checkpoint-write time, with a far worse error.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from lib.vrgdg_bridge import (
    SceneMap,
    VRGDGBridgeError,
    asset_type_for,
    copy_into_project,
    scene_id_for_segment,
    segment_image_path,
    segment_prompt,
    segment_video_path,
    session_summary,
    session_to_asset_manifest,
    session_to_edit_decisions,
    timeline_segments,
)
from schemas.artifacts import validate_artifact


# ---------------------------------------------------------------------------
# fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def project_dir(tmp_path: Path) -> Path:
    for sub in ("artifacts", "assets/images", "assets/video", "assets/audio"):
        (tmp_path / sub).mkdir(parents=True, exist_ok=True)
    return tmp_path


@pytest.fixture
def vrgdg_media(tmp_path: Path) -> dict[str, Path]:
    """Stand-in for a VRGDG project's rendered output."""
    folder = tmp_path / "VRGDG_Project_2026-08-21"
    (folder / "zimage_approved").mkdir(parents=True)
    (folder / "rendered_scene_videos").mkdir(parents=True)
    made = {}
    for n in (1, 2):
        img = folder / "zimage_approved" / f"image_{n:04d}.png"
        img.write_bytes(b"\x89PNG\r\n\x1a\n" + b"0" * 64)
        vid = folder / "rendered_scene_videos" / f"video_{n:04d}-audio.mp4"
        vid.write_bytes(b"\x00\x00\x00\x18ftypmp42" + b"0" * 64)
        made[f"image_{n}"] = img
        made[f"video_{n}"] = vid
    made["folder"] = folder
    return made


def _session(vrgdg_media: dict[str, Path]) -> dict:
    """A session shaped like the real thing, trimmed to the fields we read."""
    return {
        "project_folder": str(vrgdg_media["folder"]),
        "audio_path": str(vrgdg_media["folder"] / "project_audio" / "project_audio.wav"),
        "audio_duration": 12.0,
        "detected_tempo_bpm": 122.0,
        "video_engine": "ltx",
        "image_model_mode": "zimage",
        "segments": [
            {
                "id": "seg_bbb",
                "track": "base",
                "start": 4.0,
                "end": 9.0,
                "label": "Recognition",
                "story_beat": "turn",
                "t2i_prompt": "a still of the heroine",
                "i2v_prompt": "she turns toward the camera",
                "image": str(vrgdg_media["image_2"]),
                "video_path": str(vrgdg_media["video_2"]),
            },
            {
                "id": "seg_aaa",
                "track": "base",
                "start": 0.0,
                "end": 4.0,
                "label": "Awakening",
                "t2i_prompt": "a clockwork heroine asleep",
                "image": str(vrgdg_media["image_1"]),
                "video_path": str(vrgdg_media["video_1"]),
            },
            {
                "id": "seg_overlay",
                "track": "overlay",
                "start": 0.0,
                "end": 2.0,
                "label": "Title card",
                "image": str(vrgdg_media["image_1"]),
            },
        ],
    }


# ---------------------------------------------------------------------------
# segments
# ---------------------------------------------------------------------------

def test_segments_come_back_in_timeline_order(vrgdg_media):
    ids = [s["id"] for s in timeline_segments(_session(vrgdg_media))]
    assert ids == ["seg_aaa", "seg_bbb"]


def test_overlay_track_is_not_part_of_the_cut(vrgdg_media):
    # Overlays are a second layer, not shots in the sequence.
    assert "seg_overlay" not in [s["id"] for s in timeline_segments(_session(vrgdg_media))]


def test_a_session_without_segments_is_rejected():
    with pytest.raises(VRGDGBridgeError, match="no segments"):
        timeline_segments({"not": "a session"})


def test_motion_prompt_wins_over_the_still_prompt():
    segment = {"t2i_prompt": "a still", "i2v_prompt": "it moves"}
    assert segment_prompt(segment) == "it moves"


def test_prompt_falls_back_when_the_motion_prompt_is_blank():
    assert segment_prompt({"t2i_prompt": "a still", "i2v_prompt": "   "}) == "a still"


def test_no_prompt_at_all_is_none():
    assert segment_prompt({"t2i_prompt": "", "i2v_prompt": ""}) is None


def test_windows_paths_in_the_session_are_parsed():
    segment = {"image": r"C:\Users\Barrul\out\zimage_approved\image_0001.png"}
    path = segment_image_path(segment)
    assert path is not None and path.name == "image_0001.png"


def test_image_falls_back_through_the_builders_own_order():
    assert segment_image_path({"image": "", "ref_image_path": r"C:\a\b.png"}).name == "b.png"
    assert segment_image_path({"image": "", "ref_image_path": ""}) is None


def test_video_path_absent_is_none():
    assert segment_video_path({"video_path": ""}) is None


@pytest.mark.parametrize(
    "name,expected",
    [("a.png", "image"), ("a.WEBP", "image"), ("a.mp4", "video"),
     ("a.mov", "video"), ("a.wav", "audio"), ("a.txt", None)],
)
def test_asset_type_is_derived_from_the_suffix(name, expected):
    assert asset_type_for(Path(name)) == expected


# ---------------------------------------------------------------------------
# identity
# ---------------------------------------------------------------------------

def test_scene_ids_survive_a_reorder_in_vrgdg():
    # The whole point of the external map: if the user drags scene 2 in front of
    # scene 1, sc1 must stay attached to the same shot rather than renumbering.
    scene_map = SceneMap()
    scene_map.bind("seg_bbb", "sc1")
    scene_map.bind("seg_aaa", "sc2")
    assert scene_id_for_segment({"id": "seg_aaa"}, 0, scene_map) == "sc2"
    assert scene_id_for_segment({"id": "seg_bbb"}, 1, scene_map) == "sc1"


def test_unknown_segment_gets_a_positional_id():
    assert scene_id_for_segment({"id": "seg_new"}, 2, SceneMap()) == "sc3"


def test_scene_map_round_trips(project_dir):
    scene_map = SceneMap()
    scene_map.bind("seg_aaa", "sc1")
    scene_map.save(project_dir, vrgdg_project_folder="C:/x")
    reloaded = SceneMap.load(project_dir)
    assert reloaded.scene_id_for("seg_aaa") == "sc1"


def test_missing_scene_map_loads_empty(project_dir):
    assert SceneMap.load(project_dir).pairs == []


def test_corrupt_scene_map_is_reported(project_dir):
    (project_dir / "artifacts" / "vrgdg_scene_map.json").write_text("{ nope", encoding="utf-8")
    with pytest.raises(VRGDGBridgeError, match="Unreadable scene map"):
        SceneMap.load(project_dir)


def test_rebinding_updates_rather_than_duplicating():
    scene_map = SceneMap()
    scene_map.bind("seg_aaa", "sc1")
    scene_map.bind("seg_aaa", "sc9")
    assert scene_map.pairs == [{"segment_id": "seg_aaa", "scene_id": "sc9"}]


# ---------------------------------------------------------------------------
# asset manifest
# ---------------------------------------------------------------------------

def test_manifest_validates_against_the_real_schema(project_dir, vrgdg_media):
    manifest, warnings = session_to_asset_manifest(
        _session(vrgdg_media), project_dir=project_dir, scene_map=SceneMap()
    )
    validate_artifact("asset_manifest", manifest)
    assert warnings == []
    assert len(manifest["assets"]) == 4  # 2 scenes x (image + video)


def test_manifest_paths_are_project_relative(project_dir, vrgdg_media):
    manifest, _ = session_to_asset_manifest(
        _session(vrgdg_media), project_dir=project_dir, scene_map=SceneMap()
    )
    for asset in manifest["assets"]:
        assert not Path(asset["path"]).is_absolute()
        assert asset["path"].startswith("assets/")
        assert (project_dir / asset["path"]).is_file()


def test_assets_are_copied_into_the_project(project_dir, vrgdg_media):
    session_to_asset_manifest(
        _session(vrgdg_media), project_dir=project_dir, scene_map=SceneMap()
    )
    assert (project_dir / "assets" / "images" / "sc1_image.png").is_file()
    assert (project_dir / "assets" / "video" / "sc2_video.mp4").is_file()


def test_a_missing_file_warns_instead_of_failing(project_dir, vrgdg_media):
    session = _session(vrgdg_media)
    session["segments"][1]["video_path"] = r"C:\gone\video_0001.mp4"
    manifest, warnings = session_to_asset_manifest(
        session, project_dir=project_dir, scene_map=SceneMap()
    )
    validate_artifact("asset_manifest", manifest)
    assert any("missing on disk" in w for w in warnings)
    assert len(manifest["assets"]) == 3


def test_copy_is_skipped_when_the_target_is_already_current(project_dir, vrgdg_media):
    source = vrgdg_media["image_1"]
    rel = copy_into_project(source, project_dir, "image", stem="sc1_image")
    target = project_dir / rel
    target.write_bytes(b"edited-in-place-later")
    copy_into_project(source, project_dir, "image", stem="sc1_image")
    assert target.read_bytes() == b"edited-in-place-later"


def test_manifest_records_the_prompt_and_duration(project_dir, vrgdg_media):
    manifest, _ = session_to_asset_manifest(
        _session(vrgdg_media), project_dir=project_dir, scene_map=SceneMap()
    )
    video = next(a for a in manifest["assets"] if a["id"] == "vid_sc2")
    assert video["prompt"] == "she turns toward the camera"
    assert video["duration_seconds"] == 5.0
    assert video["cost_usd"] == 0.0


# ---------------------------------------------------------------------------
# edit decisions
# ---------------------------------------------------------------------------

def test_edit_decisions_validate_against_the_real_schema(vrgdg_media):
    cut, warnings = session_to_edit_decisions(_session(vrgdg_media), scene_map=SceneMap())
    validate_artifact("edit_decisions", cut)
    assert warnings == []
    assert [c["id"] for c in cut["cuts"]] == ["sc1", "sc2"]


def test_cut_length_comes_from_the_timeline(vrgdg_media):
    cut, _ = session_to_edit_decisions(_session(vrgdg_media), scene_map=SceneMap())
    assert cut["cuts"][0]["out_seconds"] == 4.0
    assert cut["cuts"][1]["out_seconds"] == 5.0


def test_unrendered_scenes_are_reported_not_silently_dropped(vrgdg_media):
    session = _session(vrgdg_media)
    session["segments"][0]["video_path"] = ""
    cut, warnings = session_to_edit_decisions(session, scene_map=SceneMap())
    assert len(cut["cuts"]) == 1
    assert any("no rendered video yet" in w for w in warnings)


def test_a_zero_length_segment_is_rejected_from_the_cut(vrgdg_media):
    session = _session(vrgdg_media)
    session["segments"][1]["end"] = session["segments"][1]["start"]
    cut, warnings = session_to_edit_decisions(session, scene_map=SceneMap())
    validate_artifact("edit_decisions", cut)
    assert any("ends at or before it starts" in w for w in warnings)


def test_tempo_is_carried_into_metadata(vrgdg_media):
    cut, _ = session_to_edit_decisions(_session(vrgdg_media), scene_map=SceneMap())
    assert cut["metadata"]["detected_tempo_bpm"] == 122.0


def test_render_runtime_is_required_and_passed_through(vrgdg_media):
    cut, _ = session_to_edit_decisions(
        _session(vrgdg_media), scene_map=SceneMap(), render_runtime="remotion"
    )
    assert cut["render_runtime"] == "remotion"


# ---------------------------------------------------------------------------
# a fresh, empty project - the state the user's own project is in today
# ---------------------------------------------------------------------------

def _empty_session() -> dict:
    return {
        "project_folder": r"C:\out\VRGDG_Project_2026-08-21_23-10-05",
        "audio_path": "",
        "audio_duration": 0,
        "detected_tempo_bpm": 0,
        "video_engine": "ltx",
        "segments": [
            {"id": "seg_b8ef54f5", "track": "base", "start": 0, "end": 4,
             "label": "New scene", "t2i_prompt": "", "i2v_prompt": "",
             "image": None, "video_path": ""}
        ],
    }


def test_a_scaffolded_project_imports_without_error(project_dir):
    manifest, manifest_warnings = session_to_asset_manifest(
        _empty_session(), project_dir=project_dir, scene_map=SceneMap()
    )
    cut, cut_warnings = session_to_edit_decisions(_empty_session(), scene_map=SceneMap())
    validate_artifact("asset_manifest", manifest)
    validate_artifact("edit_decisions", cut)
    assert manifest["assets"] == []
    assert cut["cuts"] == []
    assert any("no rendered video yet" in w for w in cut_warnings)
    assert manifest_warnings == []


def test_summary_describes_what_was_found(vrgdg_media):
    summary = session_summary(_session(vrgdg_media))
    assert summary["segments"] == 2
    assert summary["with_image"] == 2
    assert summary["with_video"] == 2
    assert summary["timeline_seconds"] == 9.0
    assert summary["detected_tempo_bpm"] == 122.0


# ---------------------------------------------------------------------------
# tool wiring
# ---------------------------------------------------------------------------

def test_tool_declares_both_directions():
    from tools.video.vrgdg_project_sync import VRGDGProjectSync

    tool = VRGDGProjectSync()
    assert tool.supports["import_session"] is True
    assert tool.supports["export_scene_plan"] is True
    assert tool.capability == "project_sync"
    # Only the OpenMontage side is always required; project_folder is needed for
    # import but optional on export, where a project is created instead.
    assert set(tool.input_schema["required"]) == {"project_dir"}


def test_import_still_demands_the_vrgdg_project(tmp_path):
    from tools.video import vrgdg_project_sync as mod

    tool = mod.VRGDGProjectSync()
    tool._client = _FakeClient({})
    result = tool.execute({"operation": "import", "project_dir": str(tmp_path)})
    assert result.success is False
    assert "project_folder" in result.error


def test_tool_refuses_a_project_dir_that_does_not_exist(tmp_path):
    from tools.video.vrgdg_project_sync import VRGDGProjectSync

    result = VRGDGProjectSync().execute(
        {"project_folder": "C:/x", "project_dir": str(tmp_path / "nope")}
    )
    assert result.success is False
    assert "init_project" in result.error


def test_tool_writes_the_three_artifacts(project_dir, vrgdg_media, monkeypatch):
    from tools.video import vrgdg_project_sync as mod

    tool = mod.VRGDGProjectSync()
    monkeypatch.setattr(tool._client, "is_available", lambda: True)
    monkeypatch.setattr(
        tool._client, "load_session", lambda folder: {"session": _session(vrgdg_media)}
    )
    result = tool.execute(
        {"project_folder": str(vrgdg_media["folder"]), "project_dir": str(project_dir)}
    )
    assert result.success is True, result.error
    names = {Path(p).name for p in result.artifacts}
    assert names == {"asset_manifest.json", "edit_decisions.json", "vrgdg_scene_map.json"}
    written = json.loads((project_dir / "artifacts" / "asset_manifest.json").read_text())
    validate_artifact("asset_manifest", written)


def test_tool_reports_a_session_that_is_not_there(project_dir, monkeypatch):
    from tools.video import vrgdg_project_sync as mod

    tool = mod.VRGDGProjectSync()
    monkeypatch.setattr(tool._client, "is_available", lambda: True)
    monkeypatch.setattr(tool._client, "load_session", lambda folder: {"ok": True})
    result = tool.execute({"project_folder": "C:/x", "project_dir": str(project_dir)})
    assert result.success is False
    assert "vrgdg_builder_session.json" in result.error


# ---------------------------------------------------------------------------
# export: scene_plan -> session
# ---------------------------------------------------------------------------

from lib.vrgdg_bridge import (  # noqa: E402
    apply_scene_plan_to_session,
    approved_images_by_scene,
    scene_plan_duration,
    scene_plan_to_segments,
    scene_plan_to_srt,
    stable_segment_id,
)


def _scene_plan() -> dict:
    return {
        "version": "1.0",
        "scenes": [
            {
                "id": "sc1",
                "type": "establishing",
                "description": "A clockwork heroine asleep beneath a brass orrery",
                "start_seconds": 0.0,
                "end_seconds": 4.0,
                "narrative_role": "setup",
                "movement": "slow push in",
                "texture_keywords": ["brass", "dust motes"],
                "shot_language": {
                    "shot_size": "wide",
                    "camera_movement": "dolly_in",
                    "lighting_key": "low_key",
                    "lens_mm": 35,
                },
            },
            {
                "id": "sc2",
                "type": "reaction",
                "description": "She opens her eyes and the constellations turn",
                "start_seconds": 4.0,
                "end_seconds": 9.0,
                "narrative_role": "turn",
                "transition_out": "cross_dissolve",
                "shot_language": {"shot_size": "close_up", "camera_movement": "static"},
            },
        ],
    }


def _scaffold_session() -> dict:
    """What VRGDG's new_project + load_session hands back: one blank scene."""
    return {
        "project_folder": r"C:\out\VRGDG_Project_new",
        "video_engine": "ltx",
        "gemma_context_limit": 8000,
        "some_future_key_we_do_not_know_about": {"keep": "me"},
        "segments": [
            {
                "id": "seg_scaffold",
                "track": "base",
                "start": 0,
                "end": 4,
                "label": "New scene",
                "t2i_prompt": "",
                "i2v_prompt": "",
                "notes": "",
                "story_beat": "",
                "image": None,
                "video_path": "",
                "a_field_only_this_vrgdg_release_has": 42,
                "minimax_h3_mode": "text_to_video",
            }
        ],
    }


def test_segment_ids_are_stable_across_exports():
    # Re-exporting the same plan must not renumber segments, or the scene map
    # and every artifact pointing at a shot goes stale.
    assert stable_segment_id("sc1") == stable_segment_id("sc1")
    assert stable_segment_id("sc1") != stable_segment_id("sc2")


def test_segment_id_looks_like_a_vrgdg_id():
    value = stable_segment_id("sc1")
    assert value.startswith("seg_")
    assert [len(p) for p in value[4:].split("-")] == [8, 4, 4, 4, 12]


def test_export_clones_the_scaffold_so_unknown_fields_survive():
    # The whole reason a template is used: this release has fields we do not
    # model, and inventing a segment would drop them.
    scene_map = SceneMap()
    segments, _ = scene_plan_to_segments(
        _scene_plan(), _scaffold_session()["segments"][0], scene_map=scene_map
    )
    assert all(s["a_field_only_this_vrgdg_release_has"] == 42 for s in segments)
    assert all(s["minimax_h3_mode"] == "text_to_video" for s in segments)


def test_export_maps_the_fields_we_do_model():
    scene_map = SceneMap()
    segments, warnings = scene_plan_to_segments(
        _scene_plan(), _scaffold_session()["segments"][0], scene_map=scene_map
    )
    assert warnings == []
    first = segments[0]
    assert first["start"] == 0.0 and first["end"] == 4.0
    assert first["story_beat"] == "setup"
    assert "clockwork heroine asleep" in first["notes"]
    assert "wide shot" in first["t2i_prompt"]
    assert "dolly in" in first["t2i_prompt"] or "dolly" in first["t2i_prompt"]
    assert "brass" in first["t2i_prompt"]
    assert first["source"] == "openmontage"
    assert first["track"] == "base"


def test_export_authors_the_video_prompt_and_keeps_the_notes():
    # DECISIONS #33 (revising #9): OpenMontage writes the video prompt, so
    # Video Prep opens filled in. The notes remain the brief it was written
    # from, and still carry the editorial intent (transitions) the prompt
    # deliberately leaves out.
    segments, _ = scene_plan_to_segments(
        _scene_plan(), _scaffold_session()["segments"][0], scene_map=SceneMap()
    )
    assert "slow push in" in segments[0]["i2v_prompt"]
    assert segments[0]["i2v_prompt_origin"] == "manual"
    assert "push in" in segments[0]["i2v_notes"]
    assert "cross dissolve" in segments[1]["i2v_notes"]
    assert "cross dissolve" not in segments[1]["i2v_prompt"]


def test_the_authored_movement_text_wins_over_the_enum_phrase():
    # "the camera orbits a full 360 degrees... she does not turn" IS the shot;
    # a generic "orbital camera circling subject" would only dilute it.
    from lib.shot_prompt_builder import build_motion_prompt

    scene = {
        "description": "she stands in the workshop",
        "movement": "the camera orbits a full 360 degrees around her",
        "shot_language": {"camera_movement": "orbital", "lighting_key": "rim_lit"},
    }
    prompt = build_motion_prompt(scene)
    assert "orbits a full 360 degrees" in prompt
    assert "circling subject" not in prompt
    assert "rim lighting" in prompt


def test_a_static_shot_still_gets_a_motion_prompt():
    from lib.shot_prompt_builder import build_motion_prompt

    prompt = build_motion_prompt(
        {"description": "a clock on the wall", "shot_language": {"camera_movement": "static"}}
    )
    assert "static camera" in prompt
    assert "subtle natural motion" in prompt


def test_export_binds_the_scene_map():
    scene_map = SceneMap()
    scene_plan_to_segments(
        _scene_plan(), _scaffold_session()["segments"][0], scene_map=scene_map
    )
    assert scene_map.scene_id_for(stable_segment_id("sc1")) == "sc1"


def test_export_warns_about_a_gap_in_the_timeline():
    plan = _scene_plan()
    plan["scenes"][1]["start_seconds"] = 6.0
    _, warnings = scene_plan_to_segments(
        plan, _scaffold_session()["segments"][0], scene_map=SceneMap()
    )
    assert any("gap" in w for w in warnings)


def test_export_warns_about_an_overlap():
    plan = _scene_plan()
    plan["scenes"][1]["start_seconds"] = 2.0
    _, warnings = scene_plan_to_segments(
        plan, _scaffold_session()["segments"][0], scene_map=SceneMap()
    )
    assert any("overlaps" in w for w in warnings)


def test_export_warns_but_still_exports_a_zero_length_scene():
    plan = _scene_plan()
    plan["scenes"][0]["end_seconds"] = 0.0
    segments, warnings = scene_plan_to_segments(
        plan, _scaffold_session()["segments"][0], scene_map=SceneMap()
    )
    assert len(segments) == 2
    assert any("ends at or before it starts" in w for w in warnings)


def test_export_rejects_an_empty_plan():
    with pytest.raises(VRGDGBridgeError, match="no scenes"):
        scene_plan_to_segments(
            {"version": "1.0", "scenes": []},
            _scaffold_session()["segments"][0],
            scene_map=SceneMap(),
        )


def test_apply_leaves_everything_outside_segments_untouched():
    session, _ = apply_scene_plan_to_session(
        _scaffold_session(), _scene_plan(), scene_map=SceneMap()
    )
    assert session["some_future_key_we_do_not_know_about"] == {"keep": "me"}
    assert session["gemma_context_limit"] == 8000
    assert len(session["segments"]) == 2


def test_apply_does_not_mutate_the_session_it_was_given():
    original = _scaffold_session()
    apply_scene_plan_to_session(original, _scene_plan(), scene_map=SceneMap())
    assert len(original["segments"]) == 1


def test_apply_needs_a_scaffolded_session_to_template_from():
    with pytest.raises(VRGDGBridgeError, match="new_project"):
        apply_scene_plan_to_session(
            {"segments": []}, _scene_plan(), scene_map=SceneMap()
        )


def test_style_context_reaches_the_prompt():
    segments, _ = scene_plan_to_segments(
        _scene_plan(),
        _scaffold_session()["segments"][0],
        scene_map=SceneMap(),
        style_context={"visual_language": {"aesthetic": "hand-painted matte"}},
    )
    assert "hand-painted matte" in segments[0]["t2i_prompt"]


# ---------------------------------------------------------------------------
# SRT and duration
# ---------------------------------------------------------------------------

def test_srt_has_the_expected_shape():
    srt = scene_plan_to_srt(_scene_plan())
    lines = srt.splitlines()
    assert lines[0] == "1"
    assert lines[1] == "00:00:00,000 --> 00:00:04,000"
    assert lines[2].startswith("sc1")
    assert "00:00:04,000 --> 00:00:09,000" in srt


def test_srt_skips_zero_length_scenes():
    plan = _scene_plan()
    plan["scenes"][0]["end_seconds"] = 0.0
    srt = scene_plan_to_srt(plan)
    assert srt.splitlines()[0] == "1"
    assert "sc2" in srt and "sc1 setup" not in srt


def test_timeline_duration_is_the_last_end():
    assert scene_plan_duration(_scene_plan()) == 9.0
    assert scene_plan_duration({"scenes": []}) == 0.0


def test_approved_images_are_indexed_by_scene():
    manifest = {
        "assets": [
            {"type": "image", "scene_id": "sc1", "path": "assets/images/sc1_image.png"},
            {"type": "video", "scene_id": "sc1", "path": "assets/video/sc1_video.mp4"},
            {"type": "image", "scene_id": "sc1", "path": "assets/images/later.png"},
        ]
    }
    # First image per scene wins; videos are not stills.
    assert approved_images_by_scene(manifest) == {"sc1": "assets/images/sc1_image.png"}


# ---------------------------------------------------------------------------
# tool: export
# ---------------------------------------------------------------------------

class _FakeClient:
    def __init__(self, session):
        self.session = session
        self.saved = None
        self.silent = None
        self.srt = None
        self.images = []
        self.created = None

    def is_available(self):
        return True

    def unavailable_reason(self):
        return "unavailable"

    def new_project(self, name):
        self.created = name
        return {"ok": True, "project_folder": r"C:\out\VRGDG_Project_new"}

    def load_session(self, folder):
        return {"session": self.session}

    def save_session(self, folder, session):
        self.saved = session
        return {"ok": True}

    def create_silent_audio(self, folder, duration, **kwargs):
        self.silent = duration
        return {"audio_path": folder + r"\project_audio\silence.wav"}

    def save_project_srt(self, folder, srt_text):
        self.srt = srt_text
        return {"ok": True}

    def save_scene_image(self, folder, scene_number, source_path):
        self.images.append((scene_number, source_path))
        return {"saved_path": f"{folder}/zimage_approved/image_{scene_number:04d}.png"}


def _export_tool(session):
    from tools.video.vrgdg_project_sync import VRGDGProjectSync

    tool = VRGDGProjectSync()
    tool._client = _FakeClient(session)
    return tool


def test_export_creates_a_project_and_writes_the_timeline(project_dir):
    tool = _export_tool(_scaffold_session())
    result = tool.execute(
        {
            "operation": "export",
            "project_dir": str(project_dir),
            "scene_plan": _scene_plan(),
        }
    )
    assert result.success is True, result.error
    assert result.data["created_project"] is True
    assert result.data["scenes_exported"] == 2
    assert result.data["timeline_seconds"] == 9.0
    assert len(tool._client.saved["segments"]) == 2


def test_export_scaffolds_audio_and_srt(project_dir):
    tool = _export_tool(_scaffold_session())
    tool.execute(
        {"operation": "export", "project_dir": str(project_dir), "scene_plan": _scene_plan()}
    )
    # VRGDG's video routes require both even for a film with no dialogue.
    assert tool._client.silent == 9.0
    assert "00:00:04,000 --> 00:00:09,000" in tool._client.srt


def test_export_refuses_to_discard_existing_work(project_dir):
    occupied = _scaffold_session()
    occupied["segments"][0]["t2i_prompt"] = "hours of hand-written prompt"
    tool = _export_tool(occupied)
    result = tool.execute(
        {
            "operation": "export",
            "project_dir": str(project_dir),
            "project_folder": r"C:\out\VRGDG_Project_existing",
            "scene_plan": _scene_plan(),
        }
    )
    assert result.success is False
    assert "overwrite_timeline" in result.error
    assert tool._client.saved is None


def test_export_overwrites_when_told_to(project_dir):
    occupied = _scaffold_session()
    occupied["segments"][0]["t2i_prompt"] = "hours of hand-written prompt"
    tool = _export_tool(occupied)
    result = tool.execute(
        {
            "operation": "export",
            "project_dir": str(project_dir),
            "project_folder": r"C:\out\VRGDG_Project_existing",
            "scene_plan": _scene_plan(),
            "overwrite_timeline": True,
        }
    )
    assert result.success is True, result.error
    assert tool._client.saved is not None


def test_export_pushes_approved_stills(project_dir):
    (project_dir / "assets" / "images").mkdir(parents=True, exist_ok=True)
    still = project_dir / "assets" / "images" / "sc2_image.png"
    still.write_bytes(b"\x89PNG\r\n\x1a\n")
    (project_dir / "artifacts" / "asset_manifest.json").write_text(
        json.dumps(
            {
                "version": "1.0",
                "assets": [
                    {
                        "id": "img_sc2",
                        "type": "image",
                        "path": "assets/images/sc2_image.png",
                        "source_tool": "comfyui_image",
                        "scene_id": "sc2",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    tool = _export_tool(_scaffold_session())
    result = tool.execute(
        {"operation": "export", "project_dir": str(project_dir), "scene_plan": _scene_plan()}
    )
    assert result.data["stills_pushed"] == ["sc2"]
    # sc2 is the second scene, and VRGDG numbers from 1.
    assert tool._client.images[0][0] == 2


def test_export_without_a_plan_says_where_it_looked(project_dir):
    tool = _export_tool(_scaffold_session())
    result = tool.execute({"operation": "export", "project_dir": str(project_dir)})
    assert result.success is False
    assert "scene_plan.json" in result.error


def test_unknown_operation_is_rejected(project_dir):
    tool = _export_tool(_scaffold_session())
    result = tool.execute({"operation": "sideways", "project_dir": str(project_dir)})
    assert result.success is False
    assert "import" in result.error and "export" in result.error


# ---------------------------------------------------------------------------
# the round trip - the property that makes the bridge trustworthy
# ---------------------------------------------------------------------------

def test_scene_ids_survive_an_export_then_import(project_dir, vrgdg_media):
    """Plan -> VRGDG -> render -> back must land on the same scene ids."""
    tool = _export_tool(_scaffold_session())
    tool.execute(
        {"operation": "export", "project_dir": str(project_dir), "scene_plan": _scene_plan()}
    )
    exported = tool._client.saved

    # Stand in for the user rendering both scenes in the Builder.
    exported["segments"][0]["image"] = str(vrgdg_media["image_1"])
    exported["segments"][0]["video_path"] = str(vrgdg_media["video_1"])
    exported["segments"][1]["image"] = str(vrgdg_media["image_2"])
    exported["segments"][1]["video_path"] = str(vrgdg_media["video_2"])

    tool._client.session = exported
    result = tool.execute(
        {
            "operation": "import",
            "project_dir": str(project_dir),
            "project_folder": r"C:\out\VRGDG_Project_new",
        }
    )
    assert result.success is True, result.error
    validate_artifact("asset_manifest", result.data["asset_manifest"])
    validate_artifact("edit_decisions", result.data["edit_decisions"])
    assert [c["id"] for c in result.data["edit_decisions"]["cuts"]] == ["sc1", "sc2"]
    assert {a["scene_id"] for a in result.data["asset_manifest"]["assets"]} == {"sc1", "sc2"}


# ---------------------------------------------------------------------------
# casting: the screen test's verdict carried into the Builder
# ---------------------------------------------------------------------------

def _cast_session() -> dict:
    """A scaffold that also carries the global engine groups, as real ones do."""
    session = _scaffold_session()
    session["image_model_mode"] = "flux_klein"
    session["zimage_settings"] = {
        "unet_name": "zImageTurbo_turbo.safetensors",
        "clip_name": "qwen3_4b_fp8_scaled.safetensors",
        "vae_name": "ae.safetensors",
        "first_pass_width": 1280,
        "second_pass_width": 1920,
        "seed": 1,
        "seed_mode": "random",
        "use_loras": False,
        "lora_count": 0,
        "loras": [],
    }
    session["flux_klein_settings"] = {
        "unet_name": "flux-2-klein-4b-fp8.safetensors",
        "clip_name": "qwen3_4b_fp8_scaled.safetensors",
        "vae_name": "flux2-vae.safetensors",
        "width": 1024,
        "seed": 100,
    }
    return session


def _cast_plan() -> dict:
    """The fixture plan, but with scenes the cast character appears in."""
    plan = _scene_plan()
    for scene in plan["scenes"]:
        scene["type"] = "character_scene"
    return plan


def _cast() -> dict:
    return {
        "model": "darkBeast30BF16INT8_dbzit9DIMRclaw.safetensors",
        "engine": "zimage",
        "seed": 7777,
    }


def _apply_cast(session=None, plan=None, casting=None):
    from lib.vrgdg_bridge import apply_scene_plan_to_session

    return apply_scene_plan_to_session(
        session if session is not None else _cast_session(),
        plan if plan is not None else _cast_plan(),
        scene_map=SceneMap(),
        casting=casting if casting is not None else _cast(),
    )


def test_casting_writes_scene_settings_from_the_sessions_own_group():
    updated, _ = _apply_cast()
    for segment in updated["segments"]:
        block = segment["zimage_settings"]
        assert block["unet_name"] == "darkBeast30BF16INT8_dbzit9DIMRclaw.safetensors"
        assert block["seed"] == 7777
        assert block["seed_mode"] == "fixed"
        assert segment["use_scene_zimage_settings"] is True


def test_casting_overrides_only_model_seed_and_loras():
    # Encoder, VAE and resolutions stay whatever the user runs; a cast is a
    # model choice, not a graph redesign.
    updated, _ = _apply_cast()
    block = updated["segments"][0]["zimage_settings"]
    assert block["clip_name"] == "qwen3_4b_fp8_scaled.safetensors"
    assert block["vae_name"] == "ae.safetensors"
    assert block["first_pass_width"] == 1280
    # and the global group itself is untouched - only the per-scene copies change
    assert updated["zimage_settings"]["unet_name"] == "zImageTurbo_turbo.safetensors"
    assert updated["zimage_settings"]["seed_mode"] == "random"


def test_casting_flips_the_project_image_engine():
    # image_model_mode is global Builder state; per-scene settings are dormant
    # under the wrong engine, so the cast must flip it or it did nothing.
    updated, _ = _apply_cast()
    assert updated["image_model_mode"] == "zimage"


def test_casting_references_attach_per_shot_family():
    # DECISIONS #30: a close-up reference is worth 0.93 on a close shot and
    # 0.30 on a medium. A family without a reference gets none, plus a warning.
    casting = {**_cast(), "references": {"close_up": r"C:\refs\close.png"}}
    updated, warnings = _apply_cast(casting=casting)
    wide, close = updated["segments"]
    assert close["ref_image_path"] == r"C:\refs\close.png"
    assert close["use_vision_reference"] is True
    assert not wide.get("ref_image_path")
    assert any("wide" in w and "DECISIONS #30" in w for w in warnings)


def test_a_single_reference_is_used_everywhere():
    casting = {**_cast(), "reference": r"C:\refs\any.png"}
    updated, warnings = _apply_cast(casting=casting)
    assert all(
        s["ref_image_path"] == r"C:\refs\any.png" for s in updated["segments"]
    )
    assert not any("DECISIONS #30" in w for w in warnings)


def test_a_flux_cast_uses_the_subject_image_field():
    # Flux Klein's reference goes through its own subject-image plumbing, not
    # the vision-reference checkbox the other engines share.
    casting = {
        "model": "flux-2-klein-4b-fp8.safetensors",
        "engine": "flux_klein",
        "seed": 42,
        "reference": r"C:\refs\subject.png",
    }
    updated, _ = _apply_cast(casting=casting)
    segment = updated["segments"][0]
    assert segment["flux_subject_image_path"] == r"C:\refs\subject.png"
    assert not segment.get("use_vision_reference")
    assert segment["use_scene_flux_klein_settings"] is True
    assert updated["image_model_mode"] == "flux_klein"


def test_a_non_builder_engine_warns_and_leaves_the_session_alone():
    # SDXL is driven by the bundled workflow on our side; its lane is rendered
    # stills pushed across, never Builder settings.
    casting = {"model": "juggernautXL.safetensors", "engine": "sdxl"}
    updated, warnings = _apply_cast(casting=casting)
    assert updated["image_model_mode"] == "flux_klein"
    assert not any(s.get("use_scene_zimage_settings") for s in updated["segments"])
    assert any("not a Builder engine" in w for w in warnings)


def test_casting_without_the_settings_group_still_attaches_references():
    session = _cast_session()
    del session["zimage_settings"]
    casting = {**_cast(), "reference": r"C:\refs\any.png"}
    updated, warnings = _apply_cast(session=session, casting=casting)
    segment = updated["segments"][0]
    assert segment["ref_image_path"] == r"C:\refs\any.png"
    assert "zimage_settings" not in segment
    assert any("no zimage_settings group" in w for w in warnings)


def test_casting_defaults_to_scenes_the_character_is_in():
    # The fixture plan's scenes are not character scenes, so nothing matches
    # and the session says so rather than casting a text card.
    updated, warnings = _apply_cast(plan=_scene_plan())
    assert updated["image_model_mode"] == "flux_klein"
    assert any("no scene in the plan matched" in w for w in warnings)


def test_casting_scope_can_be_narrowed_to_named_scenes():
    casting = {**_cast(), "scene_ids": ["sc2"]}
    updated, _ = _apply_cast(casting=casting)
    wide, close = updated["segments"]
    assert not wide.get("use_scene_zimage_settings")
    assert close["use_scene_zimage_settings"] is True


def test_casting_loras_pass_through():
    loras = [{"name": "character.safetensors", "first_pass_strength": 0.8,
              "second_pass_strength": 0, "strength": 0.8}]
    casting = {**_cast(), "loras": loras}
    updated, _ = _apply_cast(casting=casting)
    block = updated["segments"][0]["zimage_settings"]
    assert block["use_loras"] is True
    assert block["lora_count"] == 1
    assert block["loras"] == loras


def test_a_cast_record_is_flattened_by_the_tool(project_dir):
    # The screen test's cast_record keeps the model inside its candidate
    # block; the tool accepts that shape as-is.
    record = {
        "version": "1.0",
        "character": "Identity",
        "candidate": {
            "model": "darkBeast30BF16INT8_dbzit9DIMRclaw.safetensors",
            "loras": [],
        },
        "engine": "zimage",
        "seed": 7777,
    }
    (project_dir / "artifacts" / "cast_record.json").write_text(
        json.dumps(record), encoding="utf-8"
    )
    tool = _export_tool(_cast_session())
    casting, warnings = tool._resolve_casting({}, project_dir, str(project_dir))
    assert warnings == []
    assert casting["model"] == "darkBeast30BF16INT8_dbzit9DIMRclaw.safetensors"
    assert casting["engine"] == "zimage"


def test_references_are_staged_into_the_builder_project(tmp_path):
    # The Builder project must stay self-contained - the mirror of import
    # copying assets into the OpenMontage project.
    source = tmp_path / "close.png"
    source.write_bytes(b"\x89PNG fake")
    project = tmp_path / "vrgdg_project"
    project.mkdir()
    casting = {"references": {"close_up": str(source), "wide": str(tmp_path / "missing.png")}}
    warnings: list[str] = []
    from tools.video.vrgdg_project_sync import VRGDGProjectSync

    VRGDGProjectSync._stage_references(casting, str(project), warnings)
    staged = Path(casting["references"]["close_up"])
    assert staged.is_file() and staged.parent == project / "references"
    assert "wide" not in casting["references"]
    assert any("does not exist" in w for w in warnings)


def test_a_pushed_still_is_recorded_in_the_session(project_dir, tmp_path):
    # save_scene_image only copies the file; recording where it landed is the
    # caller's job - the Builder UI sets approved_image_path after every call,
    # and so must the export, or the timeline shows no image.
    import json as _json

    (project_dir / "artifacts" / "scene_plan.json").write_text(
        _json.dumps(_cast_plan()), encoding="utf-8"
    )
    still = project_dir / "assets" / "images" / "sc1.png"
    still.write_bytes(b"PNG fake")
    (project_dir / "artifacts" / "asset_manifest.json").write_text(
        _json.dumps({
            "version": "1.0",
            "assets": [{
                "id": "img_sc1", "type": "image", "path": "assets/images/sc1.png",
                "source_tool": "comfyui_image", "scene_id": "sc1",
            }],
        }),
        encoding="utf-8",
    )
    vrgdg_folder = tmp_path / "vrgdg_target"
    vrgdg_folder.mkdir()
    tool = _export_tool(_cast_session())
    result = tool.execute({
        "operation": "export",
        "project_dir": str(project_dir),
        "project_folder": str(vrgdg_folder),
    })
    assert result.success, result.error
    assert result.data["stills_pushed"] == ["sc1"]
    saved = tool._client.saved
    from lib.vrgdg_bridge import stable_segment_id

    seg = next(s for s in saved["segments"] if s["id"] == stable_segment_id("sc1"))
    assert seg["image"].endswith("image_0001.png")
    assert seg["approved_image_path"] == seg["image"]
    other = next(s for s in saved["segments"] if s["id"] == stable_segment_id("sc2"))
    assert not other.get("image")


def test_export_applies_and_reports_the_cast(project_dir, tmp_path):
    (project_dir / "artifacts" / "scene_plan.json").write_text(
        json.dumps(_cast_plan()), encoding="utf-8"
    )
    vrgdg_folder = tmp_path / "vrgdg_target"
    vrgdg_folder.mkdir()
    tool = _export_tool(_cast_session())
    result = tool.execute(
        {
            "operation": "export",
            "project_dir": str(project_dir),
            "project_folder": str(vrgdg_folder),
            "casting": _cast(),
        }
    )
    assert result.success, result.error
    assert result.data["casting_applied"]["model"].startswith("darkBeast30")
    assert result.data["casting_applied"]["engine"] == "zimage"
    saved = tool._client.saved
    assert saved["image_model_mode"] == "zimage"
    assert all(s["use_scene_zimage_settings"] for s in saved["segments"])
    assert all(s["zimage_settings"]["seed"] == 7777 for s in saved["segments"])
