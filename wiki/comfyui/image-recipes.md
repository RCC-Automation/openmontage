---
title: Driving each image family — the recipes, and what they cost
status: measured
updated: 2026-08-29
sources: [models.md, this-machine.md, graph-sources.md, "C:/Users/Barrul/AppData/Local/Comfy-Desktop/ComfyUI-Installs/ComfyUI/ComfyUI/blueprints/", https://huggingface.co/Tongyi-MAI/Z-Image-Turbo, https://huggingface.co/black-forest-labs/FLUX.2-klein-base-4B]
---

Every image family installed here, driven through a **standalone API graph**
rather than a VRGDG route, with the settings each family actually wants and what
a render costs. Measured 2026-08-28/29: 25 renders at 1280×720 plus a sixth family added on
the 29th, one prompt, seed 7777.

A reader's overview of all of this — the pool, the axis matrix, the
recommendations and the gaps — is compiled at
[`docs/image-bench.html`](../../docs/image-bench.html) ("Twenty Models, One
Bench"). This page is the authority if the two disagree.

The recipes are not ours. ComfyUI ships **official blueprints** for most of them
in its install (`blueprints/Text to Image (Z-Image-Turbo).json` and siblings);
those are the authority, and they disagree with several community workflows on
this machine. Read the blueprint before inventing a graph.

---

## What we know

### The pool is 19 models, in six families

| family | models | driven by |
|---|---|---|
| SDXL | 6 usable + 1 in the wrong folder | `CheckpointLoaderSimple` |
| Z-Image | **5 Turbo-derived + 1 Base** | `UNETLoader` + `CLIPLoader type: lumina2` |
| FLUX.2 Klein | 2 — distilled fp8, Base bf16 | `UNETLoader` + `CLIPLoader type: flux2` |
| Flux.1 | 2 — `flux1-dev`, the FluxDAIO all-in-one | `DualCLIPLoader type: flux` / `CheckpointLoaderSimple` |
| Chroma | 1 | `UNETLoader` + `CLIPLoader type: chroma` |
| Qwen-Image | 1 — 2512 Lightning | `UNETLoader` + `CLIPLoader type: qwen_image` |

Both Z-Image GGUFs are **not** in that count — see Traps.

### The recipes

| family / file | steps | cfg | sampler · scheduler | shift | negative |
|---|---|---|---|---|---|
| **Z-Image Turbo** (5 files) | 8 | 1.0 | `res_multistep` · `simple` | `ModelSamplingAuraFlow` **3** | zeroed — inert |
| **Z-Image Base** | 25–30 | 3–5 | `res_multistep` · `simple` | **3** | **real, and it works** |
| **Klein distilled** | 4 | 1.0 | `euler` · `Flux2Scheduler` | — | zeroed |
| **Klein Base** | 20 | 5.0 | `euler` · `Flux2Scheduler` | — | **real** |
| **flux1-dev** | 20 | 1.0 | `euler` · `simple` | built-in 1.15 | zeroed; guidance 3.5 instead |
| **FluxDAIO** | 10 | 1.0 | `euler` · `beta` | built-in 1.0 | inert at cfg 1 |
| **Chroma** | 26 | 3.5 | `euler` · `beta` | `ModelSamplingAuraFlow` **1.0** | **real — the point of the model** |
| **Qwen-Image 2512** | 4 | **1.0** | `euler` · `simple` | none | real, but inert at cfg 1 |

Z-Image and Chroma both take `ModelSamplingAuraFlow`, at different shifts.
Klein takes neither shift node — `Flux2Scheduler` computes the schedule from
width and height and the shift patch is inert against it.

### What it costs, at 1280×720

| model | recipe | warm | cold |
|---|---|---|---|
| `klein-4b-fp8` | 4 steps | **10.6 s** | 26.3 s |
| Z-Image Turbo family | 8 steps | **14.1 s** | 39–77 s |
| `flux1-dev` | 20 steps | **52.6 s** | 148 s |
| `klein-base-4b` | 20 steps, cfg 5 | 58.9 s | 66.4 s |
| `gonzalomoChroma_v30` | 12 steps, cfg 1 | — | 78.3 s |
| `FluxDAIO` | 10 steps | — | 81.3 s |
| `z_image_base_bf16` | 25 steps, cfg 4 | — | 105.4 s |
| `gonzalomoChroma_v30` | 26 steps, cfg 3.5 | — | 142.5 s |
| `qwen_image_2512` (1664×928) | 4 steps, cfg 1.0 | **24.2 s** | 85.9 s |
| `klein-base-4b` | 50 steps, cfg 4 | — | 129.5 s |

Cold includes the weight load and is the number that dominates a sweep: order
renders **by model**, not by prompt.

Qwen is timed at **1664×928 (1.54 MP)**, its native 16:9 bucket, against
1280×720 (0.92 MP) for everything else — so its 24.2 s is doing 1.7× the pixels
and is not directly comparable to the rows above it.

### Three findings that change what to reach for

**The standalone Z-Image graph renders in 14.1 s warm** — measured on five
back-to-back runs across two Turbo files (zImageTurbo, darkBeast30), varying only
the seed. The first render after a model swap costs 50–77 s, so the weight load,
not the sampling, is what a sweep pays for.

For scale, the VRGDG `zimage` route logs a **60.6 s median (n=62)**. That is not
a like-for-like ratio and should not be quoted as one: the route is a two-pass
flow that renders 1280×720 and then again at 1920×1080 — roughly 2.7× the pixels
plus a second pass — and its median mixes cold and warm runs. What is fair to say
is that a single-pass still at 1280×720 costs 14 s here, and anything quoting 60 s
for a Z-Image still is measuring a different job.

**Klein is a third of its reputation.** The 28 s on record came from VRGDG's
template at 8 steps `dpmpp_sde`. At the 4-step `euler` recipe it renders in
**10.6 s** — the cheapest good model on the machine. That 4-step recipe comes
from BFL's model card for the *distilled* file, not from a local blueprint: the
only Klein blueprint installed here is `Image Edit (Flux.2 Klein 4B).json`, which
covers **Base** at 20 steps / cfg 5.

**CFG is not free anywhere.** Klein has no guidance embedder, so cfg > 1 runs a
genuine second pass: 30.3 s → 58.9 s at identical steps. The same doubling
applies to Z-Image Base and to Chroma.

**And cfg 1.0 costs something other than speed.** Ten of the nineteen models run
there — the three DMD SDXL checkpoints, all five Z-Image Turbo merges, Klein
distilled and the FluxDAIO — and at cfg exactly 1.0 ComfyUI never evaluates the
negative branch at all. Those ten have no working negative prompt, which is the
only free fix for the subject-count problem. See
[practice/prompting](../practice/prompting.md).

### Qwen-Image is the sixth family, and it is here for adherence

Added 2026-08-29 for the one thing the other five are weak at: following
instructions about framing, counts and composition. Measured on this machine —
correct count and attribute binding on "exactly three women, red then yellow then
blue, left to right", and the **only model in the pool that renders legible
text**. It is not a casting tool: on a character brief it scored 0.399, eighth of
nineteen ([character/what-we-measured](../character/what-we-measured.md)).

Its encoder is **Qwen2.5-VL-7B — a full vision-language model, not a CLIP**,
which is where the adherence comes from and why it costs 9.4 GB on its own.
Total resident ~30 GB.

### Which knobs are real, per family

The axes are **per family**, not global — the single most important fact for
anyone building a sweep over these.

| axis | SDXL | Z-Image | Klein | Flux.1 / Chroma |
|---|---|---|---|---|
| text encoder | impossible — baked in, no standalone `clip_g` here | **real**: `qwen3_4b_fp8` vs the int8 `LLMForZ` | possible, untested | `t5xxl_fp16` only |
| VAE | pointless — baked in. A research pass reports 5 of 7 bake the fp16-fix VAE and 2 the original SDXL 1.0 one; **we have not verified that here** | **real**: `ae` vs `ultrafluxVAEImproved`, both 16-channel | impossible — `flux2-vae` only | real, same 16-ch pair |
| LoRA | 1 (Stable Yogi Realism) | **6 — the strongest single knob** | none installed, none borrowable | none installed |
| CLIP skip | **destructive if set to -1** — see Traps. ComfyUI's SDXL default already equals -2 | n/a | n/a | n/a |
| quantization | — | dead, both GGUFs refuse | fp8 vs bf16 — changes the image | fp8 upcast in RAM anyway |

`Z-Detail-Slider` at 1.0 transforms a Z-Image frame: heavy skin texture, darker,
grittier. The encoder swap shifts freckling and framing. The VAE swap is subtle
and decode-only — but note **Zpop's own author renders through UltraFlux**, so
it is the intended pairing for that merge, not an experiment.

---

## What it costs

A one-prompt sheet across all 19 models is roughly **30 minutes** including cold
loads. Seven prompts is about 2.5 hours if ordered by model. See
[the image benchmark](../practice/image-benchmark.md).

---

## Traps

**The Q6_K Z-Image GGUF does not load.** `UnetLoaderGGUF` fails on
`gonzalomoZPop_v40_Q6_K.gguf` with a `load_state_dict` key mismatch — measured,
against a research pass that recommended benchmarking it. The **BF16 GGUF is
untested**; it duplicates the safetensors, so there is little reason to try it
beyond measuring the dequant path itself.

**ComfyUI returns a cached result for an identical graph.** Submitting the same
graph twice comes back in ~2.0 s having rendered nothing. A benchmark harness
that does not vary the seed between cells records fictional timings that look
like a breakthrough. Vary `KSampler.seed` or `RandomNoise.noise_seed` on every
submission, including repeat timings of the "same" config.

**Z-Image Base at the Turbo recipe looks like a broken model.** Blonde, waxy,
painterly. At its own recipe the same file produces the best frame of the
session. This is [DECISIONS #24](../../DECISIONS.md) reproducing on a second
family — see [mis-driven checkpoints](failure-modes.md).

**Chroma's selling point is off at its author's own settings.** Chroma exists to
restore real CFG and working negative prompts to a schnell-derived model. Its
author recommends cfg 1.0–1.3, and at cfg 1.0 ComfyUI never evaluates the
negative branch. Measured both ways, the stock 26-step cfg-3.5 render is visibly
richer for 1.8× the time.

**`FluxGuidance` is a no-op on Klein and on the FluxDAIO.** Both have zero
`guidance_in` tensors, so `model_detection.py` sets `guidance_embed=False` and
the model skips the embedding. It *is* real on `flux1-dev` (4 guidance tensors) —
but ComfyUI already applies a 3.5 default, so adding the node at 3.5 changes
nothing. It is a knob only off-default.

**`Flux2Scheduler.width`/`height` must match the latent.** The schedule's mu is
computed from `width * height / 256`. Mismatch them and the noise schedule is
built for the wrong sequence length: quality degrades silently, no error.

**A recipe only transplants into a graph of the same shape.** None of these
belong in VRGDG's two-pass `zimage` route, which already rejected a foreign
recipe with speckle artefacts. See [DECISIONS #25](../../DECISIONS.md).

**`CLIPSetLastLayer` at −1 is not a no-op, and it is not the SDXL default.**
Adding the node at `stop_at_clip_layer: -1` renders a **pure black frame** on
`babesIllustriousBy_v50`, `realismIllustriousBy_v50` and `mopMixtureOfPerverts_v71`
— mean luma 0.00, reproduced across three seeds and at each model's own sampler
recipe. Juggernaut is unaffected.

The reason, measured by pixel hash: **ComfyUI's default SDXL conditioning is
already equivalent to −2.** A render with no node, a render at `-2`, and the
original pre-2026-08-28 graph are all **pixel-identical**; only `-1` differs. So
`-1` does not mean "no skip" for SDXL — it forces the true final CLIP layer,
which is degenerate in these three merges.

This corrects a claim made earlier the same day, that "every SDXL render this
project has made ran at clip skip −1 and three checkpoints have never been driven
correctly." They were being driven correctly all along. `comfyui_image` now
leaves the node out of the graph entirely unless a skip is asked for, so the
default path is byte-identical to what it always was; the binding exists for
deliberate excursions to −3 or −4, which one installed author varies for effect.

---

## Open questions

- Does the int8 `LLMForZ` encoder change Klein output the way it changes
  Z-Image? The dispatch is correct in code; never rendered.
- Is the FluxDAIO worth benchmarking at all, given its own merge graph shows it
  is 30% `gonzalomoChroma_v30`? The two are not independent samples.
- What do the five Turbo-derived Z-Image merges actually differ *in*, beyond
  look? All five take the identical recipe.
