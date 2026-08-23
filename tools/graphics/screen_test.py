"""Run a screen test: cast a look by measured comparison.

Generates one character brief across a matrix of models, LoRAs and settings, in
the conditions the film will use, then ranks the stacks and hands a shortlist to
the human. It never picks the winner - see `lib/screen_test` for why that line
is drawn there.

Budget-aware by construction. A sweep is the one thing on a local machine that
can quietly consume a whole evening, so the plan is costed against measured
history before a single image is generated, and the run stops when the budget is
gone rather than when the matrix ends.
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
from tools._comfyui.vrgdg import VRGDGClient
from lib.model_registry import (
    DRIVERS,
    ModelRegistry,
    default_ledger_path,
    default_models_root,
    resolve_driver,
)
from lib.render_clock import (
    PlanItem,
    RenderBudget,
    RenderTimings,
    check_budget,
    estimate_plan,
    route_key,
)
from lib.screen_test import (
    PRESETS,
    CandidateResult,
    ScreenTestError,
    Shot,
    apply_preset,
    build_prompt,
    comparison_sheet,
    condition_id,
    contact_sheet,
    expand_matrix,
    resolve_conditions,
    score_candidates,
    shortlist,
    slugify,
    write_report,
)


def _route_for(driver: dict[str, Any]) -> str:
    """Timing key for a driver. Families time differently, so they learn apart."""
    if driver["graph_source"] == "vrgdg_build":
        return route_key("comfyui_image", "vrgdg", str(driver["kind"]))
    return route_key("comfyui_image", "bundled", str(driver["workflow"]))


def _render_request(
    driver: dict[str, Any],
    *,
    candidate: Any,
    prompt: str,
    seed: int,
    settings: dict[str, Any],
    inputs: dict[str, Any],
    output_path: Path,
) -> dict[str, Any]:
    """Build the ComfyUIImage call for one candidate on its own graph source."""
    if driver["graph_source"] == "vrgdg_build":
        payload = {
            **settings,
            "unet_name": candidate.model,
            # The registry knows each family's encoder and VAE; an explicit
            # input still wins, because the Builder's saved defaults are the
            # only record of what actually works on this machine.
            "clip_name": inputs.get("clip_name") or driver.get("clip_name", ""),
            "vae_name": inputs.get("vae_name") or driver.get("vae_name", ""),
            "seed": seed,
            "seed_mode": "fixed",
        }
        if candidate.loras:
            payload["use_custom_loras"] = True
            payload["lora_count"] = len(candidate.loras)
            for slot, (name, strength) in enumerate(candidate.loras, start=1):
                payload[f"lora_{slot}"] = name
                payload[f"strength_{slot}"] = strength
                payload[f"first_pass_strength_{slot}"] = strength
                payload[f"second_pass_strength_{slot}"] = strength
        return {
            "prompt": prompt,
            "vrgdg_build": {"kind": driver["kind"], "payload": payload},
            "output_path": str(output_path),
        }

    # Bundled workflow: the checkpoint carries its own encoder and VAE, so the
    # only thing that varies between candidates is which file gets loaded.
    return {
        "prompt": prompt,
        "workflow_variant": "juggernaut_xl_ragnarok",
        "checkpoint_name": candidate.model,
        "seed": seed,
        "output_path": str(output_path),
    }


class ScreenTest(BaseTool):
    name = "screen_test"
    version = "0.1.0"
    tier = ToolTier.GENERATE
    capability = "casting"
    provider = "vrgdg"
    stability = ToolStability.EXPERIMENTAL
    execution_mode = ExecutionMode.SYNC
    determinism = Determinism.SEEDED
    runtime = ToolRuntime.LOCAL_GPU

    dependencies = []
    install_instructions = (
        "Needs ComfyUI running with the comfyui-vrgamedevgirl pack. Identity "
        "stability and prompt adherence additionally need torch and transformers "
        "for CLIP; without them the run still works and scores on the remaining axes."
    )
    agent_skills = ["comfyui"]

    capabilities = ["screen_test", "model_comparison", "casting"]
    supports = {
        "quick_model_comparison": True,
        "identity_stability": True,
        "budget_aware": True,
        "contact_sheet": True,
        "picks_a_winner": False,
    }
    best_for = [
        "choosing which local model and LoRA stack to cast a character with",
        "measuring whether a stack holds one identity across seeds",
        "comparing installed models on the same brief under the same conditions",
    ]
    not_good_for = [
        "judging whether a face is right for the part - that is the human's job",
        "video models, where each sample costs 25x an image",
    ]

    input_schema = {
        "type": "object",
        "required": ["project_dir", "character", "brief", "matrix"],
        "properties": {
            "project_dir": {
                "type": "string",
                "description": "OpenMontage project directory, i.e. projects/<project-id>.",
            },
            "character": {"type": "string", "description": "Name of the character being cast."},
            "brief": {
                "type": "string",
                "description": (
                    "What the character looks like. Held identical across every "
                    "candidate - only the stack varies."
                ),
            },
            "matrix": {
                "type": "object",
                "description": (
                    "What to vary. {models: [...], lora_sets: [[...], ...], settings: {...}}. "
                    "lora_sets is a list of LoRA *combinations*, so [[], [[\"a\", 0.6]]] "
                    "tests no-LoRA against a-at-0.6."
                ),
                "properties": {
                    "models": {"type": "array", "items": {"type": "string"}},
                    "lora_sets": {"type": "array"},
                    "settings": {"type": "object"},
                    "conditions": {"type": "array"},
                },
                "required": ["models"],
            },
            "preset": {
                "type": "string",
                "enum": ["quick", "shortlist", "full"],
                "default": "shortlist",
                "description": (
                    "Three rungs of one ladder. quick: one close-up per model on a "
                    "single shared seed - a direct look comparison in minutes, but it "
                    "cannot measure identity stability. shortlist: one condition, 3 "
                    "seeds - adds stability, narrows the field. full: 3 conditions x 3 "
                    "seeds - the real screen test. Explicit seeds or conditions "
                    "override the preset."
                ),
            },
            "seeds": {
                "type": "array",
                "items": {"type": "integer"},
                "description": (
                    "Overrides the preset's seeds. A single seed cannot measure "
                    "identity stability, which only the quick preset accepts."
                ),
            },
            "budget_minutes": {
                "type": "number",
                "description": (
                    "GPU-minutes this sweep may use. The plan is costed first and "
                    "refused if it does not fit; the run also stops when the budget "
                    "is spent."
                ),
            },
            "registry_path": {
                "type": "string",
                "description": "Model registry ledger. Defaults to var/model_registry.json.",
            },
            "models_root": {
                "type": "string",
                "description": "ComfyUI shared model tree the registry scans.",
            },
            "timings_path": {
                "type": "string",
                "description": "Render-clock history file. Defaults to the shared one.",
            },
            "clip_name": {"type": "string", "description": "Text encoder for every candidate."},
            "vae_name": {"type": "string", "description": "VAE for every candidate."},
            "kind": {
                "type": "string",
                "default": "zimage",
                "description": "VRGDG image build route used for every candidate.",
            },
            "dry_run": {
                "type": "boolean",
                "default": False,
                "description": "Cost the plan and return it without generating anything.",
            },
            "shortlist_size": {"type": "integer", "default": 8},
        },
    }

    resource_profile = ResourceProfile(
        cpu_cores=2, ram_mb=8000, vram_mb=8000, disk_mb=4000, network_required=False
    )
    retry_policy = RetryPolicy(max_retries=0, retryable_errors=[])
    idempotency_key_fields = ["project_dir", "character", "brief"]
    side_effects = [
        "generates images into <project_dir>/casting/<character>/",
        "writes casting_report.json and contact_sheet.png",
        "records render durations to the machine timing history",
    ]
    user_visible_verification = [
        "Open the contact sheet and choose the cast yourself - the ranking only eliminates",
        "Check the identity_stability column before the prettiness of any single frame",
    ]

    def __init__(self) -> None:
        self._client = VRGDGClient()

    def get_status(self) -> ToolStatus:
        return ToolStatus.AVAILABLE if self._client.is_available() else ToolStatus.UNAVAILABLE

    def get_info(self) -> dict[str, Any]:
        info = super().get_info()
        info["decides"] = "nothing - ranks and eliminates, the human casts"
        info["primary_metric"] = "identity_stability across seeds"
        return info

    def estimate_cost(self, inputs: dict[str, Any]) -> float:
        return 0.0

    def estimate_runtime(self, inputs: dict[str, Any]) -> float:
        try:
            plan = self._plan(inputs)[0]
        except Exception:
            return 0.0
        return estimate_plan(RenderTimings.load(), plan).total_minutes * 60.0

    # ------------------------------------------------------------------

    def _plan(self, inputs: dict[str, Any]):
        candidates = expand_matrix(inputs["matrix"])
        conditions, seeds, settings, preset = apply_preset(
            str(inputs.get("preset", "shortlist")),
            inputs["matrix"],
            inputs.get("seeds"),
        )
        pixels = int(settings.get("second_pass_width", 1920)) * int(
            settings.get("second_pass_height", 1080)
        )
        # An SDXL checkpoint and a Z-Image UNet do not cost the same, so each
        # candidate is estimated against the route that will actually run it.
        registry = ModelRegistry.load(
            inputs.get("models_root") or default_models_root(),
            inputs.get("registry_path") or default_ledger_path(),
        )
        default_key = route_key(
            "comfyui_image", "vrgdg", str(inputs.get("kind", "zimage"))
        )
        plan = []
        for c in candidates:
            ledger_key = registry.key_for_basename(c.model)
            driver = registry.driver_for(ledger_key) if ledger_key else None
            plan.append(
                PlanItem(
                    label=c.label,
                    route_key=_route_for(driver) if driver else default_key,
                    count=len(conditions) * len(seeds),
                    pixels=pixels,
                )
            )
        return plan, candidates, conditions, seeds, settings, preset

    def execute(self, inputs: dict[str, Any]) -> ToolResult:
        started = time.time()
        project_dir = Path(inputs["project_dir"])
        if not project_dir.is_dir():
            return ToolResult(
                success=False,
                error=(
                    f"OpenMontage project directory does not exist: {project_dir}. "
                    f"Create it with lib.checkpoint.init_project first."
                ),
            )

        try:
            plan, candidates, conditions, seeds, settings, preset = self._plan(inputs)
        except ScreenTestError as exc:
            return ToolResult(success=False, error=str(exc))

        skip = list(preset.get("cannot_measure") or [])
        # Only the quick preset is allowed to run on a single seed, and it says
        # in its own output what that costs.
        if len(seeds) < 3 and "identity_stability" not in skip:
            return ToolResult(
                success=False,
                error=(
                    f"{len(seeds)} seed(s) cannot measure identity stability, which is "
                    f"the point of this preset. Use at least 3 seeds, or preset='quick' "
                    f"for a look comparison that does not claim to measure it."
                ),
            )

        timings_path = inputs.get("timings_path")
        timings = RenderTimings.load(timings_path)
        cost = estimate_plan(timings, plan)
        budget_minutes = inputs.get("budget_minutes")
        verdict = check_budget(cost, float(budget_minutes)) if budget_minutes else None

        plan_summary = {
            "preset": str(inputs.get("preset", "shortlist")),
            "question": preset.get("question"),
            "candidates": len(candidates),
            "conditions": len(conditions),
            "seeds": len(seeds),
            "renders": cost.renders,
            "estimated_minutes": round(cost.total_minutes, 1),
            # A route with no history contributes nothing to the total, which is
            # the honest choice - but silence would read as "free". Say how many
            # renders the estimate does not cover, budget or no budget.
            "estimate_warnings": (verdict.warnings if verdict else []) + (
                [
                    f"{sum(l.item.count for l in cost.unknown_lines)} of "
                    f"{cost.renders} renders are on routes never measured here "
                    f"({', '.join(sorted({l.item.route_key for l in cost.unknown_lines}))})"
                    " - they are excluded from the estimate, so the real time "
                    "will be higher"
                ]
                if cost.has_unknowns
                else []
            ),
            "unmeasured_renders": sum(l.item.count for l in cost.unknown_lines),
            "heaviest": [
                {"label": l.item.label, "minutes": round(l.total_minutes, 1)}
                for l in cost.heaviest(3)
            ],
            "caveat": preset.get("caveat") or None,
        }

        if inputs.get("dry_run"):
            return ToolResult(
                success=True,
                data={"plan": plan_summary, "verdict": verdict.describe() if verdict else None},
                duration_seconds=time.time() - started,
            )

        if verdict is not None and not verdict.fits:
            return ToolResult(
                success=False,
                data={"plan": plan_summary, "suggestions": verdict.suggestions},
                error=(
                    f"This sweep needs about {cost.total_minutes:.0f} GPU-minutes and the "
                    f"budget is {float(budget_minutes):.0f}. "
                    + " ".join(verdict.suggestions)
                ),
            )

        if not self._client.is_available():
            return ToolResult(success=False, error=self._client.unavailable_reason())

        from tools.graphics.comfyui_image import ComfyUIImage

        generator = ComfyUIImage()
        budget = RenderBudget(float(budget_minutes)) if budget_minutes else None
        out_root = project_dir / "casting" / slugify(inputs["character"])

        # Candidates are not interchangeable: a Z-Image UNet renders through a
        # VRGDG build route, an SDXL checkpoint through the bundled workflow.
        # The registry says which, per file, so one sweep can mix families.
        registry = ModelRegistry.load(
            inputs.get("models_root") or default_models_root(),
            inputs.get("registry_path") or default_ledger_path(),
        )
        if not registry.entries:
            registry.scan()
            registry.save()
        fallback_driver = DRIVERS.get(str(inputs.get("kind", "zimage")).replace(
            "zimage", "z-image"
        ))
        # Bind each family's encoder and VAE to filenames this server actually
        # has; the templates name the pack author's files, which are not ours.
        from tools._comfyui.client import ComfyUIClient

        image_client = ComfyUIClient()
        installed = image_client.list_models()
        clips, vaes = installed.get("clip", []), installed.get("vae", [])
        contended = 0
        starting_depth = image_client.queue_depth()
        if starting_depth:
            plan_summary.setdefault("estimate_warnings", []).append(
                f"ComfyUI already has {starting_depth} job(s) queued - this sweep "
                "waits behind them, and renders that wait are not timed"
            )

        results: list[CandidateResult] = []
        failures: list[str] = []
        stopped_early = False

        for candidate in candidates:
            result = CandidateResult(candidate=candidate)
            ledger_key = registry.key_for_basename(candidate.model)
            driver = (
                registry.driver_for(ledger_key) if ledger_key else None
            ) or fallback_driver
            if driver is None:
                entry = registry.entries.get(ledger_key or "", {})
                failures.append(
                    f"{candidate.label}: no graph source can drive this model"
                    + (f" ({entry['reason']})" if entry.get("reason") else "")
                )
                continue
            route = _route_for(driver)
            driver = resolve_driver(driver, clips=clips, vaes=vaes)
            if driver["graph_source"] == "vrgdg_build" and not driver.get("vae_name"):
                # Better to say so now than to die inside VAEDecode minutes in.
                failures.append(
                    f"{candidate.label}: no installed VAE matches "
                    f"{driver.get('vae_candidates')}"
                )
                continue

            for condition in conditions:
                prompt = build_prompt(inputs["brief"], condition)
                for seed in seeds:
                    if budget is not None and not budget.affords(timings.estimate(route)):
                        stopped_early = True
                        break

                    out_path = out_root / candidate.id / f"{condition_id(condition)}_s{seed}.png"
                    request = _render_request(
                        driver,
                        candidate=candidate,
                        prompt=prompt,
                        seed=int(seed),
                        settings=settings,
                        inputs=inputs,
                        output_path=out_path,
                    )
                    # Elapsed is measured from submission, so anything already
                    # queued is counted as our render time. One contended
                    # sample is indistinguishable from a genuinely slow route
                    # afterwards, and it moves the median for good - so measure
                    # the machine first and decline to record when it is busy.
                    queue_depth = image_client.queue_depth()
                    render_started = time.time()
                    outcome = generator.execute(request)
                    elapsed = time.time() - render_started
                    measurable = queue_depth == 0

                    if not outcome.success:
                        failures.append(f"{candidate.label} / {condition_id(condition)} / {seed}: {outcome.error}")
                        if ledger_key:
                            registry.record_run(
                                ledger_key, ok=False, error=str(outcome.error)
                            )
                        continue
                    if ledger_key:
                        registry.record_run(
                            ledger_key,
                            ok=True,
                            seconds=elapsed if measurable else None,
                        )
                    if measurable:
                        timings.record(route, elapsed, pixels=plan[0].pixels)
                    else:
                        contended += 1
                    if budget is not None:
                        budget.spend(elapsed)
                    result.shots.append(
                        Shot(
                            candidate_id=candidate.id,
                            condition=condition_id(condition),
                            seed=int(seed),
                            path=out_path,
                            seconds=elapsed,
                        )
                    )
                if stopped_early:
                    break
            if result.shots:
                results.append(result)
            if stopped_early:
                break

        # Save where we loaded from - a load/save asymmetry would write an
        # override's samples into the shared history.
        timings.save(timings_path)
        # What the renders proved outlives this run: a model that failed to load
        # is demoted, one that worked is confirmed, both with the evidence.
        registry.save()

        if not results:
            return ToolResult(
                success=False,
                data={"plan": plan_summary, "failures": failures},
                error="No candidate produced a single image. See data.failures.",
            )

        reference_prompt = build_prompt(inputs["brief"], conditions[0])
        ranked = score_candidates(results, prompt=reference_prompt, skip=skip)
        picked = shortlist(ranked, int(inputs.get("shortlist_size", 8)))

        # A quick run exists to be looked at, so its artefact is the large
        # side-by-side rather than a survey grid of thumbnails.
        if str(inputs.get("preset", "shortlist")) == "quick":
            sheet = comparison_sheet(
                picked,
                out_root / "model_comparison.png",
                prompt=reference_prompt,
                seed=seeds[0] if seeds else None,
            )
        else:
            sheet = contact_sheet(picked, out_root / "contact_sheet.png")
        elapsed_minutes = (time.time() - started) / 60.0
        report = write_report(
            out_root / "casting_report.json",
            character=inputs["character"],
            brief=inputs["brief"],
            ranked=ranked,
            conditions=conditions,
            seeds=seeds,
            elapsed_minutes=elapsed_minutes,
            contact_sheet_path=sheet,
        )

        artifacts = [str(report)] + ([str(sheet)] if sheet else [])
        return ToolResult(
            success=True,
            data={
                "plan": plan_summary,
                # Renders that shared the machine. Their images are fine; only
                # their timings were discarded, so the clock learns from fewer
                # samples rather than from wrong ones.
                "contended_renders": contended,
                "shortlist": [
                    {
                        "rank": i + 1,
                        "label": r.candidate.label,
                        "total": round(r.total, 4),
                        "scores": {k: (None if v is None else round(v, 3)) for k, v in r.scores.items()},
                        "seconds_per_image": round(r.seconds_per_image, 1),
                        "notes": r.notes,
                    }
                    for i, r in enumerate(picked)
                ],
                "comparison_sheet": str(sheet) if sheet else None,
                "caveat": preset.get("caveat") or None,
                "budget": budget.describe() if budget else None,
                "stopped_early": stopped_early,
                "failures": failures,
                "next_step": (
                    "Open the comparison sheet and pick the two or three models worth "
                    "taking further, then run preset='shortlist' on those to see whether "
                    "they hold one identity across seeds."
                    if str(inputs.get("preset", "shortlist")) == "quick"
                    else "Open the contact sheet and cast the character yourself. This "
                    "ranking removes candidates that were never viable; it does not "
                    "choose a look."
                ),
            },
            artifacts=artifacts,
            cost_usd=0.0,
            duration_seconds=time.time() - started,
            model="screen-test",
        )
