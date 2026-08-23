"""Translate between a VRGDG builder session and OpenMontage artifacts.

VRGDG's ``vrgdg_builder_session.json`` and OpenMontage's ``scene_plan`` describe
the same object - an ordered list of timed shots with prompts and assets - in
two vocabularies. This module maps between them.

Two rules shape everything here:

* **The session is opaque.** It carries ~95 top-level keys and ~110 per segment
  with no version field. Never construct one: load it, change the few keys you
  understand, save it back. This module only reads.
* **Identity lives outside both.** VRGDG owns ``seg_<uuid>``; OpenMontage owns
  ``scene.id``. Neither can hold the other's, so the pairing is persisted
  separately in ``artifacts/vrgdg_scene_map.json``.

Path handling matters too: VRGDG writes absolute Windows paths into its
session, while OpenMontage artifacts are strictly project-relative. Assets are
copied into the OpenMontage project so it stays self-contained if the VRGDG
project is later moved or deleted.
"""

from __future__ import annotations

import copy
import hashlib
import json
import shutil
from dataclasses import dataclass, field
from pathlib import Path, PureWindowsPath
from typing import Any, Iterable, Mapping

SCENE_MAP_FILENAME = "vrgdg_scene_map.json"
SCENE_MAP_VERSION = "1.0"

_IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".webp"}
_VIDEO_SUFFIXES = {".mp4", ".mkv", ".webm", ".mov", ".gif"}
_AUDIO_SUFFIXES = {".wav", ".mp3", ".m4a", ".flac", ".ogg"}


class VRGDGBridgeError(ValueError):
    """Raised when a session cannot be mapped onto OpenMontage artifacts."""


# ---------------------------------------------------------------------------
# identity
# ---------------------------------------------------------------------------

@dataclass
class SceneMap:
    """Pairing between OpenMontage scene ids and VRGDG segment ids.

    Held outside both systems because neither has a field for the other's id.
    Order is the timeline order at the time of the last sync.
    """

    pairs: list[dict[str, str]] = field(default_factory=list)

    @classmethod
    def load(cls, project_dir: Path) -> "SceneMap":
        path = Path(project_dir) / "artifacts" / SCENE_MAP_FILENAME
        if not path.is_file():
            return cls()
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise VRGDGBridgeError(f"Unreadable scene map {path}: {exc}") from exc
        pairs = payload.get("pairs")
        return cls(pairs=[dict(p) for p in pairs] if isinstance(pairs, list) else [])

    def save(self, project_dir: Path, *, vrgdg_project_folder: str | None = None) -> Path:
        path = Path(project_dir) / "artifacts" / SCENE_MAP_FILENAME
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "version": SCENE_MAP_VERSION,
            "vrgdg_project_folder": vrgdg_project_folder,
            "pairs": self.pairs,
        }
        path.write_text(
            json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
        )
        return path

    def scene_id_for(self, segment_id: str) -> str | None:
        for pair in self.pairs:
            if pair.get("segment_id") == segment_id:
                return pair.get("scene_id")
        return None

    def bind(self, segment_id: str, scene_id: str) -> None:
        for pair in self.pairs:
            if pair.get("segment_id") == segment_id:
                pair["scene_id"] = scene_id
                return
        self.pairs.append({"segment_id": segment_id, "scene_id": scene_id})


def scene_id_for_segment(
    segment: Mapping[str, Any], index: int, scene_map: SceneMap
) -> str:
    """Resolve a stable OpenMontage scene id for a VRGDG segment.

    An existing pairing always wins, so re-importing after the user reorders the
    timeline in VRGDG does not renumber scenes that already exist in artifacts.
    """
    segment_id = str(segment.get("id") or "")
    if segment_id:
        existing = scene_map.scene_id_for(segment_id)
        if existing:
            return existing
    return f"sc{index + 1}"


# ---------------------------------------------------------------------------
# paths
# ---------------------------------------------------------------------------

def _as_path(value: Any) -> Path | None:
    """Interpret a session path string, which is a Windows path on this host."""
    if not isinstance(value, str) or not value.strip():
        return None
    text = value.strip().strip('"')
    # PureWindowsPath parses both separators, so a session written on Windows
    # still resolves when this code runs anywhere else.
    return Path(PureWindowsPath(text).as_posix())


def asset_type_for(path: Path) -> str | None:
    suffix = path.suffix.lower()
    if suffix in _IMAGE_SUFFIXES:
        return "image"
    if suffix in _VIDEO_SUFFIXES:
        return "video"
    if suffix in _AUDIO_SUFFIXES:
        return "audio"
    return None


_ASSET_SUBDIR = {"image": "images", "video": "video", "audio": "audio"}


def copy_into_project(
    source: Path, project_dir: Path, asset_type: str, *, stem: str
) -> str:
    """Copy an asset into the OpenMontage project. Returns a relative path.

    Copied rather than referenced so the project remains valid if the VRGDG
    project is moved or deleted, and because an artifact path must be relative.
    """
    subdir = _ASSET_SUBDIR.get(asset_type, "images")
    target_dir = Path(project_dir) / "assets" / subdir
    target_dir.mkdir(parents=True, exist_ok=True)
    target = target_dir / f"{stem}{source.suffix.lower()}"
    if not target.exists() or source.stat().st_mtime > target.stat().st_mtime:
        shutil.copy2(source, target)
    return f"assets/{subdir}/{target.name}"


# ---------------------------------------------------------------------------
# segments
# ---------------------------------------------------------------------------

def timeline_segments(session: Mapping[str, Any]) -> list[dict[str, Any]]:
    """Base-track segments in timeline order.

    Overlay segments live in ``overlay_segments`` and are deliberately excluded:
    they are a second layer, not shots in the cut.
    """
    segments = session.get("segments")
    if not isinstance(segments, list):
        raise VRGDGBridgeError(
            "Session has no segments array - it is probably not a VRGDG builder session"
        )
    base = [s for s in segments if isinstance(s, Mapping) and s.get("track", "base") == "base"]
    return sorted(base, key=lambda s: (_number(s.get("start")), str(s.get("id") or "")))


def _number(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def segment_prompt(segment: Mapping[str, Any]) -> str | None:
    """The prompt that produced this shot, preferring the motion prompt."""
    for key in ("i2v_prompt", "t2i_prompt", "minimax_h3_prompt", "flux_prompt", "nb_prompt"):
        value = segment.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


def segment_image_path(segment: Mapping[str, Any]) -> Path | None:
    """The approved still for this shot.

    ``image`` is what the Builder currently shows; ``ref_image_path`` and
    ``custom_image_path`` are the fallbacks it falls back to itself.
    """
    for key in ("image", "ref_image_path", "custom_image_path"):
        candidate = _as_path(segment.get(key))
        if candidate is not None:
            return candidate
    return None


def segment_video_path(segment: Mapping[str, Any]) -> Path | None:
    return _as_path(segment.get("video_path"))


# ---------------------------------------------------------------------------
# artifacts
# ---------------------------------------------------------------------------

def session_to_asset_manifest(
    session: Mapping[str, Any],
    *,
    project_dir: Path,
    scene_map: SceneMap,
    copy_assets: bool = True,
) -> tuple[dict[str, Any], list[str]]:
    """Build an ``asset_manifest`` from a session. Returns (manifest, warnings).

    Missing files are reported rather than raising: a half-rendered project is
    the normal state mid-production, and the manifest should describe what
    exists so far.
    """
    project_dir = Path(project_dir)
    assets: list[dict[str, Any]] = []
    warnings: list[str] = []

    for index, segment in enumerate(timeline_segments(session)):
        scene_id = scene_id_for_segment(segment, index, scene_map)
        segment_id = str(segment.get("id") or "")
        if segment_id:
            scene_map.bind(segment_id, scene_id)
        prompt = segment_prompt(segment)
        duration = max(0.0, _number(segment.get("end")) - _number(segment.get("start")))

        for kind, source in (
            ("image", segment_image_path(segment)),
            ("video", segment_video_path(segment)),
        ):
            if source is None:
                continue
            if not source.is_file():
                warnings.append(
                    f"{scene_id}: {kind} referenced by the session is missing on disk "
                    f"({source})"
                )
                continue
            asset_type = asset_type_for(source) or kind
            if copy_assets:
                rel = copy_into_project(
                    source, project_dir, asset_type, stem=f"{scene_id}_{kind}"
                )
            else:
                rel = source.as_posix()
            entry: dict[str, Any] = {
                "id": f"{kind[:3]}_{scene_id}",
                "type": asset_type,
                "path": rel,
                "source_tool": "vrgdg_project_sync",
                "scene_id": scene_id,
                "cost_usd": 0.0,
                "format": source.suffix.lstrip(".").lower(),
                "provider": "local ComfyUI (VRGDG)",
                "license": "user-generated",
            }
            if prompt:
                entry["prompt"] = prompt
            if kind == "video" and duration:
                entry["duration_seconds"] = round(duration, 3)
            assets.append(entry)

    return (
        {"version": "1.0", "assets": assets, "total_cost_usd": 0.0},
        warnings,
    )


def session_to_edit_decisions(
    session: Mapping[str, Any],
    *,
    scene_map: SceneMap,
    render_runtime: str = "ffmpeg",
) -> tuple[dict[str, Any], list[str]]:
    """Build ``edit_decisions`` from the timeline. Returns (artifact, warnings).

    Cut boundaries come from the segment's own start/end, which is what VRGDG's
    timeline already snapped to the beat grid - the cut is read off the
    timeline, never recomputed here.
    """
    cuts: list[dict[str, Any]] = []
    warnings: list[str] = []

    for index, segment in enumerate(timeline_segments(session)):
        scene_id = scene_id_for_segment(segment, index, scene_map)
        video = segment_video_path(segment)
        if video is None:
            warnings.append(f"{scene_id}: no rendered video yet, omitted from the cut")
            continue
        start = _number(segment.get("start"))
        end = _number(segment.get("end"))
        if end <= start:
            warnings.append(
                f"{scene_id}: segment ends at or before it starts "
                f"({start} -> {end}), omitted from the cut"
            )
            continue
        cut: dict[str, Any] = {
            "id": scene_id,
            "source": f"assets/video/{scene_id}_video{video.suffix.lower()}",
            "in_seconds": 0.0,
            "out_seconds": round(end - start, 3),
        }
        label = segment.get("label")
        beat = segment.get("story_beat")
        reason = " / ".join(
            str(v).strip() for v in (label, beat) if isinstance(v, str) and v.strip()
        )
        if reason:
            cut["reason"] = reason
        cuts.append(cut)

    artifact: dict[str, Any] = {
        "version": "1.0",
        "cuts": cuts,
        "render_runtime": render_runtime,
    }
    audio_path = _as_path(session.get("audio_path"))
    if audio_path is not None:
        artifact["music"] = {"source": audio_path.name}
    tempo = _number(session.get("detected_tempo_bpm"))
    if tempo:
        artifact.setdefault("metadata", {})["detected_tempo_bpm"] = tempo
    return artifact, warnings


def session_summary(session: Mapping[str, Any]) -> dict[str, Any]:
    """Small human-facing description of what was imported."""
    segments = timeline_segments(session)
    with_image = sum(1 for s in segments if segment_image_path(s) is not None)
    with_video = sum(1 for s in segments if segment_video_path(s) is not None)
    last = max((_number(s.get("end")) for s in segments), default=0.0)
    return {
        "segments": len(segments),
        "with_image": with_image,
        "with_video": with_video,
        "timeline_seconds": round(last, 3),
        "audio_duration": _number(session.get("audio_duration")) or None,
        "detected_tempo_bpm": _number(session.get("detected_tempo_bpm")) or None,
        "video_engine": session.get("video_engine"),
        "image_model_mode": session.get("image_model_mode"),
    }


# ---------------------------------------------------------------------------
# export: scene_plan -> session
# ---------------------------------------------------------------------------

def stable_segment_id(scene_id: str) -> str:
    """Derive a VRGDG segment id from a scene id, deterministically.

    Re-exporting the same plan must produce the same segment ids, otherwise the
    scene map breaks and every artifact pointing at a shot goes stale. Shaped
    like VRGDG's own ``seg_<uuid>`` so it reads normally in the Builder.
    """
    digest = hashlib.sha1(f"openmontage:{scene_id}".encode("utf-8")).hexdigest()
    return (
        f"seg_{digest[0:8]}-{digest[8:12]}-{digest[12:16]}-"
        f"{digest[16:20]}-{digest[20:32]}"
    )


def _scene_label(scene: Mapping[str, Any]) -> str:
    scene_id = str(scene.get("id") or "scene")
    role = scene.get("narrative_role") or scene.get("shot_intent") or scene.get("type")
    role = str(role).replace("_", " ").strip() if role else ""
    return f"{scene_id} {role}".strip()


def _motion_notes(scene: Mapping[str, Any]) -> str:
    """Motion intent for the shot, in the words VRGDG's i2v step expects."""
    shot_language = scene.get("shot_language") or {}
    parts = [
        scene.get("movement"),
        shot_language.get("camera_movement")
        if shot_language.get("camera_movement") != "static"
        else None,
        scene.get("shot_intent"),
    ]
    text = ". ".join(
        str(p).replace("_", " ").strip() for p in parts if isinstance(p, str) and p.strip()
    )
    transition = scene.get("transition_out")
    if isinstance(transition, str) and transition.strip() and transition != "cut":
        text = f"{text}. Ends on a {transition.replace('_', ' ')}".strip(". ")
    return text


def scene_plan_to_segments(
    scene_plan: Mapping[str, Any],
    template_segment: Mapping[str, Any],
    *,
    scene_map: SceneMap,
    style_context: Mapping[str, Any] | None = None,
) -> tuple[list[dict[str, Any]], list[str]]:
    """Turn scene_plan scenes into VRGDG segments. Returns (segments, warnings).

    Each segment is a **copy of the template** with only the keys this bridge
    understands overwritten. The template comes from the session VRGDG itself
    scaffolded, which is the only safe way to get all ~110 fields with the
    defaults that release expects - inventing a segment would silently drop
    whatever the current version added.
    """
    from lib.shot_prompt_builder import build_shot_prompt

    scenes = scene_plan.get("scenes")
    if not isinstance(scenes, list) or not scenes:
        raise VRGDGBridgeError("scene_plan has no scenes to export")

    segments: list[dict[str, Any]] = []
    warnings: list[str] = []
    previous_end: float | None = None

    for scene in scenes:
        if not isinstance(scene, Mapping):
            warnings.append("skipped a scene entry that was not an object")
            continue
        scene_id = str(scene.get("id") or "")
        if not scene_id:
            warnings.append("skipped a scene with no id")
            continue

        start = _number(scene.get("start_seconds"))
        end = _number(scene.get("end_seconds"))
        if end <= start:
            warnings.append(
                f"{scene_id}: ends at or before it starts ({start} -> {end}); "
                f"exported anyway, fix the timing in the Builder"
            )
        if previous_end is not None:
            if start < previous_end - 1e-6:
                warnings.append(
                    f"{scene_id}: starts at {start} but the previous scene runs to "
                    f"{previous_end} - the timeline overlaps"
                )
            elif start > previous_end + 1e-6:
                warnings.append(
                    f"{scene_id}: leaves a {round(start - previous_end, 3)}s gap "
                    f"after the previous scene"
                )
        previous_end = end

        segment_id = stable_segment_id(scene_id)
        scene_map.bind(segment_id, scene_id)

        segment = copy.deepcopy(dict(template_segment))
        segment.update(
            {
                "id": segment_id,
                "track": "base",
                "start": start,
                "end": end,
                "label": _scene_label(scene),
                "notes": str(scene.get("description") or ""),
                "timeline_note": str(scene.get("overlay_notes") or ""),
                "story_beat": str(scene.get("narrative_role") or ""),
                "t2i_prompt": build_shot_prompt(dict(scene), dict(style_context or {}) or None),
                # i2v_notes is the motion brief; i2v_prompt is left empty so the
                # Builder's own prompt step (or a later OpenMontage pass) fills it
                # rather than this bridge guessing at video-model phrasing.
                "i2v_notes": _motion_notes(scene),
                "i2v_prompt": "",
                "i2v_prompt_origin": "manual",
                "source": "openmontage",
            }
        )
        segments.append(segment)

    if not segments:
        raise VRGDGBridgeError("scene_plan produced no usable segments")
    return segments, warnings


def apply_scene_plan_to_session(
    session: Mapping[str, Any],
    scene_plan: Mapping[str, Any],
    *,
    scene_map: SceneMap,
    style_context: Mapping[str, Any] | None = None,
) -> tuple[dict[str, Any], list[str]]:
    """Return a copy of *session* carrying the scene plan's timeline.

    Everything outside ``segments`` is left exactly as VRGDG wrote it.
    """
    if not isinstance(session, Mapping):
        raise VRGDGBridgeError("session must be an object")
    existing = session.get("segments")
    if not isinstance(existing, list) or not existing:
        raise VRGDGBridgeError(
            "The scaffolded session has no segment to use as a field template. "
            "Create the project through VRGDG's new_project route first."
        )

    template = next(
        (s for s in existing if isinstance(s, Mapping) and s.get("track", "base") == "base"),
        existing[0],
    )
    segments, warnings = scene_plan_to_segments(
        scene_plan, template, scene_map=scene_map, style_context=style_context
    )
    updated = copy.deepcopy(dict(session))
    updated["segments"] = segments
    return updated, warnings


def scene_plan_duration(scene_plan: Mapping[str, Any]) -> float:
    """Timeline length, i.e. the last scene's end."""
    scenes = scene_plan.get("scenes") or []
    return max(
        (_number(s.get("end_seconds")) for s in scenes if isinstance(s, Mapping)),
        default=0.0,
    )


def _srt_timestamp(seconds: float) -> str:
    total_ms = int(round(max(0.0, seconds) * 1000))
    hours, rem = divmod(total_ms, 3_600_000)
    minutes, rem = divmod(rem, 60_000)
    secs, millis = divmod(rem, 1000)
    return f"{hours:02d}:{minutes:02d}:{secs:02d},{millis:03d}"


def scene_plan_to_srt(scene_plan: Mapping[str, Any]) -> str:
    """Render the scene plan as an SRT.

    VRGDG's project-bound video routes require an SRT to derive per-scene
    timing, so one is written even when the film has no dialogue - each cue is
    the scene's label, which is what the Builder shows on the timeline.
    """
    lines: list[str] = []
    index = 0
    for scene in scene_plan.get("scenes") or []:
        if not isinstance(scene, Mapping):
            continue
        start = _number(scene.get("start_seconds"))
        end = _number(scene.get("end_seconds"))
        if end <= start:
            continue
        index += 1
        text = _scene_label(scene) or str(scene.get("id") or f"scene {index}")
        lines.append(str(index))
        lines.append(f"{_srt_timestamp(start)} --> {_srt_timestamp(end)}")
        lines.append(text)
        lines.append("")
    return "\n".join(lines)


def approved_images_by_scene(asset_manifest: Mapping[str, Any] | None) -> dict[str, str]:
    """Scene id -> project-relative image path, from an asset_manifest."""
    if not isinstance(asset_manifest, Mapping):
        return {}
    found: dict[str, str] = {}
    for asset in asset_manifest.get("assets") or []:
        if not isinstance(asset, Mapping) or asset.get("type") != "image":
            continue
        scene_id = asset.get("scene_id")
        path = asset.get("path")
        if isinstance(scene_id, str) and isinstance(path, str) and scene_id not in found:
            found[scene_id] = path
    return found
