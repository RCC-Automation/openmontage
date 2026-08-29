---
title: Build routes — what the Builder can render, and what each one needs
status: measured
updated: 2026-08-29
sources: [../../tools/_comfyui/vrgdg.py, ../comfyui/image-recipes.md, traps.md, ../../DECISIONS.md]
---

A **build route** is VRGDG patching one of its own installed API templates and
handing back a ready-to-queue ComfyUI graph. It is the third of the
[three graph sources](../comfyui/graph-sources.md), and the one that matters for
the Builder: a route is what the Music Video Builder UI itself uses, so anything
drivable through a route is also selectable by a human working in the Builder.

Seventeen routes exist. They fall into three classes, and the class decides how
you can call it.

---

## What we know

### The three classes

**Standalone image routes** take parameters and nothing else. `zimage`, `krea2`,
`krea2_2pass`, `ernie_image`, `flux_klein`, `nb_image`, `z_upscale_enhance`.

**Project-bound video routes** read a VRGDG project folder and cannot be driven
from parameters alone — they need `project_folder`, `audio_path`, `srt_path`,
and for `i2v` an `image_folder`. `i2v`, `t2v`, `flf`, `rtv`, `ingredients`,
`id_lora`, `minimax_h3`.

**Host-bound routes are refused before they are called.** Twelve endpoints open
a native OS dialog or launch a browser and block forever in an unattended run —
`music_builder/pick_path`, the whole `browser_image/*` family,
`lora_dataset/pick_folder`, `ltx/tensorboard/open`. `HOST_BOUND_ROUTES` in
`tools/_comfyui/vrgdg.py` refuses them up front rather than letting a sweep hang
(`DECISIONS.md` #12).

Two more that are neither: `transcribe` and `timestamped_transcribe` produce an
SRT, and `clear_memory` is a graph whose only job is unloading models.

### The image routes, measured

All rendered 2026-08-29 on the same close-up portrait prompt. Z-Image is the
reference because it is what the film pipeline actually uses.

| route | model | measured | what it is for |
|---|---|---|---|
| `zimage` | Z-Image Turbo | 60.6 s median (n=62), two-pass | the workhorse — see the note below |
| `flux_klein` | FLUX.2 Klein 4B | 28 s at 8 steps | multi-image reference composition, 0.932 ArcFace on a matched close-up |
| `ernie_image` | ERNIE Image Turbo | **78.8 s** | a distinctly different look |
| `krea2` | Krea-2 + Z-Image enhance | **129.6 s** | Krea-2 with a Z-Image detail pass on top |
| `krea2_2pass` | Krea-2, two passes | **422.1 s** | the most expensive still available here |
| `z_upscale_enhance` | Z-Image | untested | upscale/detail pass over an existing image |
| `nb_image` | Nano Banana | unavailable | hosted; needs network and credentials |

**A route is not the cheapest way to render a still.** The same Z-Image weights
through a standalone graph cost **14.1 s** against the route's 60.6 s median,
because the route is a two-pass flow that renders 1280×720 and then again at
1920×1080. Reach for a route when you want the Builder to own the result, and
for [a standalone graph](../comfyui/image-recipes.md) when you want the picture
cheaply.

### Krea-2 — what it is and when it earns its cost

Krea AI's distilled turbo model, notable for being trained explicitly *against*
the "AI look": the plastic skin, even lighting and symmetry that give a
generated image away. It is an **aesthetics** proposition, where Qwen-Image is
an **adherence** one.

Stack: `krea2_turbo_fp8_scaled` (13.1 GB) + `qwen3vl_4b_fp8_scaled` encoder
(5.2 GB) + `qwen_image_vae` (0.25 GB). Two routes — `krea2` adds a Z-Image
enhance pass, `krea2_2pass` runs Krea-2 twice at 16:9,
`euler_ancestral_cfg_pp`, cfg 1.2.

**Benefit:** a different aesthetic register from everything else installed, and
it is Builder-native, so it is available to a human picking a look for a scene
rather than only to a script.

**Cost, measured:** 129.6 s and 422.1 s. That is 9× and **30×** Z-Image's
standalone 14.1 s. On a single portrait the output is good but not visibly worth
the multiple — the two-pass read as older and harder-lit than the reference.

**When to reach for it:** hero stills where the look is the point and the time
does not matter. Not in a render loop. Its anti-AI-look claim is about aesthetic
character and cannot be judged from one portrait — a wide or an environment
would test it properly, and that has not been run.

### ERNIE Image Turbo — the cheaper surprise

Baidu's image model, and the least-known quantity in the installed tree until it
was first rendered here. Stack: `ernie/ernie-image-turbo` (16.1 GB) +
`ministral-3-3b` encoder (7.7 GB), decoding through the Flux.2 VAE.

**Benefit:** at **78.8 s** it is the cheaper of the two additions and produced
the most distinct render of the four — heavy freckling, strong skin texture, a
warm cast. A genuinely different look for a scene meant to feel different.

**Cost:** 5.6× Z-Image, and 24 GB of disk for the pair.

**Verdict on both:** keep as Builder options for hero stills; leave them out of
the render loop. Neither is worth 5–30× the workhorse for routine scene work.

---

## What it costs

Disk: Krea-2 ~18.6 GB, ERNIE ~23.8 GB. Time: see the table. Both load their own
encoder, so neither shares residency with the Z-Image stack — on a machine where
[system RAM is the ceiling](../comfyui/this-machine.md), that matters more than
the disk.

---

## Traps

**The template names models you do not have, in a chain.** Enabling Krea-2 took
three aliases, each surfacing only once the previous was fixed:

| the template asks for | what is actually installed |
|---|---|
| `vae/flux/flux2-vae.safetensors` | `vae/flux2-vae.safetensors` |
| `diffusion_models/z_image_turbo_bf16.safetensors` | `zImageTurbo_turbo.safetensors` |
| `text_encoders/qwen_3_4b.safetensors` | `qwen3_4b_fp8_scaled.safetensors` |

**A hardlink is the right fix** — same volume, zero bytes, no admin, and both
names keep working so nothing already referring to the original breaks. A rename
would break every existing reference. This is the standing
"[template model names are not yours](traps.md)" trap, and the failure is a 400
from VRGDG naming a file and a folder, not a silent wrong render.

**`ernie_image` builds with an empty `clip_name`.** No alias can fix that: the
route emitted `clip_name: ""` and ComfyUI refused the prompt with
`value_not_in_list`. Every model has to be named explicitly in the payload —
`unet_name`, `clip_name`, `vae_name`. Same trap, opposite failure: sometimes the
template carries the wrong name, sometimes none at all.

**`GET /vrgdg/music_builder/model_defaults` is the base payload**, not the
template. It returns the user's own saved choices. But note its `ernie_image_settings`
carried the `flux\flux2-vae.safetensors` path that did not resolve here, so the
defaults are a starting point, not a guarantee.

---

## Open questions

- Does Krea-2's anti-AI-look claim survive a wide shot or an environment, where
  one portrait cannot test it?
- Is `z_upscale_enhance` a better finishing pass than the `4x-UltraSharp` model
  upscale or a hires-fix? All three exist here; none have been compared.
- `minimax_h3` still has no verdict — one of its two weight files was a failed
  download ([comfyui/models](../comfyui/models.md)).
