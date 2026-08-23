"""ComfyUI music generation via a local or remote ComfyUI server.

Default workflow: ACE-Step 1.5 Turbo AIO text-to-audio using ComfyUI's native
``TextEncodeAceStepAudio1.5``/``EmptyAceStep1.5LatentAudio`` nodes. Custom workflows are still accepted
via ``workflow_json``/``workflow_path`` for other ACE-Step node packs, other
versions (e.g. ACE-Step 1.5), or entirely different audio models -- the same
override contract ``comfyui_image``/``comfyui_video`` offer.
"""

from __future__ import annotations

import json
import shutil
import subprocess
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
from tools._comfyui.client import ComfyUIClient, ComfyUIError
from tools._comfyui.metadata import (
    BUNDLED_MODEL_STACKS,
    COMFYUI_SETUP_OFFER,
    missing_models_payload,
    model_stack,
    workflow_hash,
)
from tools._comfyui.profiles import apply_workflow_bindings, load_workflow_profile

_WORKFLOWS = Path(__file__).resolve().parent.parent / "_comfyui" / "workflows"
_PROFILES = Path(__file__).resolve().parent.parent / "_comfyui" / "profiles"

# Model required by the bundled ACE-Step 1.5 Turbo AIO workflow
_WORKFLOW_KEY = "ace-step-1.5-turbo-aio-t2a"
_WORKFLOW_NAME = "ace-step-1.5-turbo-aio-t2a.json"
_PROFILE_NAME = "ace-step-1.5-turbo-aio-t2a.json"
_REQUIRED_MODELS = ["ace_step_1.5_turbo_aio.safetensors"]


class ComfyUIMusic(BaseTool):
    name = "comfyui_music"
    version = "0.3.0"
    tier = ToolTier.GENERATE
    capability = "music_generation"
    provider = "comfyui"
    stability = ToolStability.EXPERIMENTAL
    execution_mode = ExecutionMode.SYNC
    determinism = Determinism.SEEDED
    runtime = ToolRuntime.LOCAL_GPU

    dependencies = []  # checked at runtime via server health
    setup_offer = COMFYUI_SETUP_OFFER
    install_instructions = (
        "Start a ComfyUI server and set COMFYUI_SERVER_URL "
        "(default http://localhost:8188).\n"
        "Requires ace_step_1.5_turbo_aio.safetensors in ComfyUI's checkpoints "
        "directory for the bundled workflow.\n"
        "Running a separate ComfyUI instance for music? Set "
        "COMFYUI_MUSIC_SERVER_URL instead -- it takes priority over "
        "COMFYUI_SERVER_URL for this tool only."
    )
    agent_skills = ["comfyui"]

    capabilities = ["generate_background_music", "generate_song", "generate_instrumental"]
    supports = {
        "seed": True,
        "lyrics": True,
        "custom_workflow": True,
        "custom_output_node": True,
        "offline": True,
    }
    best_for = [
        "local GPU music generation without API costs",
        "instrumentals and songs with lyrics via the bundled ACE-Step 1.5 Turbo AIO workflow",
        "full control over sampling or other ACE-Step versions/node packs via custom ComfyUI workflows",
    ]
    not_good_for = [
        "setups without a running ComfyUI server",
        "CPU-only machines",
    ]
    fallback_tools = ["suno_music", "music_gen"]

    input_schema = {
        "type": "object",
        "required": ["prompt"],
        "properties": {
            "prompt": {
                "type": "string",
                "description": (
                    "Style/mood/genre description (ACE-Step 'tags'), e.g. "
                    "'upbeat electronic pop, female vocals, driving bassline'. "
                    "Comma-separated tags work best. Not injected for custom workflows."
                ),
            },
            "lyrics": {
                "type": "string",
                "default": "",
                "description": (
                    "Optional lyrics. Leave empty for instrumental. Supports structure "
                    "tags like [verse]/[chorus]/[bridge] and language-code prefixes "
                    "(e.g. [zh], [ja]) for non-English lines."
                ),
            },
            "duration_seconds": {"type": "number", "default": 120.0},
            "steps": {"type": "integer", "default": 8},
            "cfg": {"type": "number", "default": 1.0, "description": "KSampler CFG"},
            "cfg_scale": {"type": "number", "default": 2.0, "description": "ACE-Step audio-code guidance"},
            "bpm": {"type": "integer", "default": 120},
            "timesignature": {"type": "string", "default": "4"},
            "language": {"type": "string", "default": "en"},
            "keyscale": {"type": "string", "default": "C major"},
            "generate_audio_codes": {"type": "boolean", "default": True},
            "temperature": {"type": "number", "default": 0.85},
            "top_p": {"type": "number", "default": 0.9},
            "top_k": {"type": "integer", "default": 0},
            "min_p": {"type": "number", "default": 0.0},
            "seed": {"type": "integer", "description": "Random if omitted"},
            "output_path": {"type": "string", "description": "Where to save the audio"},
            "workflow_json": {
                "type": "string",
                "description": "Optional full ComfyUI workflow JSON. Requires output_node.",
            },
            "workflow_path": {
                "type": "string",
                "description": "Optional path to a ComfyUI workflow JSON file. Requires output_node.",
            },
            "output_node": {
                "type": "string",
                "description": "ComfyUI output node ID for custom workflow_json/workflow_path.",
            },
            "workflow_name": {
                "type": "string",
                "description": "Optional human-readable provenance label for a custom workflow.",
            },
            "workflow_model": {
                "type": "string",
                "description": "Optional model/provenance label for a custom workflow.",
            },
            "workflow_model_stack": {
                "type": "array",
                "description": (
                    "Optional provenance metadata for custom workflow dependencies. "
                    "Items should include name, role, and node-pack origin when known."
                ),
                "items": {"type": "object"},
            },
            "timeout_seconds": {
                "type": "integer",
                "description": "How long to wait for the ComfyUI job before giving up. Default 1800s (30min).",
            },
            "resume_prompt_id": {
                "type": "string",
                "description": "A prompt_id from a previous timed-out call. Skips resubmission and resumes waiting/downloading.",
            },
        },
    }

    resource_profile = ResourceProfile(
        cpu_cores=2, ram_mb=8000, vram_mb=8000, disk_mb=500, network_required=False,
    )
    retry_policy = RetryPolicy(max_retries=1, retryable_errors=["timeout"])
    idempotency_key_fields = ["prompt", "lyrics", "duration_seconds", "seed"]
    side_effects = ["writes audio file to output_path"]
    user_visible_verification = ["Listen to generated audio for mood, genre accuracy, and quality"]

    def __init__(self) -> None:
        self._client = ComfyUIClient(capability="music")
        self._last_progress_log = 0.0

    def get_status(self) -> ToolStatus:
        if not self._client.is_available():
            return ToolStatus.UNAVAILABLE
        _, missing = self._client.check_models(_REQUIRED_MODELS)
        if missing:
            return ToolStatus.DEGRADED
        return ToolStatus.AVAILABLE

    def estimate_cost(self, inputs: dict[str, Any]) -> float:
        return 0.0

    def estimate_runtime(self, inputs: dict[str, Any]) -> float:
        return float(inputs.get("steps", 50)) * 2.0

    def get_info(self) -> dict[str, Any]:
        info = super().get_info()
        info["setup_offer"] = self.setup_offer
        info["bundled_model_stack"] = BUNDLED_MODEL_STACKS[_WORKFLOW_KEY]
        info["bundled_workflow_profile"] = _PROFILE_NAME
        return info

    def _log_progress(self, data: dict) -> None:
        """Throttled progress line (see comfyui_video for rationale)."""
        now = time.monotonic()
        if now - self._last_progress_log < 10:
            return
        self._last_progress_log = now
        value, max_value = data.get("value"), data.get("max")
        if value is not None and max_value:
            print(f"[comfyui_music] step {value}/{max_value}")

    def execute(self, inputs: dict[str, Any]) -> ToolResult:
        custom_workflow = bool(inputs.get("workflow_json") or inputs.get("workflow_path"))
        if custom_workflow and not inputs.get("output_node"):
            return ToolResult(
                success=False,
                error=(
                    "Custom ComfyUI workflows require output_node so OpenMontage "
                    "knows which ComfyUI node to download artifacts from."
                ),
            )

        if not self._client.is_available():
            return ToolResult(success=False, error=self._client.unavailable_reason())

        if not custom_workflow:
            _, missing = self._client.check_models(_REQUIRED_MODELS)
            if missing:
                return ToolResult(
                    success=False,
                    data=missing_models_payload(
                        missing,
                        workflow_key=_WORKFLOW_KEY,
                        workflow_name=_WORKFLOW_NAME,
                    ),
                    error=(
                        f"ComfyUI server is running but missing required models: "
                        f"{', '.join(missing)}.\n"
                        f"See data.missing_models for destination hints and download URLs."
                    ),
                )

        start = time.time()
        seed = inputs.get("seed")
        if seed is None:
            seed = ComfyUIClient.random_seed()
        output_path = Path(inputs.get("output_path", f"comfyui_music_{seed}.mp3"))

        try:
            if custom_workflow:
                workflow = self._load_custom_workflow(inputs)
                output_node = str(inputs["output_node"])
            else:
                workflow = ComfyUIClient.load_workflow(_WORKFLOWS / _WORKFLOW_NAME)
                profile = load_workflow_profile(_PROFILES / _PROFILE_NAME)
                workflow = apply_workflow_bindings(workflow, profile, {
                    "prompt": inputs["prompt"],
                    "lyrics": inputs.get("lyrics", ""),
                    "duration_seconds": inputs.get("duration_seconds", 120.0),
                    "seed": seed,
                    "steps": inputs.get("steps", 8),
                    "cfg": inputs.get("cfg", 1.0),
                    "cfg_scale": inputs.get("cfg_scale", 2.0),
                    "bpm": inputs.get("bpm", 120),
                    "timesignature": inputs.get("timesignature", "4"),
                    "language": inputs.get("language", "en"),
                    "keyscale": inputs.get("keyscale", "C major"),
                    "generate_audio_codes": inputs.get("generate_audio_codes", True),
                    "temperature": inputs.get("temperature", 0.85),
                    "top_p": inputs.get("top_p", 0.9),
                    "top_k": inputs.get("top_k", 0),
                    "min_p": inputs.get("min_p", 0.0),
                    "filename_prefix": inputs.get("filename_prefix", f"audio/{output_path.stem}"),
                })
                output_node = profile["output_node"]

            provenance = self._workflow_provenance(inputs, custom_workflow, output_node, workflow)
            paths = self._client.generate(
                workflow,
                output_node=output_node,
                dest=output_path,
                timeout=inputs.get("timeout_seconds", 1800),
                interval=10,
                resume_prompt_id=inputs.get("resume_prompt_id"),
                on_progress=self._log_progress,
            )

        except ComfyUIError as exc:
            data = {"prompt_id": exc.prompt_id} if exc.prompt_id else {}
            if exc.prompt_id:
                error_msg = (
                    f"{exc}\n\nThis job was NOT cancelled and is very likely still "
                    f"running server-side. To recover it without resubmitting, call "
                    f"execute() again with resume_prompt_id={exc.prompt_id!r} "
                    f"(and a longer timeout_seconds if it needs more time), or poll "
                    f"GET {{COMFYUI_SERVER_URL}}/history/{exc.prompt_id} directly."
                )
            else:
                error_msg = str(exc)
            return ToolResult(success=False, error=error_msg, data=data)
        except Exception as exc:
            return ToolResult(success=False, error=f"ComfyUI music generation failed: {exc}")

        duration = self._probe_duration(paths[0])
        model_name = self._model_name(inputs, custom_workflow)
        return ToolResult(
            success=True,
            data={
                "provider": "comfyui",
                "model": model_name,
                "prompt": inputs["prompt"],
                "lyrics": inputs.get("lyrics", ""),
                "duration_seconds": duration,
                "output": str(paths[0]),
                "format": paths[0].suffix.lstrip("."),
                "workflow_provenance": provenance,
            },
            artifacts=[str(p) for p in paths],
            cost_usd=0.0,
            duration_seconds=round(time.time() - start, 2),
            seed=seed,
            model=model_name,
        )

    @staticmethod
    def _load_custom_workflow(inputs: dict[str, Any]) -> dict:
        if inputs.get("workflow_json"):
            return json.loads(inputs["workflow_json"])
        return ComfyUIClient.load_workflow(Path(inputs["workflow_path"]))

    @staticmethod
    def _model_name(inputs: dict[str, Any], custom_workflow: bool) -> str:
        if not custom_workflow:
            return "ace-step-1.5-turbo-aio"
        return (
            inputs.get("workflow_model")
            or inputs.get("model")
            or inputs.get("workflow_name")
            or "custom-comfyui-workflow"
        )

    @staticmethod
    def _workflow_provenance(
        inputs: dict[str, Any],
        custom_workflow: bool,
        output_node: str,
        workflow: dict[str, Any],
    ) -> dict[str, Any]:
        if not custom_workflow:
            return {
                "source": "bundled",
                "workflow": _WORKFLOW_NAME,
                "workflow_hash_sha256": workflow_hash(workflow),
                "model_stack": model_stack(_WORKFLOW_KEY, inputs),
                "output_node": output_node,
                "workflow_profile": _PROFILE_NAME,
            }
        stack = inputs.get("workflow_model_stack")
        return {
            "source": "user_supplied",
            "workflow_name": inputs.get("workflow_name"),
            "workflow_path": inputs.get("workflow_path"),
            "model": inputs.get("workflow_model") or inputs.get("model"),
            "workflow_hash_sha256": workflow_hash(workflow),
            "model_stack": stack if isinstance(stack, list) else [],
            "model_stack_source": "caller_supplied" if stack else "unknown_custom_workflow",
            "output_node": output_node,
        }

    @staticmethod
    def _probe_duration(path: Path) -> float | None:
        """Best-effort track duration via ffprobe; None if unavailable."""
        if shutil.which("ffprobe") is None:
            return None
        try:
            out = subprocess.run(
                [
                    "ffprobe", "-v", "error",
                    "-show_entries", "format=duration",
                    "-of", "default=noprint_wrappers=1:nokey=1",
                    str(path),
                ],
                capture_output=True, text=True, timeout=15, check=True,
            )
            value = out.stdout.strip()
            return round(float(value), 2) if value else None
        except (subprocess.SubprocessError, ValueError):
            return None
