"""Measure a track's rhythm into a ``beat_map`` artifact.

One analyzer, and you trust it. Beats are measured once, from the delivered
audio, and everything downstream cuts to that measurement - never to what a
generator was asked for, and never to a second opinion taken by ear or by
another tool. ACE-Step has been asked for 90 BPM on this machine and delivered
117.5; a plan timed from the request is wrong by 30% with nothing reporting it.

The backend is VRGDG's own ``analyze_audio``. That is deliberate: it is the
same measurement the Builder's timeline snaps to, so a scene boundary computed
here lands on the beat the Builder will draw. Using a different analyzer would
put OpenMontage's grid a few milliseconds off VRGDG's for no gain.

Despite living under ``/vrgdg/music_builder/``, the route is **not**
project-bound - it accepts any folder as scratch space, does not copy the
audio, and leaves nothing behind. It is used here as a plain analyzer.
"""

from __future__ import annotations

import time
from pathlib import Path
from typing import Any

from tools.base_tool import (
    BaseTool,
    Determinism,
    ExecutionMode,
    ResourceProfile,
    RetryPolicy,
    ToolResult,
    ToolRuntime,
    ToolStability,
    ToolStatus,
    ToolTier,
)
from tools._comfyui.vrgdg import VRGDGClient, VRGDGError

#: Below this many beats a "grid" is an artefact of the tracker, not a pulse.
#: Nine seconds of music at 120 BPM is 18 beats, so the floor is deliberately
#: low - it exists to catch a silent bed or a drone, not to judge short clips.
_MIN_BEATS_FOR_A_PULSE = 4

#: How far one beat interval may sit from the median and still count as on the
#: grid. Compared against the *median* interval, not the mean, because a single
#: mis-tracked beat drags a mean and leaves a median alone.
#:
#: **NOT CALIBRATED.** Both numbers below are guesses. Four guessed bands have
#: been checked against real output on this machine and all four were wrong
#: (DECISIONS #27, #31), so treat these the same way until a population of
#: measured tracks exists - see QUESTIONS.md Q1. They are set conservatively so
#: the failure is "weak" rather than a wrong "strong": a weak verdict costs
#: pacing by phrase, a wrong strong verdict costs every cut in the film.
_INTERVAL_TOLERANCE = 0.15

#: Fraction of intervals that must be within tolerance for the grid to be
#: trusted. A share, not a maximum, so one tracker glitch cannot condemn an
#: otherwise steady track - which is exactly what a max-deviation test does.
_ON_GRID_SHARE = 0.85


class AudioBeatmap(BaseTool):
    name = "audio_beatmap"
    version = "0.1.0"
    tier = ToolTier.CORE
    capability = "analysis"
    provider = "vrgdg"
    stability = ToolStability.EXPERIMENTAL
    execution_mode = ExecutionMode.SYNC
    determinism = Determinism.DETERMINISTIC
    runtime = ToolRuntime.LOCAL

    dependencies = []
    install_instructions = (
        "Start ComfyUI with the comfyui-vrgamedevgirl node pack installed and set "
        "COMFYUI_SERVER_URL (default http://localhost:8188)."
    )
    agent_skills = ["comfyui"]

    capabilities = ["beat_map", "tempo_detection"]
    supports = {
        "beats": True,
        "tempo": True,
        "peaks": True,
        "downbeats": False,
        "sections": False,
    }
    best_for = [
        "measuring the beat grid a scene plan will cut to",
        "recording the delivered tempo of a generated track, which is not the requested one",
        "producing the beat_map the score stage hands to the scene plan",
    ]
    not_good_for = [
        "musical structure - it finds beats, not verses and choruses",
        "downbeats - every beat comes back equal, so bar starts are unknown",
        "deciding whether a calm track should be cut to a grid at all - read `confidence`",
    ]

    input_schema = {
        "type": "object",
        "required": ["audio_path"],
        "properties": {
            "audio_path": {
                "type": "string",
                "description": "The track to measure. Read in place; never copied or modified.",
            },
            "output_path": {
                "type": "string",
                "description": (
                    "Where to write beat_map.json. Should be under "
                    "projects/<project-id>/artifacts/. Omit to return the artifact "
                    "without touching disk."
                ),
            },
            "source_path": {
                "type": "string",
                "description": (
                    "Project-relative path to record in the artifact, e.g. "
                    "assets/music/project_audio.mp3. Defaults to the audio filename. "
                    "Artifacts are project-relative by contract, and the absolute "
                    "path this tool was handed is not valid inside one."
                ),
            },
            "requested_tempo_bpm": {
                "type": "number",
                "description": (
                    "What the generator was asked for, when the track was generated. "
                    "Recorded only so the gap with the measured tempo stays visible. "
                    "Nothing may time from it."
                ),
            },
            "target_peaks": {
                "type": "integer",
                "default": 1600,
                "description": "Waveform resolution. Affects the peaks array, not the beats.",
            },
        },
    }

    resource_profile = ResourceProfile(
        cpu_cores=1, ram_mb=512, vram_mb=0, disk_mb=10, network_required=False
    )
    retry_policy = RetryPolicy(max_retries=0, retryable_errors=[])
    idempotency_key_fields = ["audio_path", "target_peaks"]
    side_effects = ["writes beat_map.json when output_path is given"]
    user_visible_verification = [
        "Play the track and check the reported tempo against how it feels",
        "Compare beats against the Builder's timeline markers - they should agree exactly",
    ]

    def __init__(self) -> None:
        self._client = VRGDGClient()

    def get_status(self) -> ToolStatus:
        return ToolStatus.AVAILABLE if self._client.is_available() else ToolStatus.UNAVAILABLE

    def get_info(self) -> dict[str, Any]:
        info = super().get_info()
        info["produces"] = ["beat_map"]
        info["backend"] = "vrgdg:analyze_audio"
        return info

    def estimate_cost(self, inputs: dict[str, Any]) -> float:
        return 0.0

    def estimate_runtime(self, inputs: dict[str, Any]) -> float:
        return 3.0

    def execute(self, inputs: dict[str, Any]) -> ToolResult:
        start = time.time()
        audio = Path(str(inputs.get("audio_path", ""))).expanduser()
        if not audio.is_file():
            return ToolResult(
                success=False, error=f"Audio file does not exist: {audio}"
            )
        if not self._client.is_available():
            return ToolResult(success=False, error=self._client.unavailable_reason())

        # The route wants somewhere to work; it writes nothing there for a plain
        # analysis, so the audio's own folder is the least surprising choice.
        scratch = audio.parent

        try:
            data = self._client.analyze_audio(
                str(audio.resolve()),
                str(scratch.resolve()),
                target_peaks=int(inputs.get("target_peaks", 1600) or 1600),
            )
        except VRGDGError as exc:
            return ToolResult(success=False, error=f"Beat analysis failed: {exc}")

        beats = [
            round(float(b), 3)
            for b in (data.get("beats") or [])
            if isinstance(b, (int, float))
        ]
        beats.sort()
        duration = float(data.get("duration") or 0.0)
        tempo = data.get("tempo_bpm")

        artifact: dict[str, Any] = {
            "version": "1.0",
            "source": str(inputs.get("source_path") or audio.name),
            "duration_seconds": round(duration, 3),
            "beats": beats,
            "measured_by": "vrgdg:analyze_audio",
            "confidence": _confidence(beats),
        }
        if isinstance(tempo, (int, float)) and tempo > 0:
            artifact["tempo_bpm"] = round(float(tempo), 3)
        requested = inputs.get("requested_tempo_bpm")
        if isinstance(requested, (int, float)) and requested > 0:
            artifact["requested_tempo_bpm"] = float(requested)

        warnings: list[str] = []
        if artifact["confidence"] != "strong":
            warnings.append(
                f"beat grid is {artifact['confidence']}: pace by phrase rather than "
                f"hard-cutting to these beats"
            )
        measured = artifact.get("tempo_bpm")
        if measured and requested and abs(measured - float(requested)) > 1.0:
            warnings.append(
                f"delivered tempo {measured} BPM is not the {requested} BPM asked for; "
                f"time everything from the measurement"
            )

        written: list[str] = []
        out = inputs.get("output_path")
        if out:
            path = Path(str(out))
            path.parent.mkdir(parents=True, exist_ok=True)
            import json

            path.write_text(json.dumps(artifact, indent=2), encoding="utf-8")
            written.append(str(path))

        return ToolResult(
            success=True,
            data={
                "provider": "vrgdg",
                "beat_map": artifact,
                "beat_count": len(beats),
                "warnings": warnings,
            },
            artifacts=written,
            cost_usd=0.0,
            duration_seconds=time.time() - start,
            model="vrgdg-analyze-audio",
        )


def _confidence(beats: list[float]) -> str:
    """How far to trust this grid.

    A tracker always returns *something*. On calm or beatless music that
    something is a metronome it imposed, and cutting hard to it looks wrong in
    a way nothing reports. So the grid is judged on whether its own intervals
    are steady, and the verdict travels with the artifact.
    """
    if len(beats) < _MIN_BEATS_FOR_A_PULSE:
        return "none"
    intervals = sorted(i for i in (b - a for a, b in zip(beats, beats[1:])) if i > 0)
    if len(intervals) < 2:
        return "none"
    median = intervals[len(intervals) // 2]
    if median <= 0:
        return "none"
    on_grid = sum(1 for i in intervals if abs(i - median) / median <= _INTERVAL_TOLERANCE)
    return "strong" if on_grid / len(intervals) >= _ON_GRID_SHARE else "weak"
