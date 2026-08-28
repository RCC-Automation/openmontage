"""Standalone ComfyUI API graphs for every image family installed on this machine.

One builder per family, each producing a graph that is submittable as-is AND
loadable in the ComfyUI UI (the frontend opens API-format JSON directly). Node
ids are strings and every node carries a `_meta.title`, so the same file serves
the hand-experiment and the batch run.

The recipes come from ComfyUI's own installed blueprints where one exists, from
a checkpoint's embedded `__metadata__.prompt` where it carries one, and from the
model card otherwise. `MODELS` records which, per model, because a comparison
where the settings vary is only honest if it says so (DECISIONS.md #24).

See wiki/comfyui/image-recipes.md for the measurements behind these.
"""

from __future__ import annotations

from typing import Any

__all__ = ["MODELS", "build", "sdxl", "zimage", "klein", "flux1", "chroma"]

# --------------------------------------------------------------------------
# builders
# --------------------------------------------------------------------------


def _save(node_in: str, prefix: str) -> dict[str, Any]:
    return {"class_type": "SaveImage",
            "inputs": {"images": [node_in, 0], "filename_prefix": prefix},
            "_meta": {"title": "save"}}


def sdxl(*, ckpt: str, prompt: str, negative: str, width: int, height: int,
         seed: int, steps: int, cfg: float, sampler: str, scheduler: str,
         clip_skip: int = -1, loras: tuple[tuple[str, float], ...] = (),
         prefix: str = "bench/sdxl", **_: Any) -> dict[str, Any]:
    """CheckpointLoaderSimple -> KSampler. Encoders and VAE are baked in.

    clip_skip is opt-in and -1 means "leave the node out": measured 2026-08-28,
    CLIPSetLastLayer at -1 is NOT ComfyUI's SDXL default and renders a black
    frame on three of the installed checkpoints.
    """
    clip_src: list[Any] = ["1", 1]
    g: dict[str, Any] = {
        "1": {"class_type": "CheckpointLoaderSimple", "inputs": {"ckpt_name": ckpt},
              "_meta": {"title": "model"}},
        "4": {"class_type": "EmptyLatentImage",
              "inputs": {"width": width, "height": height, "batch_size": 1},
              "_meta": {"title": "latent"}},
        "5": {"class_type": "KSampler",
              "inputs": {"model": ["1", 0], "positive": ["2", 0], "negative": ["3", 0],
                         "latent_image": ["4", 0], "seed": seed, "steps": steps,
                         "cfg": cfg, "sampler_name": sampler, "scheduler": scheduler,
                         "denoise": 1.0}, "_meta": {"title": "sampler"}},
        "6": {"class_type": "VAEDecode", "inputs": {"samples": ["5", 0], "vae": ["1", 2]}},
        "7": _save("6", prefix),
    }
    if clip_skip != -1:
        g["8"] = {"class_type": "CLIPSetLastLayer",
                  "inputs": {"clip": ["1", 1], "stop_at_clip_layer": clip_skip},
                  "_meta": {"title": "clip skip"}}
        clip_src = ["8", 0]
    # A character LoRA has to patch the text encoder too, not just the UNet, or
    # its trigger token means nothing - which is exactly why the native trainer's
    # UNet-only LoRAs top out at 0.46 identity here (DECISIONS #39). So this is
    # LoraLoader, not LoraLoaderModelOnly.
    model_src: list[Any] = ["1", 0]
    for i, (name, strength) in enumerate(loras):
        nid = str(30 + i)
        g[nid] = {"class_type": "LoraLoader",
                  "inputs": {"model": model_src, "clip": clip_src, "lora_name": name,
                             "strength_model": strength, "strength_clip": strength},
                  "_meta": {"title": f"lora {i + 1}"}}
        model_src, clip_src = [nid, 0], [nid, 1]
    g["5"]["inputs"]["model"] = model_src
    g["2"] = {"class_type": "CLIPTextEncode", "inputs": {"text": prompt, "clip": clip_src},
              "_meta": {"title": "positive"}}
    g["3"] = {"class_type": "CLIPTextEncode", "inputs": {"text": negative, "clip": clip_src},
              "_meta": {"title": "negative"}}
    return g


def zimage(*, unet: str, prompt: str, negative: str, width: int, height: int,
           seed: int, steps: int, cfg: float, sampler: str, scheduler: str,
           shift: float = 3.0, clip: str = "qwen3_4b_fp8_scaled.safetensors",
           vae: str = "ae.safetensors", real_negative: bool = False,
           loras: tuple[tuple[str, float], ...] = (),
           prefix: str = "bench/zimage", **_: Any) -> dict[str, Any]:
    """UNETLoader -> [LoRA chain] -> ModelSamplingAuraFlow -> KSampler.

    Shape and settings from ComfyUI's blueprints `Text to Image (Z-Image-Turbo)`
    and `(Z-Image-Base)`. Turbo zeroes the negative; Base takes a real one.
    """
    g: dict[str, Any] = {
        "1": {"class_type": "UNETLoader", "inputs": {"unet_name": unet, "weight_dtype": "default"},
              "_meta": {"title": "model"}},
        "2": {"class_type": "CLIPLoader", "inputs": {"clip_name": clip, "type": "lumina2",
              "device": "default"}, "_meta": {"title": "encoder"}},
        "3": {"class_type": "VAELoader", "inputs": {"vae_name": vae}, "_meta": {"title": "vae"}},
        "4": {"class_type": "CLIPTextEncode", "inputs": {"text": prompt, "clip": ["2", 0]},
              "_meta": {"title": "positive"}},
        "6": {"class_type": "EmptySD3LatentImage",
              "inputs": {"width": width, "height": height, "batch_size": 1},
              "_meta": {"title": "latent"}},
        "7": {"class_type": "ModelSamplingAuraFlow", "inputs": {"model": ["1", 0], "shift": shift},
              "_meta": {"title": "shift"}},
        "8": {"class_type": "KSampler",
              "inputs": {"model": ["7", 0], "positive": ["4", 0], "negative": ["5", 0],
                         "latent_image": ["6", 0], "seed": seed, "steps": steps, "cfg": cfg,
                         "sampler_name": sampler, "scheduler": scheduler, "denoise": 1.0},
              "_meta": {"title": "sampler"}},
        "9": {"class_type": "VAEDecode", "inputs": {"samples": ["8", 0], "vae": ["3", 0]}},
        "10": _save("9", prefix),
    }
    g["5"] = ({"class_type": "CLIPTextEncode", "inputs": {"text": negative, "clip": ["2", 0]},
               "_meta": {"title": "negative"}} if real_negative else
              {"class_type": "ConditioningZeroOut", "inputs": {"conditioning": ["4", 0]},
               "_meta": {"title": "negative (zeroed)"}})
    src = ["1", 0]
    for i, (name, strength) in enumerate(loras):
        nid = str(20 + i)
        g[nid] = {"class_type": "LoraLoaderModelOnly",
                  "inputs": {"model": src, "lora_name": name, "strength_model": strength},
                  "_meta": {"title": f"lora {i + 1}"}}
        src = [nid, 0]
    g["7"]["inputs"]["model"] = src
    return g


def klein(*, unet: str, prompt: str, negative: str, width: int, height: int,
          seed: int, steps: int, cfg: float, sampler: str = "euler",
          clip: str = "qwen3_4b_fp8_scaled.safetensors",
          vae: str = "flux2-vae.safetensors", real_negative: bool = False,
          prefix: str = "bench/klein", **_: Any) -> dict[str, Any]:
    """Flux2Scheduler + SamplerCustomAdvanced. FluxGuidance is a NO-OP on Klein
    (zero guidance_in tensors) and ModelSamplingAuraFlow is inert against
    Flux2Scheduler - neither node belongs here.

    Flux2Scheduler.width/height MUST mirror the latent: the schedule's mu comes
    from width*height/256, and a mismatch degrades quality silently.
    """
    g: dict[str, Any] = {
        "1": {"class_type": "UNETLoader", "inputs": {"unet_name": unet, "weight_dtype": "default"},
              "_meta": {"title": "model"}},
        "2": {"class_type": "CLIPLoader", "inputs": {"clip_name": clip, "type": "flux2",
              "device": "default"}, "_meta": {"title": "encoder"}},
        "3": {"class_type": "VAELoader", "inputs": {"vae_name": vae}, "_meta": {"title": "vae"}},
        "4": {"class_type": "CLIPTextEncode", "inputs": {"text": prompt, "clip": ["2", 0]},
              "_meta": {"title": "positive"}},
        "6": {"class_type": "EmptyFlux2LatentImage",
              "inputs": {"width": width, "height": height, "batch_size": 1},
              "_meta": {"title": "latent"}},
        "7": {"class_type": "Flux2Scheduler",
              "inputs": {"steps": steps, "width": width, "height": height},
              "_meta": {"title": "schedule"}},
        "8": {"class_type": "KSamplerSelect", "inputs": {"sampler_name": sampler},
              "_meta": {"title": "sampler"}},
        "9": {"class_type": "RandomNoise", "inputs": {"noise_seed": seed},
              "_meta": {"title": "seed"}},
        "10": {"class_type": "CFGGuider",
               "inputs": {"model": ["1", 0], "positive": ["4", 0], "negative": ["5", 0], "cfg": cfg},
               "_meta": {"title": "guider"}},
        "11": {"class_type": "SamplerCustomAdvanced",
               "inputs": {"noise": ["9", 0], "guider": ["10", 0], "sampler": ["8", 0],
                          "sigmas": ["7", 0], "latent_image": ["6", 0]}},
        "12": {"class_type": "VAEDecode", "inputs": {"samples": ["11", 0], "vae": ["3", 0]}},
        "13": _save("12", prefix),
    }
    g["5"] = ({"class_type": "CLIPTextEncode", "inputs": {"text": negative, "clip": ["2", 0]},
               "_meta": {"title": "negative"}} if real_negative else
              {"class_type": "ConditioningZeroOut", "inputs": {"conditioning": ["4", 0]},
               "_meta": {"title": "negative (zeroed)"}})
    return g


def flux1(*, prompt: str, negative: str, width: int, height: int, seed: int,
          steps: int, cfg: float, sampler: str, scheduler: str,
          unet: str | None = None, ckpt: str | None = None,
          guidance: float | None = None, vae: str = "ae.safetensors",
          prefix: str = "bench/flux1", **_: Any) -> dict[str, Any]:
    """Flux.1-dev via UNETLoader + DualCLIPLoader, or an all-in-one via
    CheckpointLoaderSimple using its own baked encoders and VAE.

    FluxGuidance is real on flux1-dev (4 guidance_in tensors) but ComfyUI
    already applies a 3.5 default, so passing 3.5 changes nothing - it is a knob
    only off-default. It is a genuine no-op on the AIO, which has none.
    """
    g: dict[str, Any] = {
        "6": {"class_type": "EmptySD3LatentImage",
              "inputs": {"width": width, "height": height, "batch_size": 1},
              "_meta": {"title": "latent"}},
        "8": {"class_type": "KSampler",
              "inputs": {"model": ["1", 0], "positive": ["4", 0], "negative": ["5", 0],
                         "latent_image": ["6", 0], "seed": seed, "steps": steps, "cfg": cfg,
                         "sampler_name": sampler, "scheduler": scheduler, "denoise": 1.0},
              "_meta": {"title": "sampler"}},
        "10": _save("9", prefix),
    }
    if ckpt:
        g["1"] = {"class_type": "CheckpointLoaderSimple", "inputs": {"ckpt_name": ckpt},
                  "_meta": {"title": "model"}}
        clip_src: list[Any] = ["1", 1]
        vae_src: list[Any] = ["1", 2]
    else:
        g["1"] = {"class_type": "UNETLoader", "inputs": {"unet_name": unet, "weight_dtype": "default"},
                  "_meta": {"title": "model"}}
        g["2"] = {"class_type": "DualCLIPLoader",
                  "inputs": {"clip_name1": "clip_l.safetensors",
                             "clip_name2": "t5xxl_fp16.safetensors",
                             "type": "flux", "device": "default"}, "_meta": {"title": "encoder"}}
        g["3"] = {"class_type": "VAELoader", "inputs": {"vae_name": vae}, "_meta": {"title": "vae"}}
        clip_src, vae_src = ["2", 0], ["3", 0]
    g["4"] = {"class_type": "CLIPTextEncode", "inputs": {"text": prompt, "clip": clip_src},
              "_meta": {"title": "positive"}}
    g["5"] = {"class_type": "ConditioningZeroOut", "inputs": {"conditioning": ["4", 0]},
              "_meta": {"title": "negative (zeroed)"}}
    g["9"] = {"class_type": "VAEDecode", "inputs": {"samples": ["8", 0], "vae": vae_src}}
    if guidance is not None:
        g["12"] = {"class_type": "FluxGuidance",
                   "inputs": {"conditioning": ["4", 0], "guidance": guidance},
                   "_meta": {"title": "flux guidance"}}
        g["8"]["inputs"]["positive"] = ["12", 0]
    return g


def chroma(*, unet: str, prompt: str, negative: str, width: int, height: int,
           seed: int, steps: int, cfg: float, sampler: str, scheduler: str,
           shift: float = 1.0, vae: str = "ae.safetensors",
           prefix: str = "bench/chroma", **_: Any) -> dict[str, Any]:
    """Single T5 through CLIPLoader type 'chroma', ModelSamplingAuraFlow shift
    1.0 (NOT ModelSamplingFlux). Chroma restores real CFG, so the negative is
    live - and is dead at the author's own recommended cfg 1.0.
    """
    return {
        "1": {"class_type": "UNETLoader", "inputs": {"unet_name": unet, "weight_dtype": "default"},
              "_meta": {"title": "model"}},
        "2": {"class_type": "CLIPLoader", "inputs": {"clip_name": "t5xxl_fp16.safetensors",
              "type": "chroma", "device": "default"}, "_meta": {"title": "encoder"}},
        "3": {"class_type": "VAELoader", "inputs": {"vae_name": vae}, "_meta": {"title": "vae"}},
        "4": {"class_type": "CLIPTextEncode", "inputs": {"text": prompt, "clip": ["2", 0]},
              "_meta": {"title": "positive"}},
        "5": {"class_type": "CLIPTextEncode", "inputs": {"text": negative, "clip": ["2", 0]},
              "_meta": {"title": "negative"}},
        "6": {"class_type": "EmptySD3LatentImage",
              "inputs": {"width": width, "height": height, "batch_size": 1},
              "_meta": {"title": "latent"}},
        "7": {"class_type": "ModelSamplingAuraFlow", "inputs": {"model": ["1", 0], "shift": shift},
              "_meta": {"title": "shift"}},
        "8": {"class_type": "KSampler",
              "inputs": {"model": ["7", 0], "positive": ["4", 0], "negative": ["5", 0],
                         "latent_image": ["6", 0], "seed": seed, "steps": steps, "cfg": cfg,
                         "sampler_name": sampler, "scheduler": scheduler, "denoise": 1.0},
              "_meta": {"title": "sampler"}},
        "9": {"class_type": "VAEDecode", "inputs": {"samples": ["8", 0], "vae": ["3", 0]}},
        "10": _save("9", prefix),
    }


_BUILDERS = {"sdxl": sdxl, "zimage": zimage, "klein": klein, "flux1": flux1, "chroma": chroma}


def build(spec: dict[str, Any], **overrides: Any) -> dict[str, Any]:
    """Build the graph for one MODELS entry, with any field overridden."""
    merged = {**spec, **overrides}
    return _BUILDERS[merged["family"]](**merged)


# --------------------------------------------------------------------------
# the pool - 18 models, each with the recipe it actually wants
# --------------------------------------------------------------------------
#
# `source` records where the recipe came from, and is printed beside every
# result. "blueprint" = ComfyUI's own installed template; "embedded" = the
# checkpoint's __metadata__.prompt; "card" = the model card; "family" = the
# family default where the author published nothing.

MODELS: list[dict[str, Any]] = [
    # ---- SDXL, 7 -----------------------------------------------------------
    dict(key="juggernautXL_ragnarok", family="sdxl", label="Juggernaut XL Ragnarok",
         ckpt="juggernautXL_ragnarok.safetensors", steps=30, cfg=4.5,
         sampler="dpmpp_2m_sde", scheduler="karras", source="card"),
    dict(key="babesByStableYogi_v65", family="sdxl", label="Babes by Stable Yogi v6.5 (Pony)",
         ckpt="babesByStableYogi_v65FP16.safetensors", steps=28, cfg=6.0,
         sampler="euler_ancestral", scheduler="karras", source="card"),
    dict(key="babesIllustrious_v50", family="sdxl", label="Babes Illustrious v5.0",
         ckpt="babesIllustriousBy_v50BF16.safetensors", steps=27, cfg=4.5,
         sampler="dpmpp_2m_sde", scheduler="karras", source="card"),
    dict(key="realismIllustrious_v50", family="sdxl", label="Realism Illustrious v5.0",
         ckpt="realismIllustriousBy_v50FP16.safetensors", steps=27, cfg=5.0,
         sampler="dpmpp_2m_sde", scheduler="karras", source="card"),
    dict(key="gonzalomo_v60_DMD", family="sdxl", label="GonzaLomo v6.0 PhotoXL DMD",
         ckpt="gonzalomoXLFluxPony_v60PhotoXLDMD.safetensors", steps=10, cfg=1.0,
         sampler="lcm", scheduler="karras", source="embedded"),
    dict(key="mop_v71_DMD", family="sdxl", label="MoP v7.1 DMD",
         ckpt="mopMixtureOfPerverts_v71.safetensors", steps=11, cfg=1.0,
         sampler="lcm", scheduler="karras", source="embedded"),
    dict(key="gonzalomo_v70_DMD", family="sdxl", label="GonzaLomo v7.0 PhotoXL DMD",
         ckpt="gonzalomoXLFluxPony_v70PhotoXLDMD.safetensors", steps=13, cfg=1.0,
         sampler="lcm", scheduler="beta", source="embedded"),
    # ---- Z-Image, 6 --------------------------------------------------------
    dict(key="zImageTurbo", family="zimage", label="Z-Image Turbo (reference)",
         unet="zImageTurbo_turbo.safetensors", steps=8, cfg=1.0,
         sampler="res_multistep", scheduler="simple", source="blueprint"),
    dict(key="darkBeast30", family="zimage", label="darkBeast30 (Turbo merge)",
         unet="darkBeast30BF16INT8_dbzit9DIMRclaw.safetensors", steps=8, cfg=1.0,
         sampler="res_multistep", scheduler="simple", source="embedded"),
    dict(key="zImageUltimateNSFW", family="zimage", label="Z-Image Ultimate v2.0",
         unet="zImageUltimateNSFW_v20.safetensors", steps=8, cfg=1.0,
         sampler="res_multistep", scheduler="simple", source="family"),
    dict(key="moodyRealMix", family="zimage", label="moodyRealMix ZIT V7",
         unet="moodyRealMix_ZIT_V7Global.safetensors", steps=8, cfg=1.0,
         sampler="res_multistep", scheduler="simple", source="family"),
    dict(key="gonzalomoZpop_v40", family="zimage", label="GonzaLomo ZPop v4.0",
         unet="gonzalomoZpop_v40.safetensors", steps=9, cfg=1.0,
         sampler="res_multistep", scheduler="beta", source="embedded"),
    dict(key="zImageBase", family="zimage", label="Z-Image BASE",
         unet="z_image_base_bf16.safetensors", steps=25, cfg=4.0,
         sampler="res_multistep", scheduler="simple", real_negative=True,
         source="blueprint"),
    # ---- FLUX.2 Klein, 2 ---------------------------------------------------
    dict(key="klein_distilled", family="klein", label="FLUX.2 Klein 4B distilled",
         unet="flux-2-klein-4b-fp8.safetensors", steps=4, cfg=1.0, source="card"),
    dict(key="klein_base", family="klein", label="FLUX.2 Klein 4B BASE",
         unet="flux-2-klein-base-4b.safetensors", steps=20, cfg=5.0,
         real_negative=True, source="blueprint"),
    # ---- Flux.1, 2 ---------------------------------------------------------
    dict(key="flux1_dev", family="flux1", label="FLUX.1 dev",
         unet="flux1-dev.safetensors", steps=20, cfg=1.0, sampler="euler",
         scheduler="simple", guidance=3.5, source="blueprint", heavy=True),
    dict(key="flux_aio", family="flux1", label="GonzaLomo FluxDAIO (schnell-class)",
         ckpt="gonzalomoXLFluxPony_v30FluxDAIO.safetensors", steps=10, cfg=1.0,
         sampler="euler", scheduler="beta", source="embedded", heavy=True),
    # ---- Chroma, 1 ---------------------------------------------------------
    dict(key="chroma_v30", family="chroma", label="GonzaLomo Chroma v3.0",
         unet="gonzalomoChroma_v30.safetensors", steps=26, cfg=3.5,
         sampler="euler", scheduler="beta", source="card"),
]
