"""Qwen3-TTS generation through a local ComfyUI workflow."""

from __future__ import annotations

import json
import shutil
import subprocess
import time
from pathlib import Path
from typing import Any

from tools._comfyui.client import ComfyUIClient, ComfyUIError
from tools._comfyui.metadata import COMFYUI_SETUP_OFFER, workflow_hash
from tools._comfyui.profiles import apply_workflow_bindings, load_workflow_profile
from tools.base_tool import (
    BaseTool, Determinism, ExecutionMode, ResourceProfile, RetryPolicy,
    ToolResult, ToolRuntime, ToolStability, ToolStatus, ToolTier,
)

_ROOT = Path(__file__).resolve().parents[2]
_WORKFLOW_DIR = _ROOT / "tools" / "_comfyui" / "workflows"
_PROFILE_DIR = _ROOT / "tools" / "_comfyui" / "profiles"
_MODES = {
    "voice_design": ("qwen3-tts-voice-design.json", "qwen3-tts-voice-design.json"),
    "custom_voice": ("qwen3-tts-custom-voice.json", "qwen3-tts-custom-voice.json"),
    "voice_clone": ("qwen3-tts-voice-clone.json", "qwen3-tts-voice-clone.json"),
}


class ComfyUITTS(BaseTool):
    name = "comfyui_tts"
    version = "0.1.0"
    tier = ToolTier.VOICE
    capability = "tts"
    provider = "comfyui"
    stability = ToolStability.EXPERIMENTAL
    execution_mode = ExecutionMode.SYNC
    determinism = Determinism.SEEDED
    runtime = ToolRuntime.LOCAL_GPU

    dependencies = []
    setup_offer = COMFYUI_SETUP_OFFER
    install_instructions = (
        "Start ComfyUI with the AILab Qwen3-TTS custom nodes installed. "
        "COMFYUI_SERVER_URL defaults to http://localhost:8188; "
        "COMFYUI_TTS_SERVER_URL may point TTS at a separate instance."
    )
    agent_skills = ["text-to-speech", "comfyui"]
    capabilities = ["text_to_speech", "voice_design", "custom_voice", "voice_cloning"]
    supports = {
        "offline": True,
        "multilingual": True,
        "seed": True,
        "voice_cloning": True,
        "voice_design": True,
        "reference_audio": True,
    }
    best_for = [
        "free local Qwen3-TTS narration through ComfyUI",
        "designed voices, bundled speaker voices, and reference-audio voice cloning",
    ]
    not_good_for = ["setups without the AILab Qwen3-TTS ComfyUI nodes", "CPU-only machines"]
    fallback_tools = ["piper_tts", "openai_tts", "elevenlabs_tts"]

    input_schema = {
        "type": "object",
        "required": ["text"],
        "properties": {
            "text": {"type": "string"},
            "mode": {
                "type": "string",
                "enum": ["voice_design", "custom_voice", "voice_clone"],
                "default": "voice_design",
            },
            "speaker": {"type": "string", "default": "Ryan"},
            "character": {"type": "string", "default": "Female"},
            "style_name": {"type": "string", "default": "Warm"},
            "instructions": {"type": "string", "default": ""},
            "language": {"type": "string", "default": "Auto"},
            "model_size": {"type": "string", "default": "1.7B"},
            "seed": {"type": "integer"},
            "unload_models": {"type": "boolean", "default": True},
            "reference_audio_path": {"type": "string"},
            "reference_text": {"type": "string", "default": ""},
            "x_vector_only": {"type": "boolean", "default": False},
            "output_path": {"type": "string"},
            "filename_prefix": {"type": "string"},
            "timeout_seconds": {"type": "integer", "default": 1800},
            "resume_prompt_id": {"type": "string"},
        },
    }
    resource_profile = ResourceProfile(
        cpu_cores=2, ram_mb=8000, vram_mb=8000, disk_mb=500, network_required=False
    )
    retry_policy = RetryPolicy(max_retries=1, retryable_errors=["timeout"])
    idempotency_key_fields = ["text", "mode", "speaker", "instructions", "seed"]
    side_effects = ["writes audio file to output_path"]
    user_visible_verification = ["Listen for intelligibility, voice consistency, and delivery"]

    def __init__(self) -> None:
        self._client = ComfyUIClient(capability="tts")

    def get_status(self) -> ToolStatus:
        return ToolStatus.AVAILABLE if self._client.is_available() else ToolStatus.UNAVAILABLE

    def estimate_cost(self, inputs: dict[str, Any]) -> float:
        return 0.0

    def estimate_runtime(self, inputs: dict[str, Any]) -> float:
        return max(30.0, len(str(inputs.get("text", ""))) * 0.5)

    def get_info(self) -> dict[str, Any]:
        info = super().get_info()
        info["setup_offer"] = self.setup_offer
        info["workflow_modes"] = sorted(_MODES)
        return info

    def execute(self, inputs: dict[str, Any]) -> ToolResult:
        if not self._client.is_available():
            return ToolResult(success=False, error=self._client.unavailable_reason())

        mode = str(inputs.get("mode", "voice_design"))
        if mode not in _MODES:
            return ToolResult(success=False, error=f"Unsupported Qwen3-TTS mode: {mode}")
        if mode == "voice_clone" and not inputs.get("reference_audio_path"):
            return ToolResult(success=False, error="voice_clone requires reference_audio_path")

        seed = inputs.get("seed")
        if seed is None:
            seed = ComfyUIClient.random_seed()
        output_path = Path(inputs.get("output_path", f"qwen3_tts_{mode}_{seed}.mp3"))
        workflow_name, profile_name = _MODES[mode]

        try:
            workflow = ComfyUIClient.load_workflow(_WORKFLOW_DIR / workflow_name)
            profile = load_workflow_profile(_PROFILE_DIR / profile_name)
            values = self._binding_values(inputs, mode, seed, output_path)
            if mode == "voice_clone":
                ref_path = Path(str(inputs["reference_audio_path"]))
                if not ref_path.is_file():
                    return ToolResult(success=False, error=f"Reference audio not found: {ref_path}")
                upload_name = f"om_{output_path.stem}_reference{ref_path.suffix}"
                values["reference_audio"] = self._client.upload_input(ref_path, upload_name)
            workflow = apply_workflow_bindings(workflow, profile, values)

            start = time.time()
            paths = self._client.generate(
                workflow,
                output_node=profile["output_node"],
                dest=output_path,
                timeout=int(inputs.get("timeout_seconds", 1800)),
                interval=5,
                resume_prompt_id=inputs.get("resume_prompt_id"),
            )
        except ComfyUIError as exc:
            data = {"prompt_id": exc.prompt_id} if exc.prompt_id else {}
            return ToolResult(success=False, error=f"ComfyUI Qwen3-TTS failed: {exc}", data=data)
        except Exception as exc:
            return ToolResult(success=False, error=f"ComfyUI Qwen3-TTS failed: {exc}")

        duration = self._probe_duration(paths[0])
        return ToolResult(
            success=True,
            data={
                "provider": "comfyui",
                "model": f"Qwen3-TTS {inputs.get('model_size', '1.7B')}",
                "mode": mode,
                "text": inputs["text"],
                "duration_seconds": duration,
                "output": str(paths[0]),
                "format": paths[0].suffix.lstrip("."),
                "workflow_provenance": {
                    "source": "bundled_user_workflow",
                    "workflow": workflow_name,
                    "workflow_hash_sha256": workflow_hash(workflow),
                    "profile": profile_name,
                    "output_node": profile["output_node"],
                },
            },
            artifacts=[str(path) for path in paths],
            cost_usd=0.0,
            duration_seconds=round(time.time() - start, 2),
            seed=seed,
            model=f"Qwen3-TTS {inputs.get('model_size', '1.7B')}",
        )

    @staticmethod
    def _binding_values(inputs: dict[str, Any], mode: str, seed: int, output_path: Path) -> dict[str, Any]:
        values: dict[str, Any] = {
            "text": inputs["text"],
            "language": inputs.get("language", "Auto"),
            "model_size": inputs.get("model_size", "1.7B"),
            "unload_models": inputs.get("unload_models", True),
            "seed": seed,
            "filename_prefix": inputs.get("filename_prefix", f"audio/{output_path.stem}"),
        }
        if mode in {"voice_design", "custom_voice"}:
            values.update({
                "character": inputs.get("character", "Female" if mode == "voice_design" else "Male"),
                "style": inputs.get("style_name", "Warm" if mode == "voice_design" else "Gentle"),
                "instructions": inputs.get("instructions", ""),
            })
        if mode == "custom_voice":
            values["speaker"] = inputs.get("speaker", "Ryan")
        if mode == "voice_clone":
            values.update({
                "reference_text": inputs.get("reference_text", ""),
                "x_vector_only": inputs.get("x_vector_only", False),
            })
        return values

    @staticmethod
    def _probe_duration(path: Path) -> float | None:
        if shutil.which("ffprobe") is None:
            return None
        try:
            result = subprocess.run(
                ["ffprobe", "-v", "error", "-show_entries", "format=duration",
                 "-of", "default=noprint_wrappers=1:nokey=1", str(path)],
                capture_output=True, text=True, timeout=15, check=True,
            )
            return round(float(result.stdout.strip()), 2)
        except (subprocess.SubprocessError, ValueError):
            return None
