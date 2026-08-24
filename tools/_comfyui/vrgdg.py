"""Client for the VRGDG (comfyui-vrgamedevgirl) HTTP surface.

VRGDG is a ComfyUI custom-node pack that ships its own API-format workflow
templates plus routes that patch and return them. Its builder routes locate
nodes by ``class_type`` with a numeric fallback, so a template edit does not
invalidate the caller the way a stored node-ID map does.

That makes ``/vrgdg/workflow_runner/build_*_prompt`` a better graph source
than a workflow-binding profile: OpenMontage sends scene parameters and gets
back a ready-to-queue graph. This module is the transport for that.

The routes live on the same ComfyUI server as everything else, so the server
URL resolution mirrors :class:`tools._comfyui.client.ComfyUIClient`.
"""

from __future__ import annotations

import hashlib
import json
import os
from dataclasses import dataclass, field
from typing import Any, Mapping

import requests


class VRGDGError(Exception):
    """Raised when a VRGDG route fails, is unavailable, or is not permitted.

    VRGDG's routes do not share one error convention: most reply
    ``{"ok": false, "error": ...}`` with status 400, the storyboard routes use
    status 500, ``/vrgdg/update/v10/status`` returns ``ok: false`` with status
    200, and two ``*_from_concepts/generate`` routes return the raw helper
    result with no ``ok`` key at all. :meth:`VRGDGClient._request` normalizes
    all of those into this exception so callers see one failure mode.
    """


# ---------------------------------------------------------------------------
# Route policy
# ---------------------------------------------------------------------------

#: Routes that open a native OS dialog, launch a browser, or otherwise block on
#: a human sitting at the ComfyUI host. Calling these from an unattended
#: pipeline hangs the run, so they are refused before the request is made.
HOST_BOUND_ROUTES = frozenset(
    {
        "/vrgdg/music_builder/pick_path",
        "/vrgdg/music_builder/open_local_file",
        "/vrgdg/lora_dataset/pick_folder",
        "/vrgdg/lora_dataset/open_folder",
        "/vrgdg/browser_image/setup",
        "/vrgdg/browser_image/open_login",
        "/vrgdg/browser_image/manual_open",
        "/vrgdg/browser_image/manual_upload",
        "/vrgdg/browser_image/manual_submit",
        "/vrgdg/browser_image/manual_finish",
        "/vrgdg/browser_image/manual_wait_download",
        "/vrgdg/ltx/tensorboard/open",
    }
)


@dataclass(frozen=True)
class BuildRoute:
    """A ``build_*_prompt`` route and what a caller has to supply.

    ``project_bound`` routes read a VRGDG project from disk (audio, SRT, an
    image folder) and cannot be driven from parameters alone; the returned
    graph writes into the project rather than to a caller-chosen path.
    """

    kind: str
    path: str
    capability: str          # "image" | "video" | "audio" | "utility"
    project_bound: bool
    required: tuple[str, ...]
    returns_seed: bool
    description: str


_ROUTES: tuple[BuildRoute, ...] = (
    BuildRoute(
        "zimage", "/vrgdg/workflow_runner/build_zimage_prompt", "image", False,
        ("prompt", "unet_name", "clip_name", "vae_name"), True,
        "Z-Image Turbo two-pass text-to-image with optional LoRA stack.",
    ),
    BuildRoute(
        "krea2", "/vrgdg/workflow_runner/build_krea2_prompt", "image", False,
        ("prompt",), True,
        "Krea-2 turbo text-to-image with optional Z-Image enhance pass.",
    ),
    BuildRoute(
        "krea2_2pass", "/vrgdg/workflow_runner/build_krea2_2pass_prompt", "image", False,
        ("prompt",), True,
        "Krea-2 two-pass text-to-image.",
    ),
    BuildRoute(
        "ernie_image", "/vrgdg/workflow_runner/build_ernie_image_prompt", "image", False,
        ("prompt",), True,
        "ERNIE image turbo text-to-image.",
    ),
    BuildRoute(
        "flux_klein", "/vrgdg/workflow_runner/build_flux_klein_prompt", "image", False,
        ("prompt",), True,
        "FLUX.2 Klein multi-image reference composition. Reference images go in "
        "'images' (or 'image_ingredients') as a path, a newline-separated list, "
        "or [{'path': ...}] - NOT 'image_paths', which is the node's own input "
        "name and is silently ignored. Without the key the route deletes the "
        "conditioning node, so a wrong name yields a plain text-to-image render "
        "with no error. A reference is worth ~4x a description on a matched "
        "shot but does not survive a change of shot size; see DECISIONS.md #26.",
    ),
    BuildRoute(
        "nb_image", "/vrgdg/workflow_runner/build_nb_image_prompt", "image", False,
        ("prompt",), True,
        "Nano Banana image generation. Hosted: needs network and credits.",
    ),
    BuildRoute(
        "z_upscale_enhance", "/vrgdg/workflow_runner/build_z_upscale_enhance_prompt", "image", False,
        ("prompt",), True,
        "Z-Image upscale and detail-enhance pass over an existing image.",
    ),
    BuildRoute(
        "i2v", "/vrgdg/workflow_runner/build_i2v_prompt", "video", True,
        ("i2v_prompt", "project_folder", "audio_path", "image_folder", "srt_path"), False,
        "LTX 2.3 image-to-video for one scene of a VRGDG project.",
    ),
    BuildRoute(
        "t2v", "/vrgdg/workflow_runner/build_t2v_prompt", "video", True,
        ("t2v_prompt", "project_folder", "audio_path", "srt_path"), False,
        "LTX 2.3 text-to-video for one scene of a VRGDG project.",
    ),
    BuildRoute(
        "flf", "/vrgdg/workflow_runner/build_flf_prompt", "video", True,
        ("project_folder",), False,
        "LTX 2.3 first/last-frame interpolation.",
    ),
    BuildRoute(
        "rtv", "/vrgdg/workflow_runner/build_rtv_prompt", "video", True,
        ("project_folder",), False,
        "LTX 2.3 reference-to-video.",
    ),
    BuildRoute(
        "ingredients", "/vrgdg/workflow_runner/build_ingredients_prompt", "video", True,
        ("project_folder",), False,
        "LTX 2.3 ingredients-grid to video.",
    ),
    BuildRoute(
        "id_lora", "/vrgdg/workflow_runner/build_id_lora_prompt", "video", True,
        ("project_folder",), False,
        "LTX 2.3 identity-LoRA video for character consistency.",
    ),
    BuildRoute(
        "minimax_h3", "/vrgdg/workflow_runner/build_minimax_h3_prompt", "video", True,
        ("project_folder",), False,
        "MiniMax-H3 audio-driven or built-in-audio video.",
    ),
    BuildRoute(
        "transcribe", "/vrgdg/workflow_runner/build_transcribe_prompt", "utility", False,
        (), False,
        "Whisper/stable-ts transcription to SRT.",
    ),
    BuildRoute(
        "timestamped_transcribe", "/vrgdg/workflow_runner/build_timestamped_transcribe_prompt",
        "utility", False, (), False,
        "Timestamped lyric transcription to SRT.",
    ),
    BuildRoute(
        "clear_memory", "/vrgdg/workflow_runner/build_clear_memory_prompt", "utility", False,
        (), False,
        "Graph that unloads models and frees VRAM.",
    ),
)

BUILD_ROUTES: dict[str, BuildRoute] = {r.kind: r for r in _ROUTES}


def build_routes_for(capability: str | None = None) -> list[BuildRoute]:
    """Return the build routes, optionally filtered by capability."""
    if capability is None:
        return list(_ROUTES)
    return [r for r in _ROUTES if r.capability == capability]


# ---------------------------------------------------------------------------
# Output-node resolution
# ---------------------------------------------------------------------------

#: Terminal saver classes, most specific first. A VRGDG graph often carries
#: preview and comparison savers alongside the deliverable, so ordering
#: matters: the first class found wins.
_SAVER_PRIORITY: tuple[tuple[str, str], ...] = (
    ("VRGDG_CreateFinalVideo_SRT", "video"),
    ("VRGDG_CreateFinalVideo", "video"),
    ("VHS_VideoCombine", "video"),
    ("SaveVideo", "video"),
    ("SaveWEBM", "video"),
    ("SaveAnimatedWEBP", "video"),
    ("SaveAudioMP3", "audio"),
    ("SaveAudio", "audio"),
    ("SaveImage", "image"),
)

#: VRGDG's image templates (Z-Image, Krea-2, Flux Klein, z-upscale) genuinely
#: terminate in PreviewImage - the Builder UI persists the result afterwards
#: through /vrgdg/workflow_runner/save_image. So a preview node is a legitimate
#: last resort, used only when the graph has no real saver. ComfyUI reports
#: these under type "temp", which the client already honours when downloading.
_PREVIEW_FALLBACK: tuple[tuple[str, str], ...] = (
    ("PreviewImage", "image"),
    ("PreviewAudio", "audio"),
)

#: Display-only nodes that are never the deliverable, whatever else the graph
#: contains. A side-by-side comparison is not the clean generated asset.
_NEVER_OUTPUT = frozenset(
    {
        "VRGDG_ShowImage",
        "VRGDG_ImageCompare",
        "VRGDG_VideoCompareSlider",
        "VRGDG_ShowText",
        "VRGDG_ShowAny",
        "VRGDG_BoxIT",
        "VRGDG_NoteBox",
    }
)


def resolve_output_node(
    prompt: Mapping[str, Any], *, prefer: str | None = None
) -> str:
    """Return the node id the artifact should be downloaded from.

    Real savers are considered first; *prefer* (``"image"``, ``"video"``,
    ``"audio"``) puts savers of that kind ahead of the rest. Only when a graph
    has no saver at all does a preview node qualify, which is the normal shape
    of VRGDG's image templates - they end in PreviewImage and the Builder UI
    persists the result separately. Comparison and display nodes never qualify.

    Raises :class:`VRGDGError` when nothing qualifies, rather than guessing:
    a wrong output node silently downloads the wrong artifact.
    """
    if not isinstance(prompt, Mapping) or not prompt:
        raise VRGDGError("Cannot resolve an output node from an empty graph")

    by_class: dict[str, list[str]] = {}
    for node_id, node in prompt.items():
        if not isinstance(node, Mapping):
            continue
        class_type = node.get("class_type")
        if not isinstance(class_type, str) or class_type in _NEVER_OUTPUT:
            continue
        by_class.setdefault(class_type, []).append(str(node_id))

    def _search(candidates: tuple[tuple[str, str], ...]) -> str | None:
        ordered = list(candidates)
        if prefer:
            ordered.sort(key=lambda item: 0 if item[1] == prefer else 1)
        for class_type, _kind in ordered:
            ids = by_class.get(class_type)
            if ids:
                # Deterministic when a graph has several nodes of one class:
                # the highest id is the latest-added, which is the deliverable
                # in every VRGDG template inspected.
                return sorted(ids, key=_node_sort_key)[-1]
        return None

    found = _search(_SAVER_PRIORITY) or _search(_PREVIEW_FALLBACK)
    if found is not None:
        return found

    raise VRGDGError(
        "No saver or preview node found in the VRGDG graph. Pass output_node "
        "explicitly. Classes searched: "
        + ", ".join(c for c, _ in _SAVER_PRIORITY + _PREVIEW_FALLBACK)
    )


def _node_sort_key(node_id: str) -> tuple[int, ...]:
    """Sort ``"271:216"``-style composite ids numerically, segment by segment."""
    parts = []
    for chunk in str(node_id).split(":"):
        try:
            parts.append(int(chunk))
        except ValueError:
            parts.append(0)
    return tuple(parts)


def reachable_nodes(prompt: Mapping[str, Any], output_node: str) -> set[str]:
    """Node ids the output actually depends on, walking inputs transitively."""
    seen: set[str] = set()
    stack = [str(output_node)]
    while stack:
        node_id = stack.pop()
        if node_id in seen or node_id not in prompt:
            continue
        seen.add(node_id)
        node = prompt[node_id]
        if not isinstance(node, Mapping):
            continue
        for value in (node.get("inputs") or {}).values():
            # A link is ["<node id>", <slot>]; anything else is a literal.
            if isinstance(value, list) and value and isinstance(value[0], (str, int)):
                stack.append(str(value[0]))
    return seen


def prune_to_output(
    prompt: Mapping[str, Any], output_node: str
) -> tuple[dict[str, Any], list[str]]:
    """Drop nodes the output does not depend on. Returns (graph, removed ids).

    VRGDG templates carry side branches that feed nothing - the Z-Image graph
    ends its chain at PreviewImage but also hangs RAMCleanup and VRAMCleanup off
    the VAEDecode as dead ends. ComfyUI validates the whole submitted prompt, so
    one uninstalled node pack on a branch that produces nothing still blocks the
    render. Pruning matches how ComfyUI executes (ancestors of outputs only), so
    the artifact is unchanged.
    """
    keep = reachable_nodes(prompt, output_node)
    pruned = {node_id: value for node_id, value in prompt.items() if node_id in keep}
    removed = sorted(set(prompt) - keep, key=_node_sort_key)
    return pruned, removed


def node_class_types(prompt: Mapping[str, Any]) -> set[str]:
    """Distinct ``class_type`` values used by a graph."""
    types: set[str] = set()
    for node in prompt.values():
        if isinstance(node, Mapping):
            class_type = node.get("class_type")
            if isinstance(class_type, str):
                types.add(class_type)
    return types


def graph_hash(prompt: Mapping[str, Any]) -> str:
    """Stable hash of a submitted graph, for the provenance record."""
    return hashlib.sha256(
        json.dumps(prompt, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()[:16]


# ---------------------------------------------------------------------------
# The built graph
# ---------------------------------------------------------------------------

@dataclass
class VRGDGGraph:
    """A ready-to-queue graph returned by a ``build_*_prompt`` route."""

    kind: str
    prompt: dict[str, Any]
    workflow_path: str | None = None
    used_seed: int | None = None
    output_folder: str | None = None
    raw: dict[str, Any] = field(default_factory=dict)

    pruned_nodes: list[str] = field(default_factory=list)

    def output_node(self, *, prefer: str | None = None) -> str:
        return resolve_output_node(self.prompt, prefer=prefer)

    def apply_sampler_recipe(self, recipe: Mapping[str, Any]) -> dict[str, Any]:
        """Override the template's sampling with a checkpoint's own settings.

        The ``build_*_prompt`` routes patch model names from the payload but
        ignore sampler keys entirely, so this edits the returned graph. Nodes
        are matched by ``class_type``, never by id: VRGDG renumbers its
        templates between versions, and a node-id map is the maintenance burden
        DECISIONS.md #1 chose these routes to avoid.

        Returns what it actually changed - a recipe field with nowhere to go is
        reported rather than silently dropped.
        """
        applied: dict[str, Any] = {}
        steps = recipe.get("steps")
        for node in self.prompt.values():
            if not isinstance(node, dict):
                continue
            class_type = str(node.get("class_type", ""))
            inputs = node.get("inputs")
            if not isinstance(inputs, dict):
                continue

            if class_type == "KSamplerSelect" and recipe.get("sampler_name"):
                inputs["sampler_name"] = recipe["sampler_name"]
                applied["sampler_name"] = recipe["sampler_name"]
            elif class_type == "SamplerCustom" and recipe.get("guidance") is not None:
                inputs["cfg"] = recipe["guidance"]
                applied["guidance"] = recipe["guidance"]
            elif "Scheduler" in class_type and isinstance(steps, int):
                previous = inputs.get("steps")
                inputs["steps"] = steps
                applied["steps"] = steps
                # end_at_step tracks the total; start_at_step marks where a
                # second pass begins, so it keeps its share of the schedule
                # rather than an absolute index into a schedule that shrank.
                if inputs.get("end_at_step") == previous:
                    inputs["end_at_step"] = steps
                start = inputs.get("start_at_step")
                if isinstance(start, int) and isinstance(previous, int) and previous:
                    inputs["start_at_step"] = max(0, round(start * steps / previous))
        return applied

    def prune(self, output_node: str) -> list[str]:
        """Drop dead branches in place. Returns the removed node ids."""
        self.prompt, removed = prune_to_output(self.prompt, output_node)
        self.pruned_nodes = removed
        return removed

    def provenance(self, *, pack_version: str | None = None) -> dict[str, Any]:
        """Reproducibility record for this graph.

        The submitted-graph hash is the strong part: it pins the actual graph
        rather than the name of a profile that produced it.
        """
        record: dict[str, Any] = {
            "graph_source": "vrgdg_builder",
            "vrgdg_route": BUILD_ROUTES[self.kind].path if self.kind in BUILD_ROUTES else None,
            "vrgdg_kind": self.kind,
            "vrgdg_template": self.workflow_path,
            "submitted_graph_hash": graph_hash(self.prompt),
            "node_count": len(self.prompt),
        }
        if self.used_seed is not None:
            record["used_seed"] = self.used_seed
        if self.output_folder:
            record["vrgdg_output_folder"] = self.output_folder
        if self.pruned_nodes:
            # Recorded because it means the graph submitted differs from the one
            # VRGDG built: dead branches were dropped so an uninstalled node
            # pack could not fail validation.
            record["pruned_unreachable_nodes"] = self.pruned_nodes
            record["pruned_reason"] = "missing node types on unreachable branches"
        if pack_version:
            record["vrgdg_pack_version"] = pack_version
        return record


# ---------------------------------------------------------------------------
# Client
# ---------------------------------------------------------------------------

class VRGDGClient:
    """Thin, normalizing client for the VRGDG routes on a ComfyUI server."""

    def __init__(self, server_url: str | None = None, *, timeout: int = 120) -> None:
        resolved = (
            server_url
            or os.environ.get("COMFYUI_VRGDG_SERVER_URL")
            or os.environ.get("COMFYUI_VIDEO_SERVER_URL")
            or os.environ.get("COMFYUI_SERVER_URL")
        )
        self.server_url = (resolved or "http://localhost:8188").rstrip("/")
        self.timeout = timeout
        self._known_node_types: set[str] = set()

    # -- availability ----------------------------------------------------

    def is_available(self) -> bool:
        """True when the server responds and the VRGDG pack is loaded."""
        try:
            self._request("GET", "/vrgdg/workflow_runner/model_root")
            return True
        except Exception:
            return False

    def unavailable_reason(self) -> str:
        try:
            requests.get(f"{self.server_url}/system_stats", timeout=5).raise_for_status()
        except Exception:
            return (
                f"ComfyUI is not reachable at {self.server_url}. Start it, or set "
                f"COMFYUI_SERVER_URL (or COMFYUI_VRGDG_SERVER_URL) to its address."
            )
        return (
            f"ComfyUI answered at {self.server_url} but the VRGDG routes did not. "
            f"Install/enable comfyui-vrgamedevgirl and restart ComfyUI."
        )

    def pack_version(self) -> str | None:
        """Installed VRGDG version, or None when the status route is silent."""
        try:
            payload = self._request(
                "GET", "/vrgdg/update/v10/status", tolerate_not_ok=True
            )
        except VRGDGError:
            return None
        for key in ("installed_commit", "latest_commit"):
            value = payload.get(key)
            if isinstance(value, str) and value:
                return value[:12]
        return None

    # -- build -----------------------------------------------------------

    def build(self, kind: str, payload: Mapping[str, Any]) -> VRGDGGraph:
        """Ask VRGDG to patch its template for *kind* and return the graph.

        Required keys are checked here rather than server-side, so a missing
        field is a clear error instead of a 400 with VRGDG's own wording.
        """
        route = BUILD_ROUTES.get(kind)
        if route is None:
            raise VRGDGError(
                f"Unknown VRGDG build kind {kind!r}. Known: "
                + ", ".join(sorted(BUILD_ROUTES))
            )
        if not isinstance(payload, Mapping):
            raise VRGDGError("VRGDG build payload must be a mapping")

        missing = [key for key in route.required if not payload.get(key)]
        if missing:
            raise VRGDGError(
                f"VRGDG {kind} build is missing required payload keys: "
                + ", ".join(missing)
                + (
                    ". This route is project-bound: it reads a VRGDG project "
                    "from disk, so scaffold one first (see new_project)."
                    if route.project_bound
                    else ""
                )
            )

        data = self._request("POST", route.path, dict(payload))
        graph = data.get("prompt")
        if not isinstance(graph, dict) or not graph:
            raise VRGDGError(
                f"VRGDG {kind} build returned no graph. Response keys: "
                + ", ".join(sorted(data))
            )

        seed = data.get("used_seed")
        return VRGDGGraph(
            kind=kind,
            prompt=graph,
            workflow_path=data.get("workflow_path"),
            used_seed=int(seed) if isinstance(seed, (int, float)) else None,
            output_folder=data.get("output_folder"),
            raw={k: v for k, v in data.items() if k != "prompt"},
        )

    # -- discovery -------------------------------------------------------

    def missing_node_types(self, prompt: Mapping[str, Any]) -> dict[str, list[str]]:
        """Class types this graph needs that the server does not expose.

        Returns ``{class_type: [node ids]}``. Checked one class at a time
        against ``/object_info/{class}`` rather than pulling the whole object
        info document, which is many megabytes on a loaded server.
        """
        by_class: dict[str, list[str]] = {}
        for node_id, node in prompt.items():
            if isinstance(node, Mapping):
                class_type = node.get("class_type")
                if isinstance(class_type, str):
                    by_class.setdefault(class_type, []).append(str(node_id))

        missing: dict[str, list[str]] = {}
        for class_type, ids in by_class.items():
            if class_type in self._known_node_types:
                continue
            try:
                response = requests.get(
                    f"{self.server_url}/object_info/{class_type}", timeout=20
                )
                present = response.ok and class_type in (response.json() or {})
            except Exception:
                # Treat an unreachable check as "present" so a flaky probe never
                # blocks a graph that would have run.
                present = True
            if present:
                self._known_node_types.add(class_type)
            else:
                missing[class_type] = sorted(ids, key=_node_sort_key)
        return missing

    def model_root(self) -> dict[str, Any]:
        return self._request("GET", "/vrgdg/workflow_runner/model_root")

    def lora_list(self) -> dict[str, Any]:
        return self._request("GET", "/vrgdg/workflow_runner/lora_list")

    def i2v_choices(self) -> dict[str, Any]:
        return self._request("GET", "/vrgdg/workflow_runner/i2v_choices")

    def model_defaults(self) -> dict[str, Any]:
        """Saved Builder defaults — model names, LoRA stacks, pass sizes.

        Useful as the base payload for a build: it holds the model filenames
        the user actually has, which the shipped templates do not.
        """
        return self._request("GET", "/vrgdg/music_builder/model_defaults")

    # -- project (needed by the project-bound video routes) --------------

    def new_project(self, project_name_or_folder: str) -> dict[str, Any]:
        key = "project_folder" if os.path.isabs(project_name_or_folder) else "project_name"
        return self._request(
            "POST", "/vrgdg/music_builder/new_project", {key: project_name_or_folder}
        )

    def load_session(self, project_folder: str) -> dict[str, Any]:
        return self._request(
            "POST", "/vrgdg/music_builder/load_session", {"project_folder": project_folder}
        )

    def save_session(
        self,
        project_folder: str,
        session: Mapping[str, Any],
        *,
        audio_path: str | None = None,
    ) -> dict[str, Any]:
        """Write a session back.

        Always pass a session obtained from :meth:`load_session` with only known
        keys changed. The file carries ~95 top-level keys and ~110 per segment
        and has no version field, so a hand-built session silently drops state.

        ``audio_path`` must be passed here, at the payload top level, or not at
        all: the server overrides the session's own ``audio_path`` with this
        field on every save (blanking it when absent), and it is also what
        triggers VRGDG's snapshot of the file into the project folder.
        """
        payload: dict[str, Any] = {
            "project_folder": project_folder,
            "session": dict(session),
        }
        if audio_path:
            payload["audio_path"] = str(audio_path)
        return self._request(
            "POST", "/vrgdg/music_builder/save_session", payload
        )

    def save_scene_image(
        self, project_folder: str, scene_number: int, source_path: str
    ) -> dict[str, Any]:
        """Copy an image into a project's approved-stills folder for one scene.

        VRGDG owns the naming (``zimage_approved/image_%04d.png``), so the image
        is handed over by path and the route reports back where it landed.
        ``scene_number`` is 1-based, matching the Builder's own numbering.
        """
        return self._request(
            "POST",
            "/vrgdg/music_builder/save_scene_image",
            {
                "project_folder": project_folder,
                "scene_number": int(scene_number),
                "source_path": str(source_path),
            },
        )

    def analyze_audio(self, audio_path: str, project_folder: str, target_peaks: int = 1600) -> dict[str, Any]:
        return self._request(
            "POST",
            "/vrgdg/music_builder/analyze_audio",
            {
                "audio_path": audio_path,
                "project_folder": project_folder,
                "target_peaks": target_peaks,
            },
        )

    def create_silent_audio(
        self, project_folder: str, duration: float, *, scope: str = "project", scene_number: int | None = None
    ) -> dict[str, Any]:
        """Make a silent bed so a project-bound video route has an audio_path.

        The LTX routes require audio even for a silent shot.
        """
        payload: dict[str, Any] = {
            "project_folder": project_folder,
            "duration": duration,
            "scope": scope,
        }
        if scene_number is not None:
            payload["scene_number"] = scene_number
        return self._request("POST", "/vrgdg/music_builder/create_silent_audio", payload)

    def save_project_srt(self, project_folder: str, srt_text: str) -> dict[str, Any]:
        return self._request(
            "POST",
            "/vrgdg/music_builder/save_project_srt",
            {"project_folder": project_folder, "srt_text": srt_text},
        )

    # -- transport -------------------------------------------------------

    def _request(
        self,
        method: str,
        path: str,
        payload: Mapping[str, Any] | None = None,
        *,
        tolerate_not_ok: bool = False,
    ) -> dict[str, Any]:
        """Call a VRGDG route and normalize its several error conventions."""
        if path in HOST_BOUND_ROUTES:
            raise VRGDGError(
                f"{path} needs a human at the ComfyUI machine (it opens a native "
                f"dialog or a browser) and would hang an unattended run."
            )

        url = f"{self.server_url}{path}"
        try:
            if method == "GET":
                response = requests.get(url, params=payload, timeout=self.timeout)
            else:
                response = requests.post(url, json=payload or {}, timeout=self.timeout)
        except requests.RequestException as exc:
            raise VRGDGError(f"{method} {path} failed: {exc}") from exc

        try:
            data = response.json()
        except ValueError:
            snippet = (response.text or "")[:200]
            raise VRGDGError(
                f"{method} {path} returned {response.status_code} with non-JSON body: {snippet}"
            ) from None

        if not isinstance(data, dict):
            raise VRGDGError(f"{method} {path} returned {type(data).__name__}, expected an object")

        # Storyboard routes error with 500, most others with 400. Either way the
        # body is the useful part, so read it before trusting the status code.
        if data.get("ok") is False and not tolerate_not_ok:
            raise VRGDGError(f"{method} {path}: {data.get('error') or 'route reported failure'}")

        if not response.ok and data.get("ok") is not True:
            raise VRGDGError(
                f"{method} {path} returned HTTP {response.status_code}: "
                f"{data.get('error') or response.reason}"
            )

        return data
