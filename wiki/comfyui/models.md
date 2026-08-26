---
title: Models — what is installed, what can drive it, what can be trained
status: measured
updated: 2026-08-26
sources: [this-machine.md, graph-sources.md, ../../lib/model_registry.py, https://huggingface.co/black-forest-labs/FLUX.2-klein-base-4B, https://huggingface.co/Comfy-Org/z_image]
---

Every model file under `ComfyUI-Shared\models\`, read from its **safetensors
header** and never from its name, with the graph source that can drive it and
the reason when nothing can. The ledger is `var/model_registry.json` (gitignored,
rebuilt by `ModelRegistry.scan()`); this page is the human-readable state of it
on 2026-08-26, 34 files.

The rule that decides everything here (`DECISIONS.md` #18): **identity comes
from the file, not the filename.** `moodyRealMix_ZIT_V7Global` and
`darkBeast30BF16INT8_dbzit9DIMRclaw` are Z-Image UNets; `gonzalomoXLFluxPony_v30FluxDAIO`
is a Flux.1 bundle; `ace_step_1.5_turbo_aio` is audio. Nothing in those names
would tell you.

---

## Image generators that can run here

| family | files | driven by | encoder · VAE |
|---|---|---|---|
| **SDXL** | 6 usable checkpoints: `juggernautXL_ragnarok` (cast for the character work), `babesByStableYogi_v65`, `babesIllustriousBy_v50`, `gonzalomoXLFluxPony_v60PhotoXLDMD`, `mopMixtureOfPerverts_v71`, `realismIllustriousBy_v50` | bundled `juggernaut-xl-ragnarok-txt2img` workflow, `CheckpointLoaderSimple` | baked into the checkpoint |
| **Z-Image** | 6 usable: `z_image_base_bf16` (**Base**, new), `zImageTurbo_turbo`, `darkBeast30BF16INT8`, `moodyRealMix_ZIT_V7Global`, `gonzalomoZpop_v40`, `zImageUltimateNSFW_v20` | VRGDG `zimage` route | `qwen3_4b_fp8_scaled` · `ae.safetensors` (16-channel) |
| **FLUX.2 Klein** | 2: `flux-2-klein-base-4b` (**Base**, new), `flux-2-klein-4b-fp8` | VRGDG `flux_klein` route, multi-reference via `images` | `qwen3_4b_fp8_scaled` · `flux2-vae` (128-channel) |

**There is no single encoder or VAE for a mixed sweep.** Z-Image decodes 16
channels through `ae.safetensors`, Flux.2 decodes 128 through `flux2-vae`;
force one on the other and `VAEDecode` fails minutes into the render with a
channel-count error that names neither model (`DECISIONS.md` #20). The
registry carries per-family candidates and resolves them against the server.

## Trainable or not — and this is a different question

A file that renders is not a file that trains. LoRA training needs the base
weights in bf16/fp16; quantised and GGUF files are inference-only. Read the
header: count the dtypes and look for `_quantization_metadata`.

| file | header says | verdict |
|---|---|---|
| `flux-2-klein-base-4b.safetensors` | 149 tensors, **all BF16**, no quantization metadata, 0 guidance tensors | **trainable Base** (7,751,105,712 bytes, byte-verified against HF) |
| `flux-2-klein-4b-fp8.safetensors` | 80 tensors `float8_e4m3fn`, `_quantization_metadata` present | inference only |
| `z_image_base_bf16.safetensors` | 453 tensors, **all BF16**, no quantization metadata | **trainable Base** (12,309,866,400 bytes, byte-verified) |
| `darkBeast30BF16INT8…`, the ZPop GGUFs | INT8 / GGUF | inference only |
| `juggernautXL_ragnarok.safetensors` | fp16 SDXL checkpoint | **trainable** — and the one LoRA actually trained here so far ([lora-training](../character/lora-training.md)) |

So as of 2026-08-26 **all three engine lines have trainable base weights on
disk**. Sources: Klein Base from `black-forest-labs/FLUX.2-klein-base-4B`
(not gated); Z-Image Base from `Comfy-Org/z_image` — the repo created
2026-01-27, the day before the Base release, as against `Comfy-Org/z_image_turbo`
from November; same byte size, different weights, different filenames.

## Installed but not drivable, with the reason recorded

| family | files | why |
|---|---|---|
| Flux.1 / Chroma | `flux1-dev` (23.8 GB), `gonzalomoXLFluxPony_v30FluxDAIO` (17.1 GB), `gonzalomoChroma_v30` | need a dual-CLIP (t5xxl + clip_l) graph; no VRGDG template has one |
| SDXL, wrong folder | `gonzalomoXLFluxPony_v70PhotoXLDMD` | valid checkpoint sitting in `diffusion_models/`; `CheckpointLoaderSimple` lists `checkpoints/` only. Move it and it becomes a seventh SDXL |
| SDXL refiner | `sd_xl_refiner_1.0` | runs after a base; not a base |
| Z-Image GGUF | `gonzalomoZPop_v40_BF16.gguf`, `_Q6_K.gguf` | need a `*LoaderGGUF` node; the VRGDG image templates use `UNETLoader` |
| video | 5 Wan, 2 LTX (the LTX pair is what the Builder's video routes use) | not image generators |
| audio | 3 ACE-Step | not image generators |
| analysis | `sam3.1_multiplex_fp16` | segmentation |
| unknown | `minimax_h3_fl2va_pruned_int8_convrot` (21 GB) | architecture not recognised — needs a human verdict |
| unreadable | `minimax_h3_ref2va_pruned_int8_convrot` | 0 bytes: a failed download, not a model |

## Adapters and LoRAs

| | where | note |
|---|---|---|
| IP-Adapter FaceID PlusV2 SDXL | `ipadapter/` (adapter) **and** `loras/` (its LoRA — must be in both, see traps) | measured on [faceid-on-this-machine](../character/faceid-on-this-machine.md) |
| InsightFace `buffalo_l` | `insightface/models/` | detection + ArcFace, CPU provider only |
| CLIP-ViT-H | `clip_vision/CLIP-ViT-H-14-laion2B-s32B-b79K.safetensors` | the loader matches on this exact long name |
| LTX LoRAs incl. MSR V1/V2 | `loras/`, `loras/LTX/`, `loras/licon/` | Builder video modes |
| `character/wrenx_smoke_200_steps_00001_.safetensors` | `loras/character/` | the first LoRA trained here; a throwaway |
| ControlNet (any family), InstantID | **absent** — `controlnet/` is empty | `ZImageFunControlnet` node exists without its `model_patch` file |

---

## Traps

**A download in progress already appears in the loader dropdowns** — and in
our own registry as `eligible`, because the safetensors header sits at the
start of the file and parses long before the weights exist. The dropdown means
"a file with this name exists". Trust the byte count against the server's
`Content-Length`; rescan the registry after a download finishes so
`size_bytes` is right.

**`[part]` from the VRGDG installer can mean a finished file**, and a finished
byte count can be a truncated file — see `HANDOFF.md` for both directions.
`curl -sIL` for the size, then compare.

**Template model names are the pack author's, not yours.** Every VRGDG image
route takes `unet_name` / `clip_name` / `vae_name` from the payload;
`GET /vrgdg/music_builder/model_defaults` returns what actually works here.

**A checkpoint that looks broken may be mis-driven.** Two SDXL files here
(DMD in the name) want CFG ~1 and ~10 steps and return posterised garbage at
CFG 4.5 / 35. `lib/model_registry.infer_sampler_recipe` reads the recipe six
of the checkpoints embed in `__metadata__.prompt` (`DECISIONS.md` #24).

**Never cache anything derived from code in the ledger** (`DECISIONS.md` #22).
The registry once cached each family's driver and served a filename the
machine never had for three sweeps running.

## Open questions

- What is `minimax_h3_fl2va_pruned_int8_convrot`? 21 GB, header not
  recognised. `ModelRegistry.resolve(key, eligible=...)` records the verdict.
- Is `gonzalomoXLFluxPony_v70` worth moving into `checkpoints/`? It would be
  the seventh SDXL candidate at zero cost.
