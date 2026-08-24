"""Import a VRGDG builder project into OpenMontage artifacts.

VRGDG's Music Video Builder is a timeline: scenes with prompts, an approved
still per scene, a rendered clip per scene, all snapped to a beat grid. That is
the same information an OpenMontage ``asset_manifest`` and ``edit_decisions``
carry, in a different vocabulary.

Two operations, in opposite directions:

* ``import`` reads a VRGDG session into an ``asset_manifest`` and
  ``edit_decisions``. It cannot corrupt anything, so it can be run freely.
* ``export`` writes an OpenMontage ``scene_plan`` into a VRGDG project, so a
  planned film opens in the Builder as a timeline with prompts already filled
  in. It refuses to overwrite a timeline that already has work in it unless
  told to.
"""

from __future__ import annotations

import json
import shutil
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
from lib.vrgdg_bridge import (
    CASTABLE_ENGINES,
    SceneMap,
    VRGDGBridgeError,
    apply_scene_plan_to_session,
    approved_images_by_scene,
    scene_plan_duration,
    scene_plan_to_srt,
    session_summary,
    session_to_asset_manifest,
    session_to_edit_decisions,
    timeline_segments,
)


class VRGDGProjectSync(BaseTool):
    name = "vrgdg_project_sync"
    version = "0.1.0"
    tier = ToolTier.CORE
    capability = "project_sync"
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

    capabilities = ["import_vrgdg_project", "export_scene_plan"]
    supports = {
        "import_session": True,
        "asset_copy": True,
        "stable_scene_ids": True,
        "export_scene_plan": True,
        "push_approved_stills": True,
        "scaffold_audio_and_srt": True,
    }
    best_for = [
        "turning a VRGDG timeline into an OpenMontage asset_manifest",
        "reading approved stills and rendered clips back after hand-editing in ComfyUI",
        "deriving edit_decisions from a beat-snapped VRGDG timeline",
        "opening an agent-authored scene_plan in the VRGDG Builder as a timeline",
    ]
    not_good_for = [
        "VRGDG projects on a different machine from OpenMontage",
        "merging a scene_plan into a timeline that has already been hand-edited",
    ]

    input_schema = {
        "type": "object",
        "required": ["project_dir"],
        "properties": {
            "operation": {
                "type": "string",
                "enum": ["import", "export"],
                "default": "import",
                "description": (
                    "import: VRGDG session -> asset_manifest + edit_decisions. "
                    "export: scene_plan -> a VRGDG project you can open in the Builder."
                ),
            },
            "scene_plan": {
                "type": "object",
                "description": "export: the scene_plan artifact inline.",
            },
            "scene_plan_path": {
                "type": "string",
                "description": (
                    "export: path to scene_plan.json. Defaults to "
                    "<project_dir>/artifacts/scene_plan.json."
                ),
            },
            "project_name": {
                "type": "string",
                "description": (
                    "export: name for the new VRGDG project. Defaults to the "
                    "OpenMontage project directory name."
                ),
            },
            "style_context": {
                "type": "object",
                "description": (
                    "export: playbook-derived style, passed to build_shot_prompt as "
                    "Layer 5. Keys: mood, visual_language.aesthetic."
                ),
            },
            "casting": {
                "type": "object",
                "description": (
                    "export: the cast to write into the timeline - the screen "
                    "test's verdict carried across the seam. Keys: model "
                    "(filename), engine (zimage|flux_klein; resolved from the "
                    "model registry when omitted), seed, loras, reference or "
                    "references ({close_up|medium|wide: path}, per DECISIONS "
                    "#30), scene_ids. Also accepts a full cast_record (the "
                    "candidate block is flattened)."
                ),
            },
            "casting_path": {
                "type": "string",
                "description": (
                    "export: path to a cast record JSON. Defaults to "
                    "<project_dir>/artifacts/cast_record.json when that file "
                    "exists; inline casting wins over the file."
                ),
            },
            "overwrite_timeline": {
                "type": "boolean",
                "default": False,
                "description": (
                    "export: replace a timeline that already holds work. Off by "
                    "default so an export cannot discard hours of hand-editing."
                ),
            },
            "push_approved_stills": {
                "type": "boolean",
                "default": True,
                "description": (
                    "export: copy images from the project asset_manifest into the "
                    "VRGDG project as each scene's approved still."
                ),
            },
            "scaffold_audio_and_srt": {
                "type": "boolean",
                "default": True,
                "description": (
                    "export: write a silent audio bed the length of the timeline and "
                    "an SRT of the scene labels. VRGDG's video routes require both, "
                    "even for a film with no dialogue."
                ),
            },
            "project_folder": {
                "type": "string",
                "description": (
                    "Absolute path of the VRGDG project (the folder holding "
                    "vrgdg_builder_session.json). Required for import; for export "
                    "it targets an existing project instead of creating one."
                ),
            },
            "project_dir": {
                "type": "string",
                "description": "OpenMontage project directory, i.e. projects/<project-id>.",
            },
            "copy_assets": {
                "type": "boolean",
                "default": True,
                "description": (
                    "Copy stills and clips into the OpenMontage project so it stays "
                    "self-contained. Turning this off records absolute paths, which "
                    "are not valid in a committed artifact."
                ),
            },
            "write_artifacts": {
                "type": "boolean",
                "default": True,
                "description": (
                    "Write asset_manifest.json and edit_decisions.json into "
                    "<project_dir>/artifacts/. Off returns them without touching disk."
                ),
            },
            "render_runtime": {
                "type": "string",
                "enum": ["remotion", "hyperframes", "ffmpeg"],
                "default": "ffmpeg",
                "description": (
                    "Recorded in edit_decisions. edit_decisions requires it, but the "
                    "runtime choice belongs to the proposal stage - pass the value "
                    "already agreed there rather than accepting this default blindly."
                ),
            },
        },
    }

    resource_profile = ResourceProfile(
        cpu_cores=1, ram_mb=512, vram_mb=0, disk_mb=2000, network_required=False
    )
    retry_policy = RetryPolicy(max_retries=0, retryable_errors=[])
    idempotency_key_fields = ["operation", "project_folder", "project_dir"]
    side_effects = [
        "import: copies stills and clips into <project_dir>/assets/",
        "import: writes artifacts/asset_manifest.json, artifacts/edit_decisions.json "
        "and artifacts/vrgdg_scene_map.json",
        "export: creates a VRGDG project and replaces its timeline",
        "export: writes a silent audio bed and an SRT into that project",
    ]
    user_visible_verification = [
        "Check the scene count and timeline length against the VRGDG Builder",
        "import: confirm each cut points at the clip you approved",
        "export: open the project in the Builder and check the scenes and prompts",
    ]

    def __init__(self) -> None:
        self._client = VRGDGClient()

    def get_status(self) -> ToolStatus:
        return ToolStatus.AVAILABLE if self._client.is_available() else ToolStatus.UNAVAILABLE

    def get_info(self) -> dict[str, Any]:
        info = super().get_info()
        info["direction"] = "vrgdg -> openmontage (read only)"
        info["produces"] = ["asset_manifest", "edit_decisions", "vrgdg_scene_map"]
        return info

    def estimate_cost(self, inputs: dict[str, Any]) -> float:
        return 0.0

    def estimate_runtime(self, inputs: dict[str, Any]) -> float:
        return 5.0

    def execute(self, inputs: dict[str, Any]) -> ToolResult:
        start = time.time()
        project_dir = Path(inputs["project_dir"])
        if not project_dir.is_dir():
            return ToolResult(
                success=False,
                error=(
                    f"OpenMontage project directory does not exist: {project_dir}. "
                    f"Create it with lib.checkpoint.init_project first."
                ),
            )
        if not self._client.is_available():
            return ToolResult(success=False, error=self._client.unavailable_reason())

        operation = str(inputs.get("operation", "import"))
        try:
            if operation == "export":
                return self._export(inputs, project_dir, start)
            if operation == "import":
                return self._import(inputs, project_dir, start)
        except VRGDGError as exc:
            return ToolResult(success=False, error=f"VRGDG route failed: {exc}")
        except VRGDGBridgeError as exc:
            return ToolResult(success=False, error=str(exc))
        return ToolResult(
            success=False, error=f'Unknown operation {operation!r}; use "import" or "export".'
        )

    # ------------------------------------------------------------------
    # import: VRGDG -> OpenMontage
    # ------------------------------------------------------------------

    def _import(
        self, inputs: dict[str, Any], project_dir: Path, start: float
    ) -> ToolResult:
        project_folder = inputs.get("project_folder")
        if not project_folder:
            return ToolResult(
                success=False, error="import requires project_folder (the VRGDG project)."
            )
        project_folder = str(project_folder)

        session = self._load_session(project_folder)
        if session is None:
            return ToolResult(
                success=False,
                error=(
                    f"VRGDG returned no session for {project_folder}. Check that the "
                    f"folder holds a vrgdg_builder_session.json."
                ),
            )

        scene_map = SceneMap.load(project_dir)
        manifest, manifest_warnings = session_to_asset_manifest(
            session,
            project_dir=project_dir,
            scene_map=scene_map,
            copy_assets=bool(inputs.get("copy_assets", True)),
        )
        cut, cut_warnings = session_to_edit_decisions(
            session,
            scene_map=scene_map,
            render_runtime=str(inputs.get("render_runtime", "ffmpeg")),
        )

        written: list[str] = []
        if inputs.get("write_artifacts", True):
            written = self._write_artifacts(
                project_dir,
                {"asset_manifest.json": manifest, "edit_decisions.json": cut},
            )
            written.append(
                str(scene_map.save(project_dir, vrgdg_project_folder=project_folder))
            )

        return ToolResult(
            success=True,
            data={
                "provider": "vrgdg",
                "operation": "import",
                "vrgdg_project_folder": project_folder,
                "summary": session_summary(session),
                "asset_manifest": manifest,
                "edit_decisions": cut,
                "scene_map": scene_map.pairs,
                "warnings": manifest_warnings + cut_warnings,
            },
            artifacts=written,
            cost_usd=0.0,
            duration_seconds=time.time() - start,
            model="vrgdg-builder-session",
        )

    # ------------------------------------------------------------------
    # export: OpenMontage -> VRGDG
    # ------------------------------------------------------------------

    def _export(
        self, inputs: dict[str, Any], project_dir: Path, start: float
    ) -> ToolResult:
        scene_plan = inputs.get("scene_plan")
        if not isinstance(scene_plan, dict):
            plan_path = Path(
                inputs.get("scene_plan_path")
                or project_dir / "artifacts" / "scene_plan.json"
            )
            if not plan_path.is_file():
                return ToolResult(
                    success=False,
                    error=(
                        f"No scene_plan to export. Pass scene_plan inline or "
                        f"scene_plan_path; looked for {plan_path}."
                    ),
                )
            try:
                scene_plan = json.loads(plan_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError) as exc:
                return ToolResult(
                    success=False, error=f"Unreadable scene_plan at {plan_path}: {exc}"
                )

        # A VRGDG project is created rather than reused unless one is named, so a
        # first export can never land on top of existing work by accident.
        project_folder = inputs.get("project_folder")
        created = False
        if not project_folder:
            name = str(inputs.get("project_name") or project_dir.name)
            response = self._client.new_project(name)
            project_folder = response.get("project_folder")
            created = True
            if not project_folder:
                return ToolResult(
                    success=False,
                    error=f"VRGDG did not report a project folder for {name!r}.",
                )
        project_folder = str(project_folder)

        session = self._load_session(project_folder)
        if session is None:
            return ToolResult(
                success=False,
                error=f"VRGDG returned no session for {project_folder}.",
            )

        if not inputs.get("overwrite_timeline", False):
            occupied = self._occupied_segments(session)
            if occupied:
                return ToolResult(
                    success=False,
                    data={"vrgdg_project_folder": project_folder, "scenes_with_work": occupied},
                    error=(
                        f"{project_folder} already has {occupied} scene(s) with prompts, "
                        f"images or renders. Exporting would replace that timeline. "
                        f"Pass overwrite_timeline=true if that is what you want, or "
                        f"leave project_folder unset to create a new project."
                    ),
                )

        scene_map = SceneMap.load(project_dir)
        casting, casting_warnings = self._resolve_casting(
            inputs, project_dir, project_folder
        )
        session, warnings = apply_scene_plan_to_session(
            session,
            scene_plan,
            scene_map=scene_map,
            style_context=inputs.get("style_context"),
            casting=casting,
        )
        warnings = casting_warnings + warnings

        # Stills are pushed before the save so their landed paths can be
        # recorded in the same session write. VRGDG's save_scene_image route
        # only copies the file - recording where it landed is the caller's
        # job, exactly as the Builder UI does after calling it.
        pushed: list[str] = []
        if inputs.get("push_approved_stills", True):
            pushed, saved_paths, push_warnings = self._push_stills(
                project_dir, project_folder, scene_plan, scene_map
            )
            warnings.extend(push_warnings)
            if saved_paths:
                from lib.vrgdg_bridge import stable_segment_id

                by_segment = {
                    stable_segment_id(scene_id): path
                    for scene_id, path in saved_paths.items()
                }
                for segment in session.get("segments", []):
                    landed = by_segment.get(str(segment.get("id") or ""))
                    if landed:
                        segment["image"] = landed
                        segment["approved_image_path"] = landed

        self._client.save_session(project_folder, session)

        extras: dict[str, Any] = {}
        if inputs.get("scaffold_audio_and_srt", True):
            duration = scene_plan_duration(scene_plan)
            if duration > 0:
                try:
                    audio = self._client.create_silent_audio(project_folder, duration)
                    extras["audio_path"] = audio.get("audio_path") or audio.get("saved_path")
                except VRGDGError as exc:
                    warnings.append(f"could not create the silent audio bed: {exc}")
            srt = scene_plan_to_srt(scene_plan)
            if srt.strip():
                try:
                    self._client.save_project_srt(project_folder, srt)
                    extras["srt_written"] = True
                except VRGDGError as exc:
                    warnings.append(f"could not write the project SRT: {exc}")

        scene_map.save(project_dir, vrgdg_project_folder=project_folder)

        return ToolResult(
            success=True,
            data={
                "provider": "vrgdg",
                "operation": "export",
                "vrgdg_project_folder": project_folder,
                "created_project": created,
                "scenes_exported": len(session.get("segments") or []),
                "timeline_seconds": scene_plan_duration(scene_plan),
                "stills_pushed": pushed,
                "scene_map": scene_map.pairs,
                "warnings": warnings,
                **(
                    {
                        "casting_applied": {
                            "model": casting.get("model"),
                            "engine": casting.get("engine"),
                            "seed": casting.get("seed"),
                            "references": casting.get("references")
                            or casting.get("reference"),
                        }
                    }
                    if casting
                    else {}
                ),
                **extras,
            },
            artifacts=[str(project_dir / "artifacts" / "vrgdg_scene_map.json")],
            cost_usd=0.0,
            duration_seconds=time.time() - start,
            model="vrgdg-builder-session",
        )

    # ------------------------------------------------------------------
    # helpers
    # ------------------------------------------------------------------

    def _resolve_casting(
        self, inputs: dict[str, Any], project_dir: Path, project_folder: str
    ) -> tuple[dict[str, Any] | None, list[str]]:
        """Load the cast, resolve its engine, and stage its references.

        Returns (casting, warnings); casting is None when there is nothing to
        apply, which is the common case and not a problem.
        """
        warnings: list[str] = []
        casting = inputs.get("casting")
        if isinstance(casting, dict):
            casting = dict(casting)
        else:
            explicit = inputs.get("casting_path")
            path = Path(explicit) if explicit else project_dir / "artifacts" / "cast_record.json"
            if not path.is_file():
                if explicit:
                    warnings.append(f"casting: no cast record at {path}")
                return None, warnings
            try:
                casting = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError) as exc:
                warnings.append(f"casting: unreadable cast record {path}: {exc}")
                return None, warnings
            if not isinstance(casting, dict):
                warnings.append(f"casting: {path} is not a JSON object")
                return None, warnings

        # A full cast_record keeps the model inside its candidate block.
        candidate = casting.get("candidate")
        if isinstance(candidate, dict):
            casting.setdefault("model", candidate.get("model"))
            if candidate.get("loras"):
                casting.setdefault("loras", candidate.get("loras"))

        if not casting.get("engine"):
            engine, engine_warnings = self._engine_for_model(
                str(casting.get("model") or "")
            )
            warnings.extend(engine_warnings)
            if engine:
                casting["engine"] = engine

        self._stage_references(casting, project_folder, warnings)
        return casting, warnings

    @staticmethod
    def _engine_for_model(model: str) -> tuple[str | None, list[str]]:
        """Which Builder engine drives *model*, from the registry, not the name."""
        if not model:
            return None, ["casting: no model filename to resolve an engine for"]
        try:
            from lib.model_registry import (
                ModelRegistry,
                default_ledger_path,
                default_models_root,
            )

            registry = ModelRegistry.load(default_models_root(), default_ledger_path())
            key = registry.key_for_basename(model)
            driver = registry.driver_for(key) if key else None
        except Exception as exc:  # registry unavailable is a warning, not a crash
            return None, [f"casting: could not consult the model registry: {exc}"]
        if driver is None:
            return None, [
                f"casting: {model} is not in the model registry; "
                f"pass engine explicitly or run a registry scan"
            ]
        kind = driver.get("kind")
        if kind in CASTABLE_ENGINES:
            return str(kind), []
        return None, [
            f"casting: {model} is driven by "
            f"{driver.get('workflow') or driver.get('graph_source') or 'an unknown path'}, "
            f"which is not a Builder engine - render stills with comfyui_image "
            f"and re-export; approved stills push into the timeline"
        ]

    @staticmethod
    def _stage_references(
        casting: dict[str, Any], project_folder: str, warnings: list[str]
    ) -> None:
        """Copy reference images into the VRGDG project and rewrite the paths.

        Staged so the Builder project stays self-contained - the mirror of the
        import direction copying assets into the OpenMontage project.
        """

        def stage(path_text: str, stem: str) -> str | None:
            source = Path(str(path_text).strip().strip('"'))
            if not source.is_file():
                warnings.append(f"casting: reference {source} does not exist; dropped")
                return None
            target_dir = Path(project_folder) / "references"
            try:
                target_dir.mkdir(parents=True, exist_ok=True)
                target = target_dir / f"{stem}{source.suffix.lower()}"
                shutil.copy2(source, target)
            except OSError as exc:
                warnings.append(f"casting: could not stage reference {source}: {exc}")
                return None
            return str(target.resolve())

        references = casting.get("references")
        if isinstance(references, dict):
            staged: dict[str, str] = {}
            for family, path_text in references.items():
                if not (isinstance(path_text, str) and path_text.strip()):
                    continue
                copied = stage(path_text, f"reference_{family}")
                if copied:
                    staged[str(family)] = copied
            casting["references"] = staged
        elif isinstance(casting.get("reference"), str) and casting["reference"].strip():
            copied = stage(casting["reference"], "reference")
            casting["reference"] = copied or ""

    def _load_session(self, project_folder: str) -> dict[str, Any] | None:
        response = self._client.load_session(project_folder)
        session = response.get("session")
        return session if isinstance(session, dict) else None

    @staticmethod
    def _occupied_segments(session: dict[str, Any]) -> int:
        """How many scenes already hold work a re-export would discard."""
        occupied = 0
        for segment in timeline_segments(session):
            if any(
                str(segment.get(key) or "").strip()
                for key in ("t2i_prompt", "i2v_prompt", "image", "video_path", "notes")
            ):
                occupied += 1
        return occupied

    @staticmethod
    def _write_artifacts(project_dir: Path, payloads: dict[str, Any]) -> list[str]:
        artifacts_dir = project_dir / "artifacts"
        artifacts_dir.mkdir(parents=True, exist_ok=True)
        written = []
        for name, payload in payloads.items():
            path = artifacts_dir / name
            path.write_text(
                json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
            )
            written.append(str(path))
        return written

    def _push_stills(
        self,
        project_dir: Path,
        project_folder: str,
        scene_plan: dict[str, Any],
        scene_map: SceneMap,
    ) -> tuple[list[str], dict[str, str], list[str]]:
        """Send approved stills over as each scene's Builder image.

        Returns (pushed scene ids, {scene_id: landed path}, warnings). The
        landed paths matter: the route copies the file and reports where it
        put it, and the session must be told - the Builder UI does the same
        after every save_scene_image call.
        """
        manifest_path = project_dir / "artifacts" / "asset_manifest.json"
        if not manifest_path.is_file():
            return [], {}, []
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            return [], {}, [f"could not read asset_manifest.json: {exc}"]

        by_scene = approved_images_by_scene(manifest)
        pushed: list[str] = []
        landed: dict[str, str] = {}
        warnings: list[str] = []
        scenes = [s for s in (scene_plan.get("scenes") or []) if isinstance(s, dict)]
        for index, scene in enumerate(scenes):
            scene_id = str(scene.get("id"))
            rel = by_scene.get(scene_id)
            if not rel:
                continue
            source = project_dir / rel
            if not source.is_file():
                warnings.append(f"{scene_id}: {rel} is in the manifest but not on disk")
                continue
            try:
                # VRGDG numbers scenes from 1, in timeline order.
                response = self._client.save_scene_image(
                    project_folder, index + 1, str(source.resolve())
                )
                pushed.append(scene_id)
                saved = str(response.get("saved_path") or "")
                if saved:
                    landed[scene_id] = saved
            except VRGDGError as exc:
                warnings.append(f"{scene_id}: could not push the still: {exc}")
        return pushed, landed, warnings
