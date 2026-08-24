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
    infer_model_stack,
    workflow_hash,
)
from tools._comfyui.vrgdg import VRGDGClient, VRGDGError, build_routes_for
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
_JUGGERNAUT_MODELS = ["juggernautXL_ragnarok.safetensors"]
_JUGGERNAUT_WORKFLOW = "juggernaut-xl-ragnarok-txt2img.json"
_JUGGERNAUT_PROFILE = "juggernaut-xl-ragnarok-txt2img.json"
_PROFILES = Path(__file__).resolve().parent.parent / "_comfyui" / "profiles"


def _retarget_checkpoint(
    stack: list[dict[str, Any]], checkpoint_name: str | None
) -> list[dict[str, Any]]:
    """Name the checkpoint that actually rendered, not the one the stack ships.

    The bundled SDXL graph can be pointed at any SDXL file, so a fixed stack
    would record the wrong model - and provenance that names a model the render
    never used is worse than none (DECISIONS.md #7).
    """
    if not checkpoint_name:
        return stack
    retargeted = []
    for entry in stack:
        entry = dict(entry)
        if entry.get("role") == "checkpoint" and entry.get("name") != checkpoint_name:
            entry["name"] = checkpoint_name
            entry.pop("download_url", None)     # the URL was for the shipped file
        retargeted.append(entry)
    return retargeted


class ComfyUIImage(BaseTool):
    name = "comfyui_image"
    version = "0.2.0"
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
        "vrgdg_builder": True,
        "bundled_workflow_variants": True,
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
            "workflow_variant": {
                "type": "string",
                "enum": ["auto", "flux2_dev", "juggernaut_xl_ragnarok"],
                "default": "auto",
                "description": "Bundled workflow to use; auto prefers FLUX 2 when installed.",
            },
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
            "vrgdg_build": {
                "type": "object",
                "description": (
                    "Build the graph with the VRGDG node pack instead of a stored "
                    "workflow. {\"kind\": \"zimage\", \"payload\": {...}} — VRGDG "
                    "patches its own template by node class_type and returns a "
                    "ready-to-queue graph, so no binding profile is needed. "
                    "Mutually exclusive with workflow_json/workflow_path."
                ),
                "properties": {
                    "kind": {
                        "type": "string",
                        "description": "VRGDG image build route, e.g. zimage, krea2, flux_klein.",
                    },
                    "payload": {
                        "type": "object",
                        "description": "Route payload. Model names come from the caller, not the template.",
                    },
                },
                "required": ["kind"],
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
            "sampler_name": {
                "type": "string",
                "description": (
                    "KSampler sampler for the bundled SDXL workflow. Distilled "
                    "checkpoints usually need 'lcm'. Defaults to dpmpp_2m_sde."
                ),
            },
            "scheduler": {
                "type": "string",
                "description": "KSampler scheduler for the bundled SDXL workflow.",
            },
            "checkpoint_name": {
                "type": "string",
                "description": (
                    "SDXL checkpoint filename for the bundled juggernaut_xl_ragnarok "
                    "workflow. Any SDXL checkpoint on the server works; defaults to "
                    "juggernautXL_ragnarok.safetensors."
                ),
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
        _, flux_missing = self._client.check_models(_REQUIRED_MODELS)
        _, juggernaut_missing = self._client.check_models(_JUGGERNAUT_MODELS)
        return (
            ToolStatus.AVAILABLE
            if not flux_missing or not juggernaut_missing
            else ToolStatus.DEGRADED
        )

    def estimate_cost(self, inputs: dict[str, Any]) -> float:
        return 0.0

    def estimate_runtime(self, inputs: dict[str, Any]) -> float:
        return float(inputs.get("steps", 20)) * 1.5

    def get_info(self) -> dict[str, Any]:
        info = super().get_info()
        info["setup_offer"] = self.setup_offer
        info["bundled_model_stack"] = BUNDLED_MODEL_STACKS["flux2-txt2img"]
        info["bundled_workflow_variants"] = {
            "flux2_dev": BUNDLED_MODEL_STACKS["flux2-txt2img"],
            "juggernaut_xl_ragnarok": BUNDLED_MODEL_STACKS["juggernaut-xl-ragnarok-txt2img"],
        }
        info["vrgdg_build_kinds"] = {
            route.kind: route.description for route in build_routes_for("image")
        }
        return info

    def execute(self, inputs: dict[str, Any]) -> ToolResult:
        vrgdg_build = inputs.get("vrgdg_build") or None
        custom_workflow = bool(inputs.get("workflow_json") or inputs.get("workflow_path"))
        vrgdg_graph = None
        applied_recipe: dict[str, Any] = {}
        vrgdg_pack_version = None
        if vrgdg_build is not None:
            if custom_workflow or inputs.get("workflow_profile_json") or inputs.get(
                "workflow_profile_path"
            ):
                return ToolResult(
                    success=False,
                    error=(
                        "vrgdg_build supplies the graph itself, so it cannot be combined "
                        "with workflow_json/workflow_path or a workflow profile."
                    ),
                )
            if not isinstance(vrgdg_build, dict) or not vrgdg_build.get("kind"):
                return ToolResult(
                    success=False,
                    error='vrgdg_build requires a "kind", e.g. {"kind": "zimage", "payload": {...}}',
                )
        bundled_variant = (
            None
            if custom_workflow or inputs.get("vrgdg_build")
            else self._resolve_bundled_variant(inputs)
        )
        # The bundled SDXL graph loads whatever checkpoint it is pointed at, so
        # any SDXL file on the machine can be rendered through it. Defaults to
        # the one the workflow ships with.
        checkpoint_name = str(
            inputs.get("checkpoint_name") or _JUGGERNAUT_MODELS[0]
        )
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

        if not custom_workflow and vrgdg_build is None:
            required_models = (
                [checkpoint_name]
                if bundled_variant == "juggernaut_xl_ragnarok"
                else _REQUIRED_MODELS
            )
            _, missing = self._client.check_models(required_models)
            if missing:
                workflow_key = (
                    "juggernaut-xl-ragnarok-txt2img"
                    if bundled_variant == "juggernaut_xl_ragnarok"
                    else "flux2-txt2img"
                )
                workflow_name = (
                    _JUGGERNAUT_WORKFLOW
                    if bundled_variant == "juggernaut_xl_ragnarok"
                    else "flux2-txt2img.json"
                )
                return ToolResult(
                    success=False,
                    data=missing_models_payload(
                        missing,
                        workflow_key=workflow_key,
                        workflow_name=workflow_name,
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
        is_juggernaut = bundled_variant == "juggernaut_xl_ragnarok"
        width = inputs.get("width", 832 if is_juggernaut else 1024)
        height = inputs.get("height", 1216 if is_juggernaut else 1024)
        steps = inputs.get("steps", 35 if is_juggernaut else 20)
        guidance = inputs.get("guidance", 4.5 if is_juggernaut else 3.5)
        output_path = Path(inputs.get("output_path", f"comfyui_image_{seed}.png"))
        applied_profile_values: dict[str, Any] = {}

        try:
            if vrgdg_build is not None:
                vrgdg_client = VRGDGClient()
                if not vrgdg_client.is_available():
                    return ToolResult(
                        success=False, error=vrgdg_client.unavailable_reason()
                    )
                payload = dict(vrgdg_build.get("payload") or {})
                payload.setdefault("prompt", inputs["prompt"])
                payload.setdefault("seed", seed)
                vrgdg_graph = vrgdg_client.build(str(vrgdg_build["kind"]), payload)
                # The build routes patch model names but ignore sampler keys, so
                # a checkpoint's own settings have to be edited into the graph
                # they return. Matched on class_type, never node id.
                recipe = vrgdg_build.get("sampler_recipe") or {}
                applied_recipe = (
                    vrgdg_graph.apply_sampler_recipe(recipe) if recipe else {}
                )
                vrgdg_pack_version = vrgdg_client.pack_version()
                output_node = str(
                    inputs.get("output_node") or vrgdg_graph.output_node(prefer="image")
                )
                # VRGDG templates hang deliberate side-effect nodes (RAM/VRAM
                # cleanup, preview branches) off the graph. Those are the
                # author's intent, so submit the graph as built and only prune
                # when an uninstalled node would otherwise fail validation - and
                # then only the parts the output does not depend on.
                missing_nodes = vrgdg_client.missing_node_types(vrgdg_graph.prompt)
                if missing_nodes:
                    vrgdg_graph.prune(output_node)
                    missing_nodes = vrgdg_client.missing_node_types(vrgdg_graph.prompt)
                if missing_nodes:
                    return ToolResult(
                        success=False,
                        data={"missing_node_types": missing_nodes},
                        error=(
                            "The VRGDG graph needs custom nodes this ComfyUI server "
                            "does not have, on branches the output depends on: "
                            + "; ".join(
                                f"{cls} (node {', '.join(ids)})"
                                for cls, ids in sorted(missing_nodes.items())
                            )
                            + ". Install the packs that provide them through ComfyUI "
                            "Manager and restart ComfyUI."
                        ),
                    )
                workflow = vrgdg_graph.prompt
                if vrgdg_graph.used_seed is not None:
                    seed = vrgdg_graph.used_seed
            elif custom_workflow:
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
            elif bundled_variant == "juggernaut_xl_ragnarok":
                workflow = ComfyUIClient.load_workflow(_WORKFLOWS / _JUGGERNAUT_WORKFLOW)
                bundled_profile = load_workflow_profile(_PROFILES / _JUGGERNAUT_PROFILE)
                applied_profile_values = {
                    "checkpoint_name": checkpoint_name,
                    # Distilled checkpoints (DMD/LCM/Turbo) need their own
                    # sampler; the shipped dpmpp_2m_sde posterises them even at
                    # the right CFG. Many carry the author's settings in their
                    # own metadata - see infer_sampler_recipe.
                    "sampler_name": str(inputs.get("sampler_name") or "dpmpp_2m_sde"),
                    "scheduler": str(inputs.get("scheduler") or "karras"),
                    "prompt": inputs["prompt"],
                    "negative_prompt": inputs.get("negative_prompt", ""),
                    "width": width,
                    "height": height,
                    "steps": steps,
                    "guidance": guidance,
                    "seed": seed,
                    "filename_prefix": inputs.get(
                        "filename_prefix", f"image/{output_path.stem}"
                    ),
                }
                workflow = apply_workflow_bindings(
                    workflow, bundled_profile, applied_profile_values
                )
                workflow_profile = bundled_profile
                output_node = bundled_profile["output_node"]
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
                custom_workflow or vrgdg_graph is not None,
                output_node,
                workflow,
                workflow_profile,
                applied_profile_values,
                bundled_variant,
            )
            if vrgdg_graph is not None:
                provenance.update(
                    vrgdg_graph.provenance(pack_version=vrgdg_pack_version)
                )
                if applied_recipe:
                    # The submitted graph no longer matches the template, so the
                    # record has to say how it differs.
                    provenance["sampler_recipe_applied"] = applied_recipe
            paths = self._client.generate(
                workflow, output_node=output_node, dest=output_path, timeout=600,
            )

        except VRGDGError as exc:
            return ToolResult(success=False, error=f"VRGDG graph build failed: {exc}")
        except ComfyUIError as exc:
            return ToolResult(success=False, error=str(exc))
        except Exception as exc:
            return ToolResult(success=False, error=f"ComfyUI image generation failed: {exc}")

        model_name = self._model_name(
            inputs, custom_workflow or vrgdg_graph is not None, bundled_variant
        )
        if vrgdg_graph is not None and model_name == "custom-comfyui-workflow":
            model_name = f"vrgdg-{vrgdg_graph.kind}"
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
    def _model_name(
        inputs: dict[str, Any], custom_workflow: bool, bundled_variant: str | None = None
    ) -> str:
        if not custom_workflow:
            return (
                "juggernaut-xl-ragnarok"
                if bundled_variant == "juggernaut_xl_ragnarok"
                else "flux2-dev-nvfp4"
            )
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
        bundled_variant: str | None = None,
    ) -> dict[str, Any]:
        if not custom_workflow:
            if bundled_variant == "juggernaut_xl_ragnarok":
                return {
                    "source": "bundled",
                    "workflow": _JUGGERNAUT_WORKFLOW,
                    "workflow_hash_sha256": workflow_hash(workflow),
                    "model_stack": _retarget_checkpoint(
                        model_stack("juggernaut-xl-ragnarok-txt2img", inputs),
                        (applied_profile_values or {}).get("checkpoint_name"),
                    ),
                    "output_node": output_node,
                    "workflow_profile": _JUGGERNAUT_PROFILE,
                    "applied_bindings": dict(applied_profile_values or {}),
                }
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
            "model_stack": (
                model_stack(None, inputs)
                if inputs.get("workflow_model_stack")
                else infer_model_stack(workflow)
            ),
            "model_stack_source": (
                "caller_supplied"
                if inputs.get("workflow_model_stack")
                else "inferred_from_workflow"
                if infer_model_stack(workflow)
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

    def _resolve_bundled_variant(self, inputs: dict[str, Any]) -> str:
        requested = str(inputs.get("workflow_variant", "auto"))
        if requested != "auto":
            return requested
        _, flux_missing = self._client.check_models(_REQUIRED_MODELS)
        if not flux_missing:
            return "flux2_dev"
        _, juggernaut_missing = self._client.check_models(_JUGGERNAUT_MODELS)
        if not juggernaut_missing:
            return "juggernaut_xl_ragnarok"
        return "flux2_dev"
