---
title: Training a character LoRA on this machine
status: measured
updated: 2026-08-26
sources: [../comfyui/this-machine.md, https://github.com/kohya-ss/sd-scripts, https://github.com/kohya-ss/musubi-tuner, https://github.com/ROCm/ROCm/issues/6034]
---

**Yes, it can be done here.** That is a change from what this project believed
a day ago, and it rests on two things verified by hand — see
[this-machine](../comfyui/this-machine.md): `bitsandbytes` works, and the
AOTriton flag makes attention 8.2× faster with 24× less memory.

Nothing on this page has been run end-to-end here yet. It is `researched`, and
the first training run should be treated as an experiment measured with our own
[ArcFace harness](measuring-identity.md), not as a known quantity.

---

## Measured here, 2026-08-26 — it trains

The first LoRA ever trained on this machine, as a throwaway to answer
`QUESTIONS.md` Q7 before any dataset work was worth its GPU-hour:

| | |
|---|---|
| trainer | ComfyUI native `TrainLoraNode` → `SaveLoRA`, graph in `tools/_comfyui/lora_train.py` |
| base | `juggernautXL_ragnarok.safetensors` (SDXL) |
| data | 10 close-ups at 832×1216, one caption each: `WRENX woman, close-up portrait, head and shoulders` |
| settings | 200 steps · rank 16 · LR **5e-4** · AdamW · bf16 · gradient checkpointing · batch 1 |
| time | **498.7 s — 2.49 s/step** (first step 2.61 s) |
| output | 102.5 MB, loads through `LoraLoader` |
| memory | torch held ~25 GB during training on the 94 GB unified pool |
| gate | same seed, same prompt: **0.428** ArcFace to the anchor with the LoRA, **0.219** without |

So the answer to "can a LoRA be trained on ROCm here" is yes, at about
**8 minutes per 200 steps** for SDXL — a 1,500-step run is roughly an hour.
The AOTriton flag was set at User scope; whether it reached the ComfyUI
process is still unknowable from the log (`DECISIONS.md` #37), so this
number is with-or-without it. Nothing else in the plan depends on which.

**What it does not say.** 0.43 after 200 steps on ten images is a weak LoRA
moving a face the right way, not a character. Whether a real dataset produces
identity *and* keeps the base model's skin is WP7 step 7.3, and nobody has
measured it.

Three traps found on the way, all in `HANDOFF.md`: the dataset must be staged
under `ComfyUI-Shared\input` (not the install's `input/`), the LoRA name must
be passed exactly as ComfyUI lists it (backslash-joined on Windows), and the
optimizer list is `AdamW` / `Adam` / `SGD` / `RMSprop` — no 8-bit option in
this node, which is fine with 94 GB.

## Start here: ComfyUI's own trainer

**The lowest-friction trainer is already installed and already running.**
ComfyUI 0.32.0 ships a native LoRA training node stack — `TrainLoraNode`,
`LoraModelLoader`, `SaveLoRA`, `LossGraphNode` in `comfy_extras/nodes_train.py`,
plus a dataset family in `nodes_dataset.py`.

Why it matters here specifically: **its optimisers are literally
`torch.optim.Adam/AdamW/SGD/RMSprop`**. No bitsandbytes, no Triton, no
xformers. Gradient checkpointing is `torch.utils.checkpoint`. It trains
whatever ComfyUI can load — SDXL, Z-Image, FLUX.2 Klein alike. Zero install,
zero risk to the venv that currently runs the whole production pipeline.

```
LoadImageTextDataSetFromFolder → ResolutionBucket → VAEEncode → latents
CLIPTextEncode over the same captions
TrainLoraNode: algorithm=LoRA, rank=32, optimizer=AdamW, loss=MSE,
               training_dtype=bf16, lora_dtype=bf16,
               gradient_checkpointing=true, batch_size=1, grad_accum=4
→ SaveLoRA (wire `steps` in, so filenames carry the step count)
→ LossGraphNode (wire LOSS_MAP in, so you can see the curve)
```

**One catch worth knowing: alpha is pinned at 1.0**, so scale is `1/rank`.
That means the learning rate does not transfer from kohya recipes. Start at
**5e-4 for rank 32** — roughly kohya's 1e-4 at alpha=rank — and sweep
3e-4 / 5e-4 / 1e-3.

Copy the result from `output\loras\` into `ComfyUI-Shared\models\loras\`.

---

## The other trainers, ranked for this box

| Trainer | Verdict | Why |
|---|---|---|
| **ComfyUI native** | **start here** | already installed, pure-torch optimisers, no new deps |
| **kohya-ss/sd-scripts** (SDXL) | **probably** | no xformers in requirements; unpinned bitsandbytes, which now works. Trains the text encoders too — that is what binds a novel trigger tightly to a face |
| **musubi-tuner** (Z-Image, FLUX.2) | needs work | pure torch + `--sdpa`, no hard Triton/xformers. **Blocked by the model files, not the GPU** — see below |
| **OneTrainer** | needs work | reportedly the one trainer that gets Z-Image right, and does masked training. Its `requirements-rocm.txt` says verbatim *"AMD requirements might be outdated"* and pins Linux-only |
| **ai-toolkit** | needs work | broadest coverage, but CUDA-first; the only published AMD route is WSL2 |
| **SimpleTuner** | deprioritise | ROCm extra pulls manylinux-only wheels; gfx1151 not on its verified list |
| **ComfyUI-FluxTrainer** | avoid | it is sd-scripts, but it installs kohya's dependency surface **into the ComfyUI venv** — the one environment that currently works end-to-end |
| **diffusion-pipe** | **no** | DeepSpeed pipeline parallelism is not optional in it. Linux/CUDA-shaped |

---

## The real blocker is the model files, not the GPU

This is the finding that would otherwise cost a wasted day:

**Every Z-Image file on disk is a Turbo derivative, and everyone says train on
Base.** Turbo models are distilled; training on them is training on an already
collapsed schedule. The fix is to download Z-Image **Base**, or apply ostris's
De-Turbo adapter via `--base_weights`.

**The FLUX.2 Klein file on disk is `flux-2-klein-4b-fp8.safetensors` — the
distilled fp8 *inference* model.** musubi expects the full-precision DiT and
applies its own quantisation via `--fp8_base --fp8_scaled`. Training on an
already-fp8 checkpoint is the wrong starting artefact.

**SDXL is the family we can train today**, from checkpoints already on disk:
`juggernautXL_ragnarok` (photoreal), `realismIllustriousBy_v50FP16`,
`babesIllustriousBy_v50BF16`.

---

## Dataset — this is where character LoRAs are won or lost

The literature arrives independently at **our own shot-family finding**:
identity does not generalise across shot size on its own, so every framing you
intend to shoot must be in the data.

A LoRA learns a joint distribution of identity *and everything else present*.
Whatever framing, lighting or background you over-represent gets baked into the
identity direction.

**Target 24–36 images**, with quotas:

| | |
|---|---|
| ~8 | close-up / face — front, ¾ left, ¾ right, profile both sides, slight up, slight down |
| ~8 | medium / waist-up |
| ~8 | full body / wide |
| rest | expression and lighting variation |

- **Vary the background in every image.** Never let one location dominate.
- **ArcFace-score every candidate against your canonical reference before
  training** and drop anything below ~0.75. Training on drift teaches drift.
- **Fewer excellent beats more mediocre** — every source that quantifies it says
  25 good beats 75 inconsistent.

**Skip regularisation images.** The 2025–26 sources call them optional, ignore
them, or reserve them for DreamBooth full fine-tunes. The class drift they
protect against is not our failure mode; ours is cross-framing collapse, which
is a dataset-coverage problem. Spend the effort on framing coverage instead.

---

## Captioning is the mechanism, not a formality

**Caption everything that VARIES. Omit everything that is CONSTANT about the
character.**

Anything you name becomes something the model can be asked to change at
inference. Anything you never name gets absorbed into the trigger token.

| Name it | Omit it |
|---|---|
| clothing, accessories, pose, expression | face structure |
| background, lighting, camera angle | eye colour, hair colour |
| **shot size, explicitly, in every caption** | any permanent mark |

That last one is what lets you later prompt the shot size and have it obey.

Use the **same field order in every caption**; never reorder. Pick a trigger
that is a real rare token rather than gibberish when the text encoder is not
being trained. Florence2 is already installed in ComfyUI for local captioning,
though its raw output is prose and needs restructuring.

This is the direct literature analogue of our measured finding that
[the description carries identity, not the seed](what-we-measured.md).

---

## Starting hyperparameters

LoRA output is scaled by `alpha/rank`, so alpha and learning rate trade off
directly. Rank sets capacity: too low and the face is not captured; too high and
it memorises the dataset *including its backgrounds*.

| | |
|---|---|
| **SDXL / sd-scripts** | dim 32, alpha 32, AdamW8bit, LR 1e-4 UNet + 5e-5 TE, cosine + 100 warmup, batch 2 × accum 2, 1024px |
| **ComfyUI native** | rank 32, AdamW, MSE, bf16, grad checkpointing on, batch 1 × accum 4, ~1200 steps, **LR 5e-4** (alpha is pinned at 1) |
| **Z-Image / FLUX.2 (musubi)** | dim 32, LR 1e-4, adamw8bit, bf16, 16 epochs saving every epoch |

**Sweep one axis at a time, and sweep LR first** — it moves results more than
rank does.

**Overfit tell:** prompt for a completely different outfit or location. If the
LoRA refuses, halve the steps or the LR. Underfit shows as the face drifting;
overfit shows as the face being right while the LoRA drags training backgrounds
into every shot.

**Save every epoch.** The difference between epoch 6 and epoch 16 is usually the
difference between flexible and baked, and the best identity/flexibility
trade-off is rarely the last one.

---

## The experiment that settles it

**Nobody in the LoRA literature publishes ArcFace numbers.** Their quality
claims are qualitative and not comparable to ours — which means our harness can
answer a question the field cannot.

Fix N prompts × 3 shot families × 3 seeds, identical across four conditions:

1. description only
2. reference image matched to shot family
3. LoRA only
4. LoRA + matched reference

Score all four with the same ArcFace harness. **Report per-shot-family means,
never a single average** — an average is exactly what hid the reference-image
collapse in the first place. Record CLIP look-consistency alongside, since
[the two disagree usefully](measuring-identity.md): a LoRA that raises CLIP while
lowering ArcFace is learning the costume, not the person.

**The prior worth testing:** a LoRA should degrade far less across shot size
than a single reference image does, because identity lives in the weights rather
than in a conditioning image that stops matching when the framing moves.
