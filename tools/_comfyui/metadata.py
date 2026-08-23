"""Shared metadata helpers for ComfyUI provider tools."""

from __future__ import annotations

import hashlib
import json
from typing import Any


COMFYUI_SETUP_OFFER: dict[str, Any] = {
    "kind": "local_server",
    "fix_complexity": "1-minute env-var if ComfyUI is already running; otherwise local install",
    "env_var": "COMFYUI_SERVER_URL",
    "default_url": "http://localhost:8188",
    "health_check": "GET /system_stats",
    "what_it_unlocks": [
        "free local image generation through ComfyUI workflows",
        "free local video generation through ComfyUI workflows",
        "community workflow_json/workflow_path execution",
    ],
    # Optional: point image/video generation at separate ComfyUI instances
    # (e.g. different GPUs). Each overrides COMFYUI_SERVER_URL for its own
    # tool only; single-server setups can ignore this entirely.
    "per_capability_env_var_overrides": {
        "comfyui_image": "COMFYUI_IMAGE_SERVER_URL",
        "comfyui_video": "COMFYUI_VIDEO_SERVER_URL",
        "comfyui_music": "COMFYUI_MUSIC_SERVER_URL",
    },
}


BUNDLED_MODEL_STACKS: dict[str, list[dict[str, Any]]] = {
    "minimax-h3-local": [
        {
            "role": "diffusion_model",
            "name": "minimax_h3_fl2va_pruned_int8_convrot.safetensors",
            "quantization": "INT8 ConvRot",
            "destination_hint": "ComfyUI/models/diffusion_models/",
            "download_url": "https://huggingface.co/Comfy-Org/MiniMax-H3/tree/main/diffusion_models",
        },
        {
            "role": "text_encoder",
            "name": "qwen3vl_32b_minimax_h3_nvfp4_awq.safetensors",
            "quantization": "NVFP4 AWQ",
            "destination_hint": "ComfyUI/models/text_encoders/",
            "download_url": "https://huggingface.co/Comfy-Org/MiniMax-H3/tree/main/text_encoders",
        },
        {
            "role": "video_vae",
            "name": "minimax_h3_video_vae_fp16.safetensors",
            "destination_hint": "ComfyUI/models/vae/",
            "download_url": "https://huggingface.co/Comfy-Org/MiniMax-H3/tree/main/vae",
        },
        {
            "role": "audio_vae",
            "name": "minimax_h3_audio_vae_fp32.safetensors",
            "destination_hint": "ComfyUI/models/vae/",
            "download_url": "https://huggingface.co/Comfy-Org/MiniMax-H3/tree/main/vae",
        },
    ],
    "flux2-txt2img": [
        {
            "role": "diffusion_model",
            "name": "flux2-dev-nvfp4.safetensors",
            "quantization": "NVFP4",
            "destination_hint": "ComfyUI/models/diffusion_models/",
            "download_url": (
                "https://huggingface.co/black-forest-labs/FLUX.2-dev-NVFP4"
            ),
        },
        {
            "role": "text_encoder",
            "name": "mistral_3_small_flux2_fp4_mixed.safetensors",
            "quantization": "FP4 mixed",
            "destination_hint": "ComfyUI/models/text_encoders/",
            "download_url": (
                "https://huggingface.co/Comfy-Org/flux2-dev/tree/main/"
                "split_files/text_encoders"
            ),
        },
        {
            "role": "vae",
            "name": "flux2-vae.safetensors",
            "destination_hint": "ComfyUI/models/vae/",
            "download_url": (
                "https://huggingface.co/Comfy-Org/flux2-dev/blob/main/"
                "split_files/vae/flux2-vae.safetensors"
            ),
        },
    ],
    "juggernaut-xl-ragnarok-txt2img": [
        {
            "role": "checkpoint",
            "name": "juggernautXL_ragnarok.safetensors",
            "architecture": "SDXL 1.0",
            "destination_hint": "ComfyUI/models/checkpoints/",
            "download_url": "https://civitai.com/models/133005/juggernaut-xl",
        },
    ],
    "wan22-t2v-4step": [
        {
            "role": "text_encoder",
            "name": "umt5_xxl_fp8_e4m3fn_scaled.safetensors",
            "quantization": "FP8",
            "destination_hint": "ComfyUI/models/text_encoders/",
            "download_url": (
                "https://huggingface.co/Comfy-Org/Wan_2.2_ComfyUI_Repackaged/"
                "tree/main/split_files/text_encoders"
            ),
        },
        {
            "role": "diffusion_model_high_noise",
            "name": "wan2.2_t2v_high_noise_14B_fp8_scaled.safetensors",
            "quantization": "FP8",
            "destination_hint": "ComfyUI/models/diffusion_models/",
            "download_url": (
                "https://huggingface.co/Comfy-Org/Wan_2.2_ComfyUI_Repackaged/"
                "blob/main/split_files/diffusion_models/"
                "wan2.2_t2v_high_noise_14B_fp8_scaled.safetensors"
            ),
        },
        {
            "role": "diffusion_model_low_noise",
            "name": "wan2.2_t2v_low_noise_14B_fp8_scaled.safetensors",
            "quantization": "FP8",
            "destination_hint": "ComfyUI/models/diffusion_models/",
            "download_url": (
                "https://huggingface.co/Comfy-Org/Wan_2.2_ComfyUI_Repackaged/"
                "tree/main/split_files/diffusion_models"
            ),
        },
        {
            "role": "vae",
            "name": "wan_2.1_vae.safetensors",
            "destination_hint": "ComfyUI/models/vae/",
            "download_url": (
                "https://huggingface.co/Comfy-Org/Wan_2.1_ComfyUI_repackaged/"
                "tree/main/split_files/vae"
            ),
        },
        {
            "role": "lora",
            "name": "wan2.2_t2v_lightx2v_4steps_lora_v1.1_high_noise.safetensors",
            "strength_model": 1.0,
            "destination_hint": "ComfyUI/models/loras/",
            "download_url": (
                "https://huggingface.co/Comfy-Org/Wan_2.2_ComfyUI_Repackaged/"
                "tree/main/split_files/loras"
            ),
        },
        {
            "role": "lora",
            "name": "wan2.2_t2v_lightx2v_4steps_lora_v1.1_low_noise.safetensors",
            "strength_model": 1.0,
            "destination_hint": "ComfyUI/models/loras/",
            "download_url": (
                "https://huggingface.co/Comfy-Org/Wan_2.2_ComfyUI_Repackaged/"
                "tree/main/split_files/loras"
            ),
        },
    ],
    "wan22-i2v-4step": [
        {
            "role": "text_encoder",
            "name": "umt5_xxl_fp8_e4m3fn_scaled.safetensors",
            "quantization": "FP8",
            "destination_hint": "ComfyUI/models/text_encoders/",
            "download_url": (
                "https://huggingface.co/Comfy-Org/Wan_2.2_ComfyUI_Repackaged/"
                "tree/main/split_files/text_encoders"
            ),
        },
        {
            "role": "diffusion_model_high_noise",
            "name": "wan2.2_i2v_high_noise_14B_fp8_scaled.safetensors",
            "quantization": "FP8",
            "destination_hint": "ComfyUI/models/diffusion_models/",
            "download_url": (
                "https://huggingface.co/Comfy-Org/Wan_2.2_ComfyUI_Repackaged/"
                "blob/main/split_files/diffusion_models/"
                "wan2.2_i2v_high_noise_14B_fp8_scaled.safetensors"
            ),
        },
        {
            "role": "diffusion_model_low_noise",
            "name": "wan2.2_i2v_low_noise_14B_fp8_scaled.safetensors",
            "quantization": "FP8",
            "destination_hint": "ComfyUI/models/diffusion_models/",
            "download_url": (
                "https://huggingface.co/Comfy-Org/Wan_2.2_ComfyUI_Repackaged/"
                "tree/main/split_files/diffusion_models"
            ),
        },
        {
            "role": "vae",
            "name": "wan_2.1_vae.safetensors",
            "destination_hint": "ComfyUI/models/vae/",
            "download_url": (
                "https://huggingface.co/Comfy-Org/Wan_2.1_ComfyUI_repackaged/"
                "tree/main/split_files/vae"
            ),
        },
        {
            "role": "lora",
            "name": "wan2.2_i2v_lightx2v_4steps_lora_v1_high_noise.safetensors",
            "strength_model": 1.0,
            "destination_hint": "ComfyUI/models/loras/",
            "download_url": (
                "https://huggingface.co/Comfy-Org/Wan_2.2_ComfyUI_Repackaged/"
                "tree/main/split_files/loras"
            ),
        },
        {
            "role": "lora",
            "name": "wan2.2_i2v_lightx2v_4steps_lora_v1_low_noise.safetensors",
            "strength_model": 1.0,
            "destination_hint": "ComfyUI/models/loras/",
            "download_url": (
                "https://huggingface.co/Comfy-Org/Wan_2.2_ComfyUI_Repackaged/"
                "tree/main/split_files/loras"
            ),
        },
    ],
    "ace-step-1-t2a": [
        {
            "role": "checkpoint",
            "name": "ace_step_v1_3.5b.safetensors",
            "destination_hint": "ComfyUI/models/checkpoints/",
            "download_url": (
                "https://huggingface.co/Comfy-Org/ACE-Step_ComfyUI_repackaged/"
                "blob/main/all_in_one/ace_step_v1_3.5b.safetensors"
            ),
        },
    ],
    "ace-step-1.5-turbo-aio-t2a": [
        {
            "role": "checkpoint",
            "name": "ace_step_1.5_turbo_aio.safetensors",
            "destination_hint": "ComfyUI/models/checkpoints/",
            "download_url": (
                "https://huggingface.co/Comfy-Org/ace_step_1.5_ComfyUI_files/"
                "resolve/main/all_in_one/ace_step_1.5_turbo_aio.safetensors"
            ),
        },
    ],
}


def workflow_hash(workflow: dict[str, Any]) -> str:
    """Return a stable hash of the final workflow JSON submitted to ComfyUI."""
    payload = json.dumps(workflow, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def model_stack(
    workflow_key: str | None, inputs: dict[str, Any]
) -> list[dict[str, Any]]:
    """Return bundled or caller-supplied model stack metadata."""
    if workflow_key:
        return [dict(item) for item in BUNDLED_MODEL_STACKS[workflow_key]]
    stack = inputs.get("workflow_model_stack")
    return stack if isinstance(stack, list) else []


def infer_model_stack(workflow: dict[str, Any]) -> list[dict[str, Any]]:
    """Infer loader assets from a graph, for custom-workflow provenance.

    Walks every node's inputs for the well-known loader field names and records
    what was actually loaded. Used when the caller supplies no explicit
    workflow_model_stack, which is the normal case for a graph built by VRGDG.
    """

    roles = {
        "unet_name": "diffusion_model",
        "ckpt_name": "checkpoint",
        "clip_name": "text_encoder",
        "clip_name1": "text_encoder",
        "clip_name2": "text_encoder",
        "vae_name": "vae",
        "lora_name": "lora",
        "model_name": "upscale_model",
    }
    lora_slots = {f"lora_{index}": "lora" for index in range(1, 9)}
    roles.update(lora_slots)

    stack: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for node_id, node in workflow.items():
        node_inputs = node.get("inputs", {}) if isinstance(node, dict) else {}
        if not isinstance(node_inputs, dict):
            continue
        for input_name, role in roles.items():
            asset_name = node_inputs.get(input_name)
            if not isinstance(asset_name, str) or not asset_name:
                continue
            # VRGDG uses these sentinels for an unfilled optional LoRA slot.
            if asset_name.strip().lower() in {"[none]", "none", "null"}:
                continue
            key = (role, asset_name)
            if key in seen:
                continue
            seen.add(key)
            item: dict[str, Any] = {
                "role": role,
                "name": asset_name,
                "node": str(node_id),
            }
            if role == "lora":
                suffix = input_name.split("_")[-1]
                for strength in (
                    "strength_model",
                    "strength_clip",
                    f"strength_{suffix}",
                    f"first_pass_strength_{suffix}",
                    f"second_pass_strength_{suffix}",
                ):
                    if strength in node_inputs:
                        item[strength] = node_inputs[strength]
            stack.append(item)
    return stack


def missing_models_payload(
    missing: list[str],
    *,
    workflow_key: str,
    workflow_name: str,
    operation: str | None = None,
) -> dict[str, Any]:
    """Build a machine-readable missing-model error payload."""
    stack_by_name = {
        item["name"]: item for item in BUNDLED_MODEL_STACKS.get(workflow_key, [])
    }
    items = []
    for name in missing:
        meta = dict(stack_by_name.get(name, {}))
        meta.setdefault("name", name)
        meta.setdefault("role", "unknown")
        meta.setdefault(
            "destination_hint", "ComfyUI/models/ matching the workflow node"
        )
        meta.setdefault("download_url", None)
        items.append(meta)

    return {
        "provider": "comfyui",
        "workflow": workflow_name,
        "operation": operation,
        "missing_models": items,
        "setup_offer": COMFYUI_SETUP_OFFER,
    }
