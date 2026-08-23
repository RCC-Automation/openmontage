"""Contract tests for the model registry.

The registry's whole value is that it is right about files whose names lie, so
the fixtures here are built from the tensor-key signatures of the real models on
this machine rather than from plausible-looking names.
"""

from __future__ import annotations

import json
import struct
from pathlib import Path

import pytest

from lib.model_registry import (
    DRIVERS,
    ModelRegistry,
    Verdict,
    classify,
    read_safetensors_header,
    resolve_driver,
    resolve_model_name,
)


# ---------------------------------------------------------------------------
# fixtures: real tensor signatures, minus the weights
# ---------------------------------------------------------------------------

def write_safetensors(path: Path, keys: list[str], metadata: dict | None = None) -> Path:
    """Write a file with a valid safetensors header and no real tensor data."""
    header: dict = {
        k: {"dtype": "F16", "shape": [1], "data_offsets": [0, 2]} for k in keys
    }
    if metadata:
        header["__metadata__"] = metadata
    body = json.dumps(header).encode("utf-8")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(struct.pack("<Q", len(body)) + body + b"\x00\x00")
    return path


# Signatures taken from the installed models, verified by header inspection.
SIGNATURES: dict[str, list[str]] = {
    "z-image": ["cap_embedder.0.weight", "context_refiner.0.attn.qkv.weight",
                "final_layer.adaLN_modulation.1.weight"],
    "flux2": ["double_blocks.0.img_attn.qkv.weight", "single_blocks.0.linear1.weight",
              "double_stream_modulation_img.0.weight", "img_in.weight"],
    "flux1": ["double_blocks.0.img_attn.qkv.weight", "single_blocks.0.linear1.weight",
              "vector_in.in_layer.weight", "guidance_in.in_layer.weight"],
    "chroma": ["double_blocks.0.img_attn.qkv.weight",
               "distilled_guidance_layer.in_proj.weight"],
    "sdxl": ["conditioner.embedders.0.transformer.weight",
             "conditioner.embedders.1.model.ln_final.weight",
             "first_stage_model.decoder.conv_in.weight",
             "model.diffusion_model.input_blocks.0.0.weight"],
    "sd15": ["conditioner.embedders.0.transformer.weight",
             "first_stage_model.decoder.conv_in.weight",
             "model.diffusion_model.input_blocks.0.0.weight"],
    "sam": ["detector.backbone.conv.weight", "detector.segmentation_head.weight",
            "tracker.model.layers.0.weight"],
    "wan": ["patch_embedding.weight", "blocks.0.cross_attn.q.weight"],
    "ltx": ["model.diffusion_model.patchify_proj.weight",
            "model.diffusion_model.adaln_single.emb.weight",
            "model.diffusion_model.av_ca_a2v_gate_adaln_single.weight"],
}


def make(tmp_path: Path, family: str, name: str | None = None, **kw) -> Path:
    return write_safetensors(
        tmp_path / f"{name or family}.safetensors", SIGNATURES[family], **kw
    )


# ---------------------------------------------------------------------------
# reading headers
# ---------------------------------------------------------------------------

class TestReadHeader:
    def test_reads_a_valid_header(self, tmp_path):
        path = make(tmp_path, "z-image")
        header = read_safetensors_header(path)
        assert header is not None
        assert "cap_embedder.0.weight" in header

    def test_truncated_file_reads_as_none(self, tmp_path):
        """A half-finished download must not pass as a usable model."""
        path = tmp_path / "partial.safetensors"
        body = json.dumps({"a.weight": {}}).encode()
        # Claim a long header, then supply almost none of it.
        path.write_bytes(struct.pack("<Q", len(body) * 50) + body)
        assert read_safetensors_header(path) is None

    def test_non_safetensors_reads_as_none(self, tmp_path):
        path = tmp_path / "notes.txt"
        path.write_text("this is not a model", encoding="utf-8")
        assert read_safetensors_header(path) is None

    def test_empty_file_reads_as_none(self, tmp_path):
        path = tmp_path / "empty.safetensors"
        path.write_bytes(b"")
        assert read_safetensors_header(path) is None


# ---------------------------------------------------------------------------
# classification
# ---------------------------------------------------------------------------

class TestClassify:
    @pytest.mark.parametrize(
        "family,expected_modality",
        [
            ("z-image", "image"),
            ("flux2", "image"),
            ("flux1", "image"),
            ("chroma", "image"),
            ("sdxl", "image"),
            ("sd15", "image"),
            ("sam", "segmentation"),
            ("wan", "video"),
            ("ltx", "video"),
        ],
    )
    def test_identifies_each_family(self, tmp_path, family, expected_modality):
        path = make(tmp_path, family)
        verdict = classify(path, read_safetensors_header(path))
        assert verdict.family == family
        assert verdict.modality == expected_modality

    def test_sdxl_and_sd15_split_on_the_second_text_encoder(self, tmp_path):
        sdxl = classify(make(tmp_path, "sdxl"), read_safetensors_header(
            make(tmp_path, "sdxl")))
        sd15 = classify(make(tmp_path, "sd15"), read_safetensors_header(
            make(tmp_path, "sd15")))
        assert sdxl.family == "sdxl"
        assert sd15.family == "sd15"

    def test_refiner_is_read_from_metadata(self, tmp_path):
        path = make(tmp_path, "sdxl", name="refiner", metadata={
            "modelspec.architecture": "stable-diffusion-xl-v1-refiner"})
        verdict = classify(path, read_safetensors_header(path))
        assert verdict.family == "sdxl-refiner"
        assert verdict.role == "refiner"

    def test_filename_never_influences_the_verdict(self, tmp_path):
        """The real trap: names that describe a different model entirely."""
        path = write_safetensors(
            tmp_path / "gonzalomoXLFluxPony_v70PhotoXLDMD.safetensors",
            SIGNATURES["z-image"],
        )
        assert classify(path, read_safetensors_header(path)).family == "z-image"

    def test_unrecognised_architecture_is_unknown_not_guessed(self, tmp_path):
        path = write_safetensors(tmp_path / "mystery.safetensors",
                                 ["some.novel.layer.weight"])
        verdict = classify(path, read_safetensors_header(path))
        assert verdict.family == "unknown"
        assert verdict.confidence == "unknown"

    def test_missing_header_is_unreadable(self, tmp_path):
        path = tmp_path / "stub.safetensors"
        path.write_bytes(b"\x00" * 4)
        assert classify(path, None).family == "unreadable"


class TestBundledCheckpoints:
    """All-in-one files wrap the model beside its encoder and VAE."""

    def test_bundle_is_unwrapped_and_still_identified(self, tmp_path):
        keys = ([f"model.diffusion_model.{k}" for k in SIGNATURES["flux1"]]
                + ["text_encoders.clip_l.transformer.weight",
                   "text_encoders.t5xxl.transformer.weight",
                   "vae.decoder.conv_in.weight"])
        path = write_safetensors(tmp_path / "aio.safetensors", keys)
        verdict = classify(path, read_safetensors_header(path))
        assert verdict.family == "flux1"
        assert verdict.bundled is True
        assert verdict.role == "checkpoint"

    def test_audio_bundle_is_not_mistaken_for_video(self, tmp_path):
        """Regression: ACE-Step hides its vocoder under ``vae.``.

        Unwrapping to the diffusion model first threw away the only proof the
        file was audio, and its inner attention blocks then read as Wan video.
        """
        keys = ["model.diffusion_model.blocks.0.cross_attn.q.weight",
                "model.diffusion_model.patch_embedding.weight",
                "text_encoders.umt5base.transformer.weight",
                "vae.vocoder.conv.weight",
                "vae.dcae.encoder.weight"]
        path = write_safetensors(tmp_path / "ace_step_v1_3.5b.safetensors", keys)
        verdict = classify(path, read_safetensors_header(path))
        assert verdict.family == "ace-step"
        assert verdict.modality == "audio"


# ---------------------------------------------------------------------------
# eligibility
# ---------------------------------------------------------------------------

class TestEligibility:
    def _scan(self, tmp_path, files: dict[str, list[str]]) -> ModelRegistry:
        root = tmp_path / "models"
        for name, keys in files.items():
            write_safetensors(root / "diffusion_models" / name, keys)
        registry = ModelRegistry.load(root, tmp_path / "ledger.json")
        registry.scan()
        return registry

    def test_families_with_a_driver_are_eligible(self, tmp_path):
        registry = self._scan(tmp_path, {
            "a.safetensors": SIGNATURES["z-image"],
            "b.safetensors": SIGNATURES["flux2"],
        })
        assert len(registry.eligible()) == 2

    def test_audio_and_video_are_excluded_with_a_reason(self, tmp_path):
        registry = self._scan(tmp_path, {
            "w.safetensors": SIGNATURES["wan"],
            "s.safetensors": SIGNATURES["sam"],
        })
        excluded = registry.excluded()
        assert len(excluded) == 2
        assert all(reason for reason in excluded.values())
        assert "video" in excluded["diffusion_models/w.safetensors"]

    def test_flux1_is_excluded_for_a_stated_reason_not_silently(self, tmp_path):
        registry = self._scan(tmp_path, {"f.safetensors": SIGNATURES["flux1"]})
        reason = registry.excluded()["diffusion_models/f.safetensors"]
        assert "dual-CLIP" in reason

    def test_unknown_architecture_asks_rather_than_excludes(self, tmp_path):
        registry = self._scan(tmp_path, {"m.safetensors": ["novel.layer.weight"]})
        assert registry.unknown() == ["diffusion_models/m.safetensors"]
        assert registry.eligible() == []

    def test_driver_carries_the_encoder_for_its_family(self, tmp_path):
        registry = self._scan(tmp_path, {"z.safetensors": SIGNATURES["z-image"]})
        driver = registry.driver_for("diffusion_models/z.safetensors")
        assert driver["graph_source"] == "vrgdg_build"
        assert driver["kind"] == "zimage"
        assert driver["clip_type"] == "lumina2"

    def test_sdxl_routes_to_the_bundled_workflow(self, tmp_path):
        root = tmp_path / "models"
        write_safetensors(root / "checkpoints" / "x.safetensors", SIGNATURES["sdxl"])
        registry = ModelRegistry.load(root, tmp_path / "ledger.json")
        registry.scan()
        driver = registry.driver_for("checkpoints/x.safetensors")
        assert driver["graph_source"] == "bundled"
        assert driver["binding"] == "checkpoint_name"


# ---------------------------------------------------------------------------
# persistence and learning
# ---------------------------------------------------------------------------

class TestRegistryLifecycle:
    def _registry(self, tmp_path) -> ModelRegistry:
        root = tmp_path / "models"
        write_safetensors(root / "diffusion_models" / "z.safetensors",
                          SIGNATURES["z-image"])
        registry = ModelRegistry.load(root, tmp_path / "ledger.json")
        registry.scan()
        return registry

    def test_save_and_load_round_trip(self, tmp_path):
        registry = self._registry(tmp_path)
        registry.save()
        reloaded = ModelRegistry.load(registry.models_root, registry.ledger_path)
        assert reloaded.entries == registry.entries

    def test_rescanning_an_unchanged_file_keeps_its_history(self, tmp_path):
        registry = self._registry(tmp_path)
        key = "diffusion_models/z.safetensors"
        registry.record_run(key, ok=True, seconds=41.0)
        counts = registry.scan()
        assert counts["unchanged"] == 1
        assert registry.entries[key]["runs"]["successes"] == 1

    def test_replacing_a_file_reclassifies_it(self, tmp_path):
        registry = self._registry(tmp_path)
        key = "diffusion_models/z.safetensors"
        assert registry.entries[key]["family"] == "z-image"
        write_safetensors(registry.models_root / "diffusion_models" / "z.safetensors",
                          SIGNATURES["wan"])
        counts = registry.scan()
        assert counts["reclassified"] == 1
        assert registry.entries[key]["family"] == "wan"

    def test_a_corrupt_ledger_rebuilds_instead_of_blocking(self, tmp_path):
        ledger = tmp_path / "ledger.json"
        ledger.write_text("{ not json", encoding="utf-8")
        registry = ModelRegistry.load(tmp_path / "models", ledger)
        assert registry.entries == {}

    def test_a_missing_file_is_marked_absent_not_deleted(self, tmp_path):
        registry = self._registry(tmp_path)
        key = "diffusion_models/z.safetensors"
        (registry.models_root / "diffusion_models" / "z.safetensors").unlink()
        registry.scan()
        assert registry.entries[key]["present"] is False
        assert registry.eligible() == []

    def test_key_for_basename_maps_comfyui_names_back(self, tmp_path):
        registry = self._registry(tmp_path)
        assert registry.key_for_basename("z.safetensors") == "diffusion_models/z.safetensors"
        assert registry.key_for_basename("absent.safetensors") is None


class TestLearningFromRuns:
    def _registry(self, tmp_path, family="z-image") -> tuple[ModelRegistry, str]:
        root = tmp_path / "models"
        write_safetensors(root / "diffusion_models" / "m.safetensors",
                          SIGNATURES[family])
        registry = ModelRegistry.load(root, tmp_path / "ledger.json")
        registry.scan()
        return registry, "diffusion_models/m.safetensors"

    def test_a_failure_demotes_an_eligible_model_and_keeps_the_error(self, tmp_path):
        registry, key = self._registry(tmp_path)
        assert registry.entries[key]["eligible"] is True
        registry.record_run(key, ok=False, error="UNETLoader: unknown architecture")
        assert registry.entries[key]["eligible"] is False
        assert "UNETLoader" in registry.entries[key]["reason"]
        assert registry.entries[key]["source"] == "run_outcome"

    def test_a_model_that_has_worked_survives_a_later_failure(self, tmp_path):
        """One transient failure should not condemn a proven model."""
        registry, key = self._registry(tmp_path)
        registry.record_run(key, ok=True, seconds=40.0)
        registry.record_run(key, ok=False, error="server restarted mid-render")
        assert registry.entries[key]["eligible"] is True
        assert registry.entries[key]["runs"]["failures"] == 1

    def test_a_timeout_does_not_condemn_the_model(self, tmp_path):
        """Infrastructure failures say nothing about the model.

        A read timeout while ComfyUI loads several GB of weights is a fact
        about the machine; demoting on it would shrink the usable set every
        time the box was busy.
        """
        registry, key = self._registry(tmp_path)
        registry.record_run(key, ok=False, error=(
            "ComfyUI image generation failed: HTTPConnectionPool("
            "host='127.0.0.1', port=8188): Read timed out. (read timeout=10)"
        ))
        assert registry.entries[key]["eligible"] is True
        assert registry.entries[key]["runs"]["failures"] == 1
        assert registry.entries[key]["runs"]["last_failure_transient"] is True

    def test_a_real_load_failure_still_demotes(self, tmp_path):
        registry, key = self._registry(tmp_path)
        registry.record_run(key, ok=False, error=(
            "UNETLoader: ERROR: Could not detect model type"
        ))
        assert registry.entries[key]["eligible"] is False
        assert registry.entries[key]["runs"]["last_failure_transient"] is False

    def test_success_promotes_an_unknown_model(self, tmp_path):
        registry, key = self._registry(tmp_path)
        registry.entries[key]["eligible"] = None
        registry.record_run(key, ok=True, seconds=12.0)
        assert registry.entries[key]["eligible"] is True
        assert registry.entries[key]["source"] == "run_outcome"

    def test_timing_is_recorded_for_the_render_clock(self, tmp_path):
        registry, key = self._registry(tmp_path)
        registry.record_run(key, ok=True, seconds=41.5)
        assert registry.entries[key]["runs"]["last_seconds"] == 41.5

    def test_recording_an_unknown_key_is_a_no_op(self, tmp_path):
        registry, _ = self._registry(tmp_path)
        registry.record_run("nope.safetensors", ok=False, error="x")  # must not raise

    def test_a_human_verdict_overrides_the_header(self, tmp_path):
        registry, key = self._registry(tmp_path)
        registry.resolve(key, eligible=False, reason="reserved for the hero shot")
        assert registry.entries[key]["eligible"] is False
        assert registry.entries[key]["source"] == "human"
        assert registry.entries[key]["reason"] == "reserved for the hero shot"

    def test_a_human_verdict_can_assign_a_family_and_driver(self, tmp_path):
        registry, key = self._registry(tmp_path)
        registry.resolve(key, eligible=True, family="sdxl")
        assert registry.entries[key]["driver"] == DRIVERS["sdxl"]


class TestNameResolution:
    """Template filenames are the pack author's, not this machine's."""

    INSTALLED_CLIPS = [
        "clip_l.safetensors",
        "qwen3_4b_fp8_scaled.safetensors",
        "t5xxl_fp16.safetensors",
    ]
    INSTALLED_VAES = ["ae.safetensors", "flux2-vae.safetensors", "wan_2.1_vae.safetensors"]

    def test_exact_name_wins(self):
        assert resolve_model_name(
            ["ae.safetensors"], self.INSTALLED_VAES
        ) == "ae.safetensors"

    def test_a_subfolder_path_matches_a_flat_install(self):
        """The Klein template says ``flux\\flux2-vae``; the file sits at the root."""
        assert resolve_model_name(
            ["flux\\flux2-vae.safetensors"], self.INSTALLED_VAES
        ) == "flux2-vae.safetensors"

    def test_punctuation_and_quantisation_suffixes_are_bridged(self):
        """``qwen_3_4b`` must find ``qwen3_4b_fp8_scaled``."""
        assert resolve_model_name(
            ["qwen_3_4b.safetensors"], self.INSTALLED_CLIPS
        ) == "qwen3_4b_fp8_scaled.safetensors"

    def test_earlier_candidates_are_preferred(self):
        assert resolve_model_name(
            ["t5xxl_fp16.safetensors", "clip_l.safetensors"], self.INSTALLED_CLIPS
        ) == "t5xxl_fp16.safetensors"

    def test_no_match_returns_empty_rather_than_a_guess(self):
        """A wrong VAE dies inside VAEDecode minutes in; say so up front."""
        assert resolve_model_name(["nothing_like_this.safetensors"],
                                  self.INSTALLED_VAES) == ""

    def test_empty_install_list_resolves_to_nothing(self):
        assert resolve_model_name(["ae.safetensors"], []) == ""

    def test_resolve_driver_binds_both_slots(self):
        driver = resolve_driver(
            DRIVERS["flux2"], clips=self.INSTALLED_CLIPS, vaes=self.INSTALLED_VAES
        )
        assert driver["clip_name"] == "qwen3_4b_fp8_scaled.safetensors"
        assert driver["vae_name"] == "flux2-vae.safetensors"
        assert driver["clip_type"] == "flux2"

    def test_families_do_not_share_a_vae(self):
        """Z-Image decodes 16 channels, Flux.2 decodes 128."""
        z = resolve_driver(DRIVERS["z-image"], clips=self.INSTALLED_CLIPS,
                           vaes=self.INSTALLED_VAES)
        f = resolve_driver(DRIVERS["flux2"], clips=self.INSTALLED_CLIPS,
                           vaes=self.INSTALLED_VAES)
        assert z["vae_name"] != f["vae_name"]

    def test_bundled_drivers_need_no_resolution(self):
        driver = resolve_driver(DRIVERS["sdxl"], clips=[], vaes=[])
        assert "clip_name" not in driver
        assert driver["graph_source"] == "bundled"


class TestDriverTable:
    def test_every_driver_names_a_known_graph_source(self):
        for family, driver in DRIVERS.items():
            assert driver["graph_source"] in {"vrgdg_build", "bundled"}, family

    def test_vrgdg_drivers_declare_their_encoder_and_vae(self):
        for family, driver in DRIVERS.items():
            if driver["graph_source"] == "vrgdg_build":
                assert driver.get("clip_candidates"), family
                assert driver.get("vae_candidates"), family
                assert driver.get("clip_type"), family
                assert driver.get("kind"), family
