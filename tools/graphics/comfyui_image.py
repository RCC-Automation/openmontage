"""ComfyUI image generation via a local or remote ComfyUI server.

Default workflow: FLUX 2 Dev (NVFP4) with Mistral text encoder.
Supports custom workflows via the ``workflow_json`` input.
"""

from __future__ import annotations

import json
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
from tools._comfyui.profiles import (
    WorkflowProfileError,
    apply_workflow_bindings,
    load_workflow_profile,
    parse_workflow_profile_json,
)

_WORKFLOWS = Path(__file__).resolve().parent.parent / "_comfyui" / "workflows"

# Models required by the bundled flux2-txt2img workflow
_REQUIRED_MODELS = [
    "flux2-dev-nvfp4.safetensors",
    "mistral_3_small_flux2_fp4_mixed.safetensors",
    "flux2-vae.safetensors",
]


class ComfyUIImage(BaseTool):
    name = "comfyui_image"
    version = "0.1.0"
    tier = ToolTier.GENERATE
    capability = "image_generation"
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
        "See https://github.com/comfyanonymous/ComfyUI for setup.\n"
        "Running a separate ComfyUI instance for images? Set COMFYUI_IMAGE_SERVER_URL "
        "instead -- it takes priority over COMFYUI_SERVER_URL for this tool only."
    )
    agent_skills = ["comfyui", "flux-best-practices"]

    capabilities = ["text_to_image"]
    supports = {
        "seed": True,
        "custom_size": True,
        "custom_workflow": True,
        "custom_workflow_profile": True,
        "custom_output_node": True,
        "offline": True,
    }
    best_for = [
        "local GPU generation without API costs",
        "Blackwell / DGX Spark hardware where diffusers is unsupported",
        "full control over sampling via custom ComfyUI workflows",
    ]
    not_good_for = [
        "setups without a running ComfyUI server",
        "CPU-only machines",
    ]
    fallback = "flux_image"
    fallback_tools = ["flux_image", "local_diffusion", "openai_image"]

    input_schema = {
        "type": "object",
        "required": ["prompt"],
        "properties": {
            "prompt": {"type": "string", "description": "Text prompt for image generation"},
            "width": {"type": "integer", "default": 1024},
            "height": {"type": "integer", "default": 1024},
            "steps": {"type": "integer", "default": 20},
            "guidance": {"type": "number", "default": 3.5},
            "seed": {"type": "integer", "description": "Random if omitted"},
            "output_path": {"type": "string", "description": "Where to save the image"},
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
            "workflow_profile_json": {
                "type": "string",
                "description": "Inline OpenMontage binding profile for a custom workflow.",
            },
            "workflow_profile_path": {
                "type": "string",
                "description": "Path to an OpenMontage binding profile for a custom workflow.",
            },
            "negative_prompt": {
                "type": "string",
                "description": "Optional negative prompt when declared by the workflow profile.",
            },
            "filename_prefix": {
                "type": "string",
                "description": "Optional ComfyUI filename prefix when declared by the profile.",
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
                    "Items should include name, role, quantization, and LoRA strengths when known."
                ),
                "items": {"type": "object"},
            },
        },
    }

    resource_profile = ResourceProfile(
        cpu_cores=2, ram_mb=8000, vram_mb=8000, disk_mb=500, network_required=False,
    )
    retry_policy = RetryPolicy(max_retries=1, retryable_errors=["timeout"])
    idempotency_key_fields = ["prompt", "width", "height", "steps", "seed"]
    side_effects = ["writes image file to output_path"]
    user_visible_verification = ["Inspect generated image for quality and prompt adherence"]

    def __init__(self) -> None:
        self._client = ComfyUIClient(capability="image")

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
        return float(inputs.get("steps", 20)) * 1.5

    def get_info(self) -> dict[str, Any]:
        info = super().get_info()
        info["setup_offer"] = self.setup_offer
        info["bundled_model_stack"] = BUNDLED_MODEL_STACKS["flux2-txt2img"]
        return info

    def execute(self, inputs: dict[str, Any]) -> ToolResult:
        custom_workflow = bool(inputs.get("workflow_json") or inputs.get("workflow_path"))
        try:
            workflow_profile = self._load_workflow_profile(inputs)
        except WorkflowProfileError as exc:
            return ToolResult(success=False, error=str(exc))

        if workflow_profile and not custom_workflow:
            return ToolResult(
                success=False,
                error=(
                    "workflow_profile_json/workflow_profile_path requires a custom "
                    "workflow_json or workflow_path."
                ),
            )
        if custom_workflow and not inputs.get("output_node") and not workflow_profile:
            return ToolResult(
                success=False,
                error=(
                    "Custom ComfyUI workflows require output_node so OpenMontage "
                    "knows which ComfyUI node to download artifacts from."
                ),
            )

        if not self._client.is_available():
            return ToolResult(
                success=False,
                error=self._client.unavailable_reason(),
            )

        if not custom_workflow:
            _, missing = self._client.check_models(_REQUIRED_MODELS)
            if missing:
                return ToolResult(
                    success=False,
                    data=missing_models_payload(
                        missing,
                        workflow_key="flux2-txt2img",
                        workflow_name="flux2-txt2img.json",
                    ),
                    error=(
                        f"ComfyUI server is running but missing required models: "
                        f"{', '.join(missing)}.\n"
                        f"See data.missing_models for destination hints and download URLs."
                    ),
                )

        start = time.time()
        seed = (
            inputs["seed"]
            if inputs.get("seed") is not None
            else ComfyUIClient.random_seed()
        )
        width = inputs.get("width", 1024)
        height = inputs.get("height", 1024)
        steps = inputs.get("steps", 20)
        guidance = inputs.get("guidance", 3.5)
        output_path = Path(inputs.get("output_path", f"comfyui_image_{seed}.png"))
        applied_profile_values: dict[str, Any] = {}

        try:
            if custom_workflow:
                workflow = self._load_custom_workflow(inputs)
                if workflow_profile:
                    profile_values = self._workflow_profile_values(
                        inputs, seed, workflow_profile
                    )
                    if "filename_prefix" in workflow_profile["bindings"]:
                        profile_values["filename_prefix"] = inputs.get(
                            "filename_prefix", f"image/{output_path.stem}"
                        )
                    workflow = apply_workflow_bindings(
                        workflow, workflow_profile, profile_values
                    )
                    applied_profile_values = profile_values
                output_node = str(
                    inputs.get("output_node") or workflow_profile["output_node"]
                )
            else:
                workflow = ComfyUIClient.load_workflow(_WORKFLOWS / "flux2-txt2img.json")
                workflow = ComfyUIClient.patch_workflow(workflow, {
                    "4": {"text": inputs["prompt"]},
                    "5": {"guidance": guidance},
                    "6": {"width": width, "height": height, "batch_size": 1},
                    "7": {"noise_seed": seed},
                    "10": {"steps": steps, "width": width, "height": height},
                    "13": {"filename_prefix": output_path.stem},
                })
                output_node = "13"

            provenance = self._workflow_provenance(
                inputs,
                custom_workflow,
                output_node,
                workflow,
                workflow_profile,
                applied_profile_values,
            )
            paths = self._client.generate(
                workflow, output_node=output_node, dest=output_path, timeout=600,
            )

        except ComfyUIError as exc:
            return ToolResult(success=False, error=str(exc))
        except Exception as exc:
            return ToolResult(success=False, error=f"ComfyUI image generation failed: {exc}")

        model_name = self._model_name(inputs, custom_workflow)
        return ToolResult(
            success=True,
            data={
                "provider": "comfyui",
                "model": model_name,
                "prompt": inputs["prompt"],
                "width": width,
                "height": height,
                "steps": steps,
                "guidance": guidance,
                "output": str(paths[0]),
                "format": paths[0].suffix.lower().lstrip(".") or output_path.suffix.lower().lstrip("."),
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
    def _load_workflow_profile(
        inputs: dict[str, Any],
    ) -> dict[str, Any] | None:
        inline = inputs.get("workflow_profile_json")
        path = inputs.get("workflow_profile_path")
        if inline and path:
            raise WorkflowProfileError(
                "Provide only one of workflow_profile_json or workflow_profile_path"
            )
        if inline:
            return parse_workflow_profile_json(inline)
        if path:
            return load_workflow_profile(Path(path))
        return None

    @staticmethod
    def _workflow_profile_values(
        inputs: dict[str, Any],
        seed: int,
        workflow_profile: dict[str, Any],
    ) -> dict[str, Any]:
        values: dict[str, Any] = {
            "prompt": inputs["prompt"],
            "seed": seed,
        }
        for name in (
            "negative_prompt",
            "width",
            "height",
            "steps",
            "guidance",
        ):
            if name in inputs:
                values[name] = inputs[name]
        declared_bindings = workflow_profile["bindings"]
        return {
            name: value
            for name, value in values.items()
            if name in declared_bindings
        }

    @staticmethod
    def _model_name(inputs: dict[str, Any], custom_workflow: bool) -> str:
        if not custom_workflow:
            return "flux2-dev-nvfp4"
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
        workflow_profile: dict[str, Any] | None = None,
        applied_profile_values: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        if not custom_workflow:
            return {
                "source": "bundled",
                "workflow": "flux2-txt2img.json",
                "workflow_hash_sha256": workflow_hash(workflow),
                "model_stack": model_stack("flux2-txt2img", inputs),
                "output_node": output_node,
            }
        provenance = {
            "source": "user_supplied",
            "workflow_name": inputs.get("workflow_name"),
            "workflow_path": inputs.get("workflow_path"),
            "model": inputs.get("workflow_model") or inputs.get("model"),
            "workflow_hash_sha256": workflow_hash(workflow),
            "model_stack": model_stack(None, inputs),
            "model_stack_source": (
                "caller_supplied"
                if inputs.get("workflow_model_stack")
                else "unknown_custom_workflow"
            ),
            "output_node": output_node,
        }
        if workflow_profile:
            provenance["workflow_profile"] = {
                "name": workflow_profile["name"],
                "version": workflow_profile["version"],
                "path": inputs.get("workflow_profile_path"),
                "source": "path" if inputs.get("workflow_profile_path") else "inline",
                "profile_hash_sha256": workflow_hash(workflow_profile),
                "declared_bindings": sorted(workflow_profile["bindings"]),
                "applied_bindings": dict(applied_profile_values or {}),
            }
        return provenance
