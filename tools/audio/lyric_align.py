"""Give a song's lines the times they are actually sung at.

A ``song`` is written before the track exists, so its lines carry words and no
times. Nothing can be placed on a timeline that way - not a scene boundary, not
a lyric cue, not a caption. This tool listens to the delivered audio and fills
the times in.

It is **forced alignment, not transcription.** VRGDG's
``VRGDG_TimestampedLyricsExtractor`` is handed the lyrics we wrote and asked
where they occur, rather than being asked what it hears. That distinction is
the whole value: a transcriber guesses at sung words and gets proper nouns,
stylised spellings and belted vowels wrong, and every mistake then has to be
corrected by hand. Alignment cannot get the words wrong because it is not
choosing them.

It also runs stem separation first (``VRGDG_GetStems``), so the vocal is
isolated before anything tries to hear it. That is why it works on a full mix
with brass and bass over the voice.

This is the capability OpenMontage's own ``transcriber`` cannot provide on this
machine - ``faster_whisper`` is not installed - reached instead through a graph
that already works.
"""

from __future__ import annotations

import json
import time
import urllib.error
import urllib.request
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

#: The extractor's own segment modes. ``reference_lines`` is the default and the
#: one that matches how a song artifact is written - one timed span per line we
#: authored. ``whisper_chunks`` ignores the reference and returns whatever the
#: model heard, which is transcription, not alignment.
SEGMENT_MODES = (
    "reference_lines",
    "exact_reference_lines",
    "reference_stanzas",
    "reference_scene_words",
    "whisper_chunks",
)

#: The graph terminates in VRGDG_ShowText: the deliverable is text in a node
#: output, not a file on disk. Output-node resolution deliberately refuses
#: display nodes, so this route reads the history entry directly instead.
_TEXT_NODE_CLASS = "VRGDG_ShowText"


class LyricAlign(BaseTool):
    name = "lyric_align"
    version = "0.1.0"
    tier = ToolTier.CORE
    capability = "analysis"
    provider = "vrgdg"
    stability = ToolStability.EXPERIMENTAL
    execution_mode = ExecutionMode.SYNC
    determinism = Determinism.STOCHASTIC
    runtime = ToolRuntime.LOCAL_GPU

    dependencies = []
    install_instructions = (
        "Start ComfyUI with the comfyui-vrgamedevgirl node pack installed and set "
        "COMFYUI_SERVER_URL (default http://localhost:8188). The first run "
        "downloads a Whisper model and a stem-separation model."
    )
    agent_skills = ["comfyui", "speech-to-text"]

    capabilities = ["lyric_alignment", "word_timings", "instrumental_gaps"]
    supports = {
        "forced_alignment": True,
        "word_level": True,
        "stem_separation": True,
        "instrumental_gaps": True,
        "offline": True,
    }
    best_for = [
        "filling times into a song artifact written before the track existed",
        "word timings for a karaoke or word-by-word caption burn",
        "finding where the vocal stops, so a shot can be planned over the instrumental",
    ]
    not_good_for = [
        "finding out what a track says - it is told the words, it does not guess them",
        "speech that is not sung over music; use the transcriber for narration",
    ]

    input_schema = {
        "type": "object",
        "required": ["audio_path"],
        "properties": {
            "audio_path": {"type": "string", "description": "The delivered track."},
            "song": {
                "type": "object",
                "description": (
                    "The song artifact. Its lines supply the reference lyrics and "
                    "receive the times. Returned filled in, never mutated in place."
                ),
            },
            "song_path": {
                "type": "string",
                "description": (
                    "Path to song.json. Used when `song` is not given inline; the "
                    "filled-in artifact is written back to this path."
                ),
            },
            "reference_lyrics": {
                "type": "string",
                "description": (
                    "Raw lyrics, one line per line, when there is no song artifact. "
                    "Ignored when a song is supplied - the song is the source of truth."
                ),
            },
            "language": {"type": "string", "default": "english"},
            "segment_mode": {
                "type": "string",
                "enum": list(SEGMENT_MODES),
                "default": "reference_lines",
                "description": (
                    "reference_lines: one timed span per authored line (the default, "
                    "and what a song artifact wants). whisper_chunks: ignore the "
                    "reference and return what was heard - transcription, not alignment."
                ),
            },
            "model_name": {"type": "string", "default": "large-v3"},
            "include_instrumental_gaps": {"type": "boolean", "default": True},
            "min_gap_seconds": {"type": "number", "default": 1.0},
            "timeout_seconds": {"type": "number", "default": 900},
        },
    }

    resource_profile = ResourceProfile(
        cpu_cores=2, ram_mb=4096, vram_mb=4096, disk_mb=100, network_required=False
    )
    retry_policy = RetryPolicy(max_retries=0, retryable_errors=[])
    idempotency_key_fields = ["audio_path", "segment_mode", "model_name"]
    side_effects = ["writes the filled-in song back to song_path when one was given"]
    user_visible_verification = [
        "Play the track and check one line starts where the alignment says",
        "Check the instrumental gaps match where the vocal actually stops",
    ]

    def __init__(self) -> None:
        self._client = VRGDGClient()

    def get_status(self) -> ToolStatus:
        return ToolStatus.AVAILABLE if self._client.is_available() else ToolStatus.UNAVAILABLE

    def get_info(self) -> dict[str, Any]:
        info = super().get_info()
        info["produces"] = ["song", "lyric_alignment"]
        info["backend"] = "vrgdg:timestamped_transcribe"
        info["method"] = "forced alignment against supplied lyrics, not transcription"
        return info

    def estimate_cost(self, inputs: dict[str, Any]) -> float:
        return 0.0

    def estimate_runtime(self, inputs: dict[str, Any]) -> float:
        return 90.0

    def execute(self, inputs: dict[str, Any]) -> ToolResult:
        start = time.time()
        audio = Path(str(inputs.get("audio_path", ""))).expanduser()
        if not audio.is_file():
            return ToolResult(success=False, error=f"Audio file does not exist: {audio}")
        if not self._client.is_available():
            return ToolResult(success=False, error=self._client.unavailable_reason())

        song, song_path = self._resolve_song(inputs)
        reference = (
            song_reference_lyrics(song)
            if song
            else str(inputs.get("reference_lyrics") or "")
        )
        if not reference.strip():
            return ToolResult(
                success=False,
                error=(
                    "Nothing to align. Pass a song artifact with lines, or "
                    "reference_lyrics. This tool aligns words it is given; it does "
                    "not transcribe."
                ),
            )

        try:
            graph = self._client.build(
                "timestamped_transcribe",
                {
                    "audio_path": str(audio.resolve()),
                    "reference_lyrics": reference,
                    "language": str(inputs.get("language") or "english"),
                    "segment_mode": str(inputs.get("segment_mode") or "reference_lines"),
                    "model_name": str(inputs.get("model_name") or "large-v3"),
                    "include_instrumental_gaps": bool(
                        inputs.get("include_instrumental_gaps", True)
                    ),
                    "min_gap_seconds": float(inputs.get("min_gap_seconds", 1.0) or 1.0),
                },
            )
        except VRGDGError as exc:
            return ToolResult(success=False, error=f"Could not build the graph: {exc}")

        try:
            alignment = self._run(
                graph.prompt, float(inputs.get("timeout_seconds", 900) or 900)
            )
        except (VRGDGError, TimeoutError) as exc:
            return ToolResult(success=False, error=str(exc))

        segments = [s for s in alignment.get("segments", []) if isinstance(s, dict)]
        vocal = [s for s in segments if s.get("type") != "instrumental"]
        warnings = [
            f"segment {s.get('index', '?')}: {s['timing_warning']}"
            for s in segments
            if s.get("timing_warning")
        ]

        written: list[str] = []
        filled = None
        if song:
            filled, fill_warnings = fill_song_times(song, vocal)
            warnings.extend(fill_warnings)
            if song_path is not None:
                song_path.write_text(json.dumps(filled, indent=2), encoding="utf-8")
                written.append(str(song_path))

        return ToolResult(
            success=True,
            data={
                "provider": "vrgdg",
                "method": "forced_alignment",
                "song": filled,
                "alignment": alignment,
                "vocal_segments": len(vocal),
                "instrumental_segments": len(segments) - len(vocal),
                "warnings": warnings,
            },
            artifacts=written,
            cost_usd=0.0,
            duration_seconds=time.time() - start,
            model=str(alignment.get("model_name") or inputs.get("model_name") or "large-v3"),
        )

    # ------------------------------------------------------------------

    def _resolve_song(
        self, inputs: dict[str, Any]
    ) -> tuple[dict[str, Any] | None, Path | None]:
        song = inputs.get("song")
        if isinstance(song, dict):
            return song, None
        raw = str(inputs.get("song_path") or "").strip()
        if not raw:
            return None, None
        path = Path(raw)
        if not path.is_file():
            return None, None
        try:
            loaded = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return None, None
        return (loaded, path) if isinstance(loaded, dict) else (None, None)

    def _run(self, prompt: dict[str, Any], timeout: float) -> dict[str, Any]:
        """Queue the graph and read the text its display node produced."""
        base = self._client.server_url.rstrip("/")
        body = json.dumps({"prompt": prompt, "client_id": "openmontage-lyric-align"})
        request = urllib.request.Request(
            f"{base}/prompt",
            data=body.encode("utf-8"),
            headers={"Content-Type": "application/json"},
        )
        try:
            queued = json.loads(urllib.request.urlopen(request, timeout=60).read())
        except urllib.error.HTTPError as exc:
            raise VRGDGError(f"ComfyUI refused the graph: {exc.read().decode()[:400]}")
        prompt_id = queued.get("prompt_id")
        if not prompt_id:
            raise VRGDGError("ComfyUI accepted the graph but returned no prompt_id")

        deadline = time.time() + timeout
        while time.time() < deadline:
            try:
                # The server serves HTTP from the process loading models off
                # disk, so a first run can block for tens of seconds. Budget for
                # the stall rather than calling it a failure.
                history = json.loads(
                    urllib.request.urlopen(f"{base}/history/{prompt_id}", timeout=60).read()
                )
            except Exception:
                time.sleep(5)
                continue
            entry = history.get(prompt_id)
            if not entry:
                time.sleep(5)
                continue
            status = entry.get("status", {})
            if status.get("status_str") == "error":
                raise VRGDGError(
                    f"Alignment failed in ComfyUI: {str(status.get('messages'))[:400]}"
                )
            for output in entry.get("outputs", {}).values():
                for text in output.get("text", []) or []:
                    try:
                        parsed = json.loads(text)
                    except (TypeError, json.JSONDecodeError):
                        continue
                    if isinstance(parsed, dict) and "segments" in parsed:
                        return parsed
            raise VRGDGError(
                "Alignment finished but produced no readable segments. The graph's "
                "text node returned nothing parseable."
            )
        raise TimeoutError(
            f"Alignment did not finish within {timeout:.0f}s. The first run downloads "
            f"a Whisper model and a stem-separation model; try a longer timeout."
        )


def song_reference_lyrics(song: dict[str, Any]) -> str:
    """The song's lines as the aligner wants them - one per line, words only.

    Delivery directions and section tags are deliberately left out. They are
    instructions to a *generator*; an aligner handed ``[powerful belting]`` will
    look for someone singing those words.
    """
    lines: list[str] = []
    for section in song.get("sections") or []:
        if not isinstance(section, dict):
            continue
        for line in section.get("lines") or []:
            if isinstance(line, dict) and str(line.get("text") or "").strip():
                lines.append(str(line["text"]).strip())
    return "\n".join(lines)


def fill_song_times(
    song: dict[str, Any], vocal_segments: list[dict[str, Any]]
) -> tuple[dict[str, Any], list[str]]:
    """Copy aligned times onto a song's lines. Returns (filled copy, warnings).

    Matched by order, because that is what ``reference_lines`` guarantees: the
    aligner was handed the lines in order and returns one span per line in the
    same order. Matching on text instead would fail on a repeated chorus line,
    which is the most common line in any song.
    """
    import copy

    filled = copy.deepcopy(song)
    warnings: list[str] = []
    flat = [
        line
        for section in filled.get("sections") or []
        if isinstance(section, dict)
        for line in section.get("lines") or []
        if isinstance(line, dict) and str(line.get("text") or "").strip()
    ]

    if len(flat) != len(vocal_segments):
        warnings.append(
            f"the song has {len(flat)} lines but alignment returned "
            f"{len(vocal_segments)} vocal spans; times were filled in for the "
            f"first {min(len(flat), len(vocal_segments))} in order and the rest "
            f"left without times"
        )

    for line, segment in zip(flat, vocal_segments):
        line["start_seconds"] = round(float(segment.get("start", 0.0)), 3)
        line["end_seconds"] = round(float(segment.get("end", 0.0)), 3)

    # Section spans follow from their lines, so a caller can group scenes by
    # section without re-deriving them.
    for section in filled.get("sections") or []:
        if not isinstance(section, dict):
            continue
        timed = [
            l
            for l in section.get("lines") or []
            if isinstance(l, dict) and "start_seconds" in l
        ]
        if timed:
            section["start_seconds"] = min(l["start_seconds"] for l in timed)
            section["end_seconds"] = max(l["end_seconds"] for l in timed)
    return filled, warnings
