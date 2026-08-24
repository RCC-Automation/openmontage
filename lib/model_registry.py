"""A registry of what every model file on this machine actually is.

ComfyUI lists whatever sits in a folder. It does not say whether a file is an
image generator, an audio model, a segmentation network or a half-finished
download, and filenames lie about all four - ``moodyRealMix_ZIT_V7Global`` is a
Z-Image UNet, ``gonzalomoXLFluxPony_v30FluxDAIO`` is a Flux.1 bundle, and
``ace_step_1.5_turbo_aio`` is audio. Substring rules over filenames get this
wrong in both directions, silently, and each mistake costs a render.

So identity is read from the file itself. A ``.safetensors`` file opens with a
JSON header naming every tensor; the architecture is unmistakable in the key
prefixes, and reading it costs a few hundred KB and no GPU. What the header
cannot settle is left ``unknown`` for a human to answer once.

The registry then answers the question the screen test actually asks: *which
graph source can drive this file* - a VRGDG build route, a bundled workflow, or
nothing at all. A model no route can drive is recorded with that reason rather
than dropped, so the next person sees why it is missing.

Verdicts are re-derived when a file changes (header fingerprint), and corrected
by what happens when a model runs: a candidate that fails to load is demoted
with the error kept, so a wrong guess self-corrects the first time it costs
anything.
"""

from __future__ import annotations

import hashlib
import json
import os
import struct
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable, Mapping

__all__ = [
    "DRIVERS",
    "ModelRegistry",
    "Verdict",
    "classify",
    "default_ledger_path",
    "default_models_root",
    "driver_signature",
    "read_safetensors_header",
    "resolve_driver",
    "resolve_model_name",
]

# A safetensors header is JSON and small; anything larger is not one.
_MAX_HEADER_BYTES = 100 * 1024 * 1024
_SCANNED_FOLDERS = ("checkpoints", "diffusion_models")
_MODEL_SUFFIXES = (".safetensors", ".gguf")


# ---------------------------------------------------------------------------
# what can drive what
# ---------------------------------------------------------------------------

# family -> the graph source that can render it. Keys mirror the three sources
# in .agents/skills/comfyui/SKILL.md. A family absent here has no driver today,
# which is a fact worth recording rather than a reason to hide the file.
#
# Encoder and VAE are *candidate lists*, not fixed names. VRGDG's templates
# reference the pack author's filenames (``qwen_3_4b.safetensors``,
# ``flux\flux2-vae.safetensors``) and this machine has neither; they are
# resolved against what the server reports before a graph is built. Getting this
# wrong is not a clean failure - a 16-channel VAE on a 128-channel latent dies
# inside VAEDecode, several minutes into the render.
DRIVERS: dict[str, dict[str, Any]] = {
    "z-image": {
        "graph_source": "vrgdg_build",
        "kind": "zimage",
        "clip_candidates": ["qwen3_4b_fp8_scaled.safetensors", "qwen_3_4b.safetensors"],
        "clip_type": "lumina2",
        "vae_candidates": ["ae.safetensors"],
    },
    "flux2": {
        "graph_source": "vrgdg_build",
        "kind": "flux_klein",
        "clip_candidates": ["qwen3_4b_fp8_scaled.safetensors", "qwen_3_4b.safetensors"],
        "clip_type": "flux2",
        "vae_candidates": ["flux2-vae.safetensors", "flux\\flux2-vae.safetensors"],
    },
    "sdxl": {
        "graph_source": "bundled",
        "workflow": "juggernaut-xl-ragnarok-txt2img",
        "binding": "checkpoint_name",
        # CheckpointLoaderSimple only lists models/checkpoints, so an SDXL file
        # parked in diffusion_models cannot be loaded however valid it is.
        "requires_folder": "checkpoints",
    },
}


def driver_signature(family: str) -> str:
    """Fingerprint of how a family is driven.

    A demotion is evidence about a model *given the graph we submitted*. Change
    the route, the encoder candidates or the resolution rules and that evidence
    expires - otherwise a bug in our own driver permanently shrinks the usable
    set, and the registry cannot tell the difference between "this model is
    broken" and "we asked for it wrongly once".
    """
    driver = DRIVERS.get(family)
    if not driver:
        return "no-driver"
    payload = json.dumps(driver, sort_keys=True) + f"|resolver={_RESOLVER_VERSION}"
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:12]


# Bump when name resolution itself changes behaviour, not just its inputs.
_RESOLVER_VERSION = 2

# GGUF states its architecture outright, so a quantized sibling is identified
# as confidently as the safetensors original. "lumina2" is Z-Image's.
_GGUF_ARCHITECTURES: dict[str, tuple[str, str]] = {
    "lumina2": ("z-image", "image"),
    "ltxv": ("ltx", "video"),
    "flux": ("flux1", "image"),
    "sdxl": ("sdxl", "image"),
}

# Why a known family still cannot be rendered. Explicit beats a bare False.
_NO_DRIVER_REASON: dict[str, str] = {
    "flux1": "Flux.1 needs a dual-CLIP (t5xxl + clip_l) graph; no VRGDG template has one",
    "chroma": "Chroma is Flux.1-derived; same missing dual-CLIP graph as flux1",
    "sd15": "no bundled SD1.5 workflow; the bundled checkpoint graph is SDXL",
    "sdxl-refiner": "a refiner runs after a base model, it is not a base model",
    "krea2": "route exists but the Krea-2 weights are not downloaded",
    "ernie": "route exists but the ERNIE weights are not downloaded",
}


def _basename(name: str) -> str:
    """Last path component, for names that may carry either separator."""
    return name.replace("\\", "/").rsplit("/", 1)[-1]


def _normalise(name: str) -> str:
    stem = _basename(name).rsplit(".", 1)[0]
    return "".join(ch for ch in stem.lower() if ch.isalnum())


def resolve_model_name(candidates: Iterable[str], installed: Iterable[str]) -> str:
    """Pick the installed file matching one of *candidates*.

    Matching widens in three steps - exact, then ignoring punctuation and case,
    then allowing the candidate to be a prefix of a longer installed name, which
    is how ``qwen_3_4b`` finds ``qwen3_4b_fp8_scaled``. Returns "" when nothing
    matches, so the caller can fail loudly rather than submit a name the server
    will reject.
    """
    installed = list(installed)
    if not installed:
        return ""
    by_normal: dict[str, str] = {}
    for name in installed:
        by_normal.setdefault(_normalise(name), name)

    for candidate in candidates:
        if candidate in installed:
            return candidate
    for candidate in candidates:
        match = by_normal.get(_normalise(candidate))
        if match:
            return match
    for candidate in candidates:
        needle = _normalise(candidate)
        if not needle:
            continue
        for normal, name in by_normal.items():
            if normal.startswith(needle):
                return name
    return ""


def resolve_driver(
    driver: Mapping[str, Any],
    *,
    clips: Iterable[str] = (),
    vaes: Iterable[str] = (),
) -> dict[str, Any]:
    """Return *driver* with its encoder and VAE bound to installed filenames."""
    resolved = dict(driver)
    if driver.get("clip_candidates"):
        resolved["clip_name"] = resolve_model_name(driver["clip_candidates"], clips)
    if driver.get("vae_candidates"):
        resolved["vae_name"] = resolve_model_name(driver["vae_candidates"], vaes)
    return resolved


@dataclass(frozen=True)
class Verdict:
    """What a file is, and how confidently we know it."""

    family: str
    modality: str                      # image | video | audio | segmentation | unknown
    role: str                          # unet | checkpoint | refiner | generator | analysis
    evidence: tuple[str, ...] = ()
    confidence: str = "high"           # high | medium | low | unknown
    bundled: bool = False              # carries its own text encoder + VAE
    container: str = "safetensors"     # safetensors | gguf

    def as_dict(self) -> dict[str, Any]:
        return {
            "family": self.family,
            "modality": self.modality,
            "role": self.role,
            "evidence": list(self.evidence),
            "confidence": self.confidence,
            "bundled": self.bundled,
            "container": self.container,
        }


# ---------------------------------------------------------------------------
# reading the file
# ---------------------------------------------------------------------------


def read_safetensors_header(path: Path) -> dict[str, Any] | None:
    """Return the JSON header of a safetensors file, or None if it is not one.

    The first 8 bytes are a little-endian u64 header length. A truncated
    download usually fails here, which is exactly what we want to detect.
    """
    try:
        with open(path, "rb") as handle:
            raw = handle.read(8)
            if len(raw) < 8:
                return None
            length = struct.unpack("<Q", raw)[0]
            if length == 0 or length > _MAX_HEADER_BYTES:
                return None
            body = handle.read(length)
            if len(body) < length:
                return None              # truncated: the header itself is cut short
            return json.loads(body)
    except (OSError, ValueError):
        return None


def _header_fingerprint(header: Mapping[str, Any]) -> str:
    """Stable hash of the tensor names, so a swapped file re-classifies."""
    names = sorted(k for k in header if k != "__metadata__")
    return hashlib.sha256("\n".join(names).encode("utf-8")).hexdigest()[:16]


def _gguf_architecture(path: Path) -> str | None:
    """Best-effort ``general.architecture`` from a GGUF header.

    Only the string-valued case is decoded; anything else returns None and the
    file is left unknown rather than guessed at.
    """
    try:
        with open(path, "rb") as handle:
            if handle.read(4) != b"GGUF":
                return None
            handle.read(4 + 8 + 8)                   # version, n_tensors, n_kv
            for _ in range(64):                      # architecture is an early key
                raw = handle.read(8)
                if len(raw) < 8:
                    return None
                key = handle.read(struct.unpack("<Q", raw)[0]).decode("utf-8", "replace")
                vtype = struct.unpack("<I", handle.read(4))[0]
                if vtype != 8:                       # 8 == string
                    return None
                value = handle.read(
                    struct.unpack("<Q", handle.read(8))[0]
                ).decode("utf-8", "replace")
                if key == "general.architecture":
                    return value
    except (OSError, ValueError, struct.error):
        return None
    return None


# ---------------------------------------------------------------------------
# classification
# ---------------------------------------------------------------------------


def classify(path: Path, header: Mapping[str, Any] | None) -> Verdict:
    """Identify a model from its header. Never guesses from the filename."""
    if header is None:
        if path.suffix.lower() == ".gguf":
            arch = _gguf_architecture(path)
            if arch:
                family, modality = _GGUF_ARCHITECTURES.get(
                    arch.lower(), (arch.lower(), "unknown")
                )
                return Verdict(
                    family, modality, "unet",
                    (f"gguf general.architecture={arch}",), "medium",
                    container="gguf",
                )
            return Verdict("unknown", "unknown", "unknown",
                           ("gguf header not decodable",), "unknown",
                           container="gguf")
        return Verdict("unreadable", "unknown", "unknown",
                       ("safetensors header missing or truncated",), "high")

    keys = [k for k in header if k != "__metadata__"]
    if not keys:
        return Verdict("unreadable", "unknown", "unknown",
                       ("header declares no tensors",), "high")

    meta = header.get("__metadata__") or {}
    arch = str(meta.get("modelspec.architecture") or "").lower()
    tops = {k.split(".")[0] for k in keys}

    # Judge modality on the *whole* file before unwrapping anything. An
    # ACE-Step bundle keeps its giveaway - the vocoder - under ``vae.``, so
    # stripping to the diffusion model first throws away the only proof it is
    # audio and its inner attention blocks then read as video.
    outer_audio = any("vocoder" in k or "detokenizer" in k for k in keys)
    outer_seg = {"detector", "tracker"} <= tops

    # An all-in-one bundle wraps the diffusion model beside its encoder and VAE.
    # Strip the wrapper and the architecture rules below apply unchanged.
    bundled = {"text_encoders", "vae"} <= tops
    dual_encoder = any(k.startswith("conditioner.embedders.1") for k in keys)
    if bundled:
        inner = [k[len("model.diffusion_model."):] for k in keys
                 if k.startswith("model.diffusion_model.")]
        if inner:
            keys = inner
            tops = {k.split(".")[0] for k in keys}

    def has(needle: str) -> bool:
        return any(needle in k for k in keys)

    def verdict(family, modality, role, why, confidence="high"):
        return Verdict(family, modality, role, tuple(why), confidence, bundled)

    if "refiner" in arch:
        return verdict("sdxl-refiner", "image", "refiner",
                       [f"modelspec.architecture={arch}"])
    if outer_audio or has("detokenizer") or has("vocoder"):
        return verdict("ace-step", "audio", "generator",
                       ["audio codec tensors (detokenizer/vocoder)"])
    if outer_seg:
        return verdict("sam", "segmentation", "analysis",
                       ["detector.* and tracker.*, no diffusion tensors"])
    if has("cap_embedder") or has("context_refiner"):
        return verdict("z-image", "image", "unet",
                       ["cap_embedder / context_refiner (Lumina-style DiT)"])
    if has("distilled_guidance_layer"):
        return verdict("chroma", "image", "unet", ["distilled_guidance_layer"])
    if has("double_stream_modulation") or has("single_stream_modulation"):
        return verdict("flux2", "image", "checkpoint" if bundled else "unet",
                       ["double/single_stream_modulation (Flux.2)"])
    if "double_blocks" in tops and ("vector_in" in tops or "guidance_in" in tops):
        return verdict("flux1", "image", "checkpoint" if bundled else "unet",
                       ["double_blocks with vector_in/guidance_in (Flux.1)"])
    if has("av_ca_") or (has("patchify_proj") and has("adaln_single")):
        return verdict("ltx", "video", "unet",
                       ["patchify_proj + adaln_single with audio/video "
                        "cross-attention (LTX 2.3)"])
    if has("patch_embedding") or has("cross_attn"):
        return verdict("wan", "video", "unet", ["patch_embedding / cross_attn (Wan)"])
    if "conditioner" in tops or dual_encoder:
        return verdict("sdxl" if dual_encoder else "sd15", "image", "checkpoint",
                       ["conditioner.embedders"
                        + (".1 (two text encoders)" if dual_encoder
                           else " (one text encoder)")])
    if has("input_blocks") and has("output_blocks"):
        return verdict("sdxl" if bundled else "sd15", "image", "checkpoint",
                       ["UNet input/output_blocks"], "medium")
    return verdict("unknown", "unknown", "unknown",
                   [f"unrecognised tensor prefixes: {sorted(tops)[:6]}"], "unknown")


def _eligibility(verdict: Verdict) -> tuple[bool | None, str]:
    """Can this be rendered as a screen-test candidate, and why or why not."""
    if verdict.family == "unreadable":
        return False, "file is truncated or not a safetensors file"
    if verdict.confidence == "unknown":
        return None, "architecture not recognised - needs a human verdict"
    if verdict.modality == "unknown":
        # Known family, undetermined purpose - a GGUF whose architecture string
        # decoded but means nothing here. Ask rather than exclude: guessing the
        # wrong way silently drops a usable model.
        return None, f"{verdict.family}: purpose undetermined - needs a human verdict"
    if verdict.modality != "image":
        return False, f"{verdict.modality} model, not an image generator"
    if verdict.role in {"refiner", "analysis"}:
        return False, _NO_DRIVER_REASON.get(verdict.family, f"role is {verdict.role}")
    if verdict.container == "gguf":
        # Quantized weights load through UnetLoaderGGUF. Every VRGDG *image*
        # template uses a plain UNETLoader, so the file is real and identified
        # but nothing here can currently load it.
        return False, ("GGUF weights need a *LoaderGGUF node; the VRGDG image "
                       "templates use UNETLoader")
    if verdict.family in DRIVERS:
        return True, f"{verdict.family} via {DRIVERS[verdict.family]['graph_source']}"
    return False, _NO_DRIVER_REASON.get(
        verdict.family, f"no graph source drives {verdict.family} today"
    )


# ---------------------------------------------------------------------------
# the registry
# ---------------------------------------------------------------------------

# Failures that say nothing about the model. A read timeout while ComfyUI loads
# 4 GB of weights, or a server that went away, is a fact about the machine - and
# demoting a model for it would quietly shrink the usable set every time the box
# was busy.
_TRANSIENT_MARKERS = (
    "timed out",
    "timeout",
    "connection",
    "connectionpool",
    "refused",
    "reset by peer",
    "temporarily unavailable",
    "not reachable",
)


def _is_transient(error: str | None) -> bool:
    lowered = (error or "").lower()
    return any(marker in lowered for marker in _TRANSIENT_MARKERS)


_EMPTY_RUNS: dict[str, Any] = {
    "attempts": 0, "successes": 0, "failures": 0,
    "last_error": None, "last_seconds": None,
}


@dataclass
class ModelRegistry:
    """A persisted record of every model file, refreshed by scanning and by use."""

    models_root: Path
    ledger_path: Path
    entries: dict[str, dict[str, Any]] = field(default_factory=dict)

    @classmethod
    def load(cls, models_root: str | Path, ledger_path: str | Path) -> "ModelRegistry":
        ledger = Path(ledger_path)
        entries: dict[str, dict[str, Any]] = {}
        if ledger.exists():
            try:
                payload = json.loads(ledger.read_text(encoding="utf-8"))
                entries = dict(payload.get("entries") or {})
            except (OSError, ValueError):
                entries = {}             # a corrupt ledger rebuilds, it never blocks
        return cls(Path(models_root), ledger, entries)

    def save(self) -> Path:
        self.ledger_path.parent.mkdir(parents=True, exist_ok=True)
        self.ledger_path.write_text(
            json.dumps(
                {
                    "version": 1,
                    "models_root": str(self.models_root),
                    "entries": self.entries,
                },
                indent=2,
                sort_keys=True,
            ),
            encoding="utf-8",
        )
        return self.ledger_path

    # -- scanning ----------------------------------------------------------

    def scan(self, folders: Iterable[str] = _SCANNED_FOLDERS) -> dict[str, int]:
        """Re-read every model file, preserving verdicts a human or a run settled.

        A file whose header fingerprint is unchanged keeps any human correction
        and any demotion earned by failing. Change the file and it is judged
        afresh, because it is a different model.
        """
        seen: set[str] = set()
        counts = {"scanned": 0, "added": 0, "reclassified": 0, "unchanged": 0,
                  "revived": 0}

        for folder in folders:
            directory = self.models_root / folder
            if not directory.is_dir():
                continue
            for path in sorted(directory.rglob("*")):
                if not path.is_file() or path.suffix.lower() not in _MODEL_SUFFIXES:
                    continue
                key = path.relative_to(self.models_root).as_posix()
                seen.add(key)
                counts["scanned"] += 1

                header = read_safetensors_header(path)
                fingerprint = _header_fingerprint(header) if header else "no-header"
                existing = self.entries.get(key)

                if existing and existing.get("header_fingerprint") == fingerprint:
                    counts["unchanged"] += 1
                    existing["size_bytes"] = path.stat().st_size
                    existing.pop("driver", None)   # migrate: no cached drivers
                    if self._expire_stale_demotion(key, existing):
                        counts["revived"] = counts.get("revived", 0) + 1
                    continue

                verdict = classify(path, header)
                eligible, reason = self._eligibility_for(key, verdict)
                record: dict[str, Any] = {
                    "size_bytes": path.stat().st_size,
                    "header_fingerprint": fingerprint,
                    **verdict.as_dict(),
                    "eligible": eligible,
                    "reason": reason,
                    "source": "header" if header else "file",
                    "runs": dict(_EMPTY_RUNS),
                }
                if existing:
                    record["runs"] = existing.get("runs", dict(_EMPTY_RUNS))
                    counts["reclassified"] += 1
                else:
                    counts["added"] += 1
                self.entries[key] = record

        for key, entry in self.entries.items():
            entry["present"] = key in seen
        return counts

    def _expire_stale_demotion(self, key: str, entry: dict[str, Any]) -> bool:
        """Undo a demotion that was earned under a driver we have since changed.

        Only run-outcome demotions expire. A human verdict is about intent, not
        mechanism, so it stands until the file itself changes.
        """
        if entry.get("source") != "run_outcome" or entry.get("eligible") is not False:
            return False
        family = entry.get("family", "")
        if entry.get("driver_signature") == driver_signature(family):
            return False
        eligible, reason = self._eligibility_for(key, Verdict(
            family,
            entry.get("modality", "unknown"),
            entry.get("role", "unknown"),
            tuple(entry.get("evidence") or ()),
            entry.get("confidence", "high"),
            bool(entry.get("bundled")),
            entry.get("container", "safetensors"),
        ))
        entry["eligible"] = eligible
        entry["reason"] = (
            f"{reason} (earlier failure discarded: it was recorded against a "
            f"different driver)"
        )
        entry["source"] = "header"
        entry.pop("driver_signature", None)
        return True

    @staticmethod
    def _eligibility_for(key: str, verdict: Verdict) -> tuple[bool | None, str]:
        """Eligibility, including requirements that depend on where a file sits."""
        eligible, reason = _eligibility(verdict)
        driver = DRIVERS.get(verdict.family) or {}
        required = driver.get("requires_folder")
        if eligible and required and not key.startswith(f"{required}/"):
            return False, (
                f"{verdict.family} loads from models/{required}/ only; this file "
                f"is in {key.rsplit('/', 1)[0]}/"
            )
        return eligible, reason

    # -- using what it knows ----------------------------------------------

    def eligible(self, family: str | None = None) -> list[str]:
        """Files that can be rendered today."""
        return sorted(
            key for key, e in self.entries.items()
            if e.get("eligible") is True and e.get("present", True)
            and (family is None or e.get("family") == family)
        )

    def unknown(self) -> list[str]:
        """Files needing a human verdict."""
        return sorted(
            key for key, e in self.entries.items()
            if e.get("eligible") is None and e.get("present", True)
        )

    def excluded(self) -> dict[str, str]:
        """Files deliberately not rendered, mapped to the reason."""
        return {
            key: e.get("reason", "")
            for key, e in sorted(self.entries.items())
            if e.get("eligible") is False and e.get("present", True)
        }

    def driver_for(self, key: str) -> dict[str, Any] | None:
        """How to drive this file, read from code rather than from the ledger.

        Deliberately not cached per entry. An earlier version stored a snapshot
        of the driver alongside each model; when the driver changed from fixed
        encoder names to resolved candidates, every stored snapshot kept the old
        hardcoded name and the renders failed on a filename this machine never
        had. Derived data in a persisted cache is a second source of truth, and
        it rots silently.
        """
        entry = self.entries.get(key)
        if not entry:
            return None
        driver = DRIVERS.get(entry.get("family", ""))
        return dict(driver) if driver else None

    def key_for_basename(self, name: str) -> str | None:
        """ComfyUI names models by basename; map one back to a ledger key."""
        for key in self.entries:
            if Path(key).name == name:
                return key
        return None

    # -- learning from what happened --------------------------------------

    def record_run(
        self,
        key: str,
        *,
        ok: bool,
        seconds: float | None = None,
        error: str | None = None,
    ) -> None:
        """Fold the outcome of one render back into the verdict.

        A model classified eligible that has never once succeeded and has just
        failed is demoted: the classification was a claim, and the render is the
        evidence that settles it. The error is kept so the demotion is
        auditable rather than mysterious.
        """
        entry = self.entries.get(key)
        if entry is None:
            return
        runs = entry.setdefault("runs", dict(_EMPTY_RUNS))
        runs["attempts"] = runs.get("attempts", 0) + 1
        if ok:
            runs["successes"] = runs.get("successes", 0) + 1
            if seconds is not None:
                # None means the render worked but was not cleanly timed (the
                # machine was busy). Keep the last real measurement rather than
                # erasing it with a blank.
                runs["last_seconds"] = seconds
            runs["last_error"] = None
            if entry.get("eligible") is None:
                entry["eligible"] = True
                entry["reason"] = "rendered successfully"
                entry["source"] = "run_outcome"
        else:
            runs["failures"] = runs.get("failures", 0) + 1
            runs["last_error"] = error
            runs["last_failure_transient"] = _is_transient(error)
            if (
                runs.get("successes", 0) == 0
                and entry.get("eligible") is not False
                and not _is_transient(error)
            ):
                entry["eligible"] = False
                entry["reason"] = f"failed to render: {error or 'unknown error'}"
                entry["source"] = "run_outcome"
                # Stamp how it was driven, so this verdict expires if we change
                # that rather than outliving the bug that produced it.
                entry["driver_signature"] = driver_signature(entry.get("family", ""))

    def resolve(
        self,
        key: str,
        *,
        eligible: bool,
        family: str | None = None,
        reason: str = "",
    ) -> None:
        """Record a human verdict. Sticky until the file itself changes."""
        entry = self.entries.setdefault(key, {})
        entry["eligible"] = eligible
        entry["source"] = "human"
        entry["confidence"] = "high"
        entry["reason"] = reason or "set by hand"
        entry.setdefault("runs", dict(_EMPTY_RUNS))
        entry.setdefault("present", True)
        if family:
            entry["family"] = family


def default_models_root() -> Path:
    """ComfyUI Desktop's shared model tree (see HANDOFF.md, Paths)."""
    override = os.environ.get("COMFYUI_MODELS_ROOT")
    if override:
        return Path(override)
    return (
        Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local"))
        / "Comfy-Desktop" / "ComfyUI-Shared" / "models"
    )


def default_ledger_path() -> Path:
    return Path(__file__).resolve().parents[1] / "var" / "model_registry.json"
