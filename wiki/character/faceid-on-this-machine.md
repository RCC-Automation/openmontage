---
title: IP-Adapter FaceID on this machine — what it buys and what it costs
status: measured
updated: 2026-08-26
sources: [reference-conditioning.md, what-we-measured.md, runbook-first-lora.md]
---

IP-Adapter FaceID PlusV2 conditions a render on a **pose-normalised ArcFace
vector** rather than on image tokens. That is the *embedding* path, and the
reason the runbook reaches for it: our latent-path measurement collapsed from
0.932 on matched framing to 0.301 on a medium (`DECISIONS.md` #30), and an
embedding should survive a framing change that image tokens cannot.

It works here. It also costs something the identity score cannot see, and that
cost is why the first character dataset was built without it.

Installed by runbook Phase 1: `ip-adapter-faceid-plusv2_sdxl.bin` plus its LoRA,
`buffalo_l`, and CLIP-ViT-H under the long filename the loader matches on. Graph
builder: `tools/_comfyui/faceid.py`.

---

## What we know

### It transfers identity, and `lora_strength` is the strongest dial

Raw ArcFace cosine to the anchor, one prompt, one seed, close-up:

| | w1 | w2 | w3 |
|---|---|---|---|
| no reference | 0.413 | | |
| lora 0.3 | 0.554 | 0.652 | 0.670 |
| lora 0.5 | 0.585 | 0.648 | 0.611 |
| lora 0.7 | 0.654 | 0.697 | 0.695 |
| lora 1.0 | **0.745** | 0.744 | 0.727 |

`lora_strength` 0.6 → 1.0 moved identity 0.685 → 0.750; `weight_faceidv2` above
2 buys nothing and above 3 loses. The measured ceiling with framing intact is
**0.786** (lora 1.0, w3, close-up).

### It overrides the shot size unless you hold it off

Face box as a share of frame, against the same prompt rendered with no reference:

| | face share | drift vs baseline |
|---|---|---|
| baseline close-up, no reference | 12.28 % | — |
| baseline wide, no reference | 3.39 % | — |
| wide, FaceID `start_at` 0 | 9.96 % | **2.94×** |
| wide, FaceID `start_at` 0.4 | 6.02 % | 1.77× |

Composition is decided early in the trajectory, so conditioning from step zero
makes every shot a portrait. `start_at` 0.4 nearly halves the distortion and
costs no identity (0.792 → 0.750). **Set it per shot family**: 0.0 close-up,
0.2 medium, 0.4 wide. Close-ups want 0.0 — delaying there only lets the
composition wander (drift falls to 0.59×, too far out).

### It makes skin plastic, and that is why we stopped using it

Every setting produced glossier, warmer, more idealised faces than the base
model's own output: uniform skin tone, heavy specular sheen, freckles gone. The
effect scales with `lora_strength` — exactly the dial that maximises identity.

**A two-pass refinement does not recover it.** Re-rendering a FaceID image at
low denoise with no reference kept identity (0.745 → 0.735 at denoise 0.20,
0.700 at 0.30; the face is lost entirely by 0.40) and left the look unchanged. A
low-denoise pass preserves the source's idiom rather than re-rendering it.

The decision that follows is `DECISIONS.md` #38 applied one level down. That
decision cast a model that renders brass but drifts, because *identity is
addable and the look is not*. Here the LoRA being trained **is** the thing that
adds identity, and it cannot add realism it was never shown. So the dataset
carries the realism and the training carries the identity — see
[dataset-bootstrap](dataset-bootstrap.md) for the rejection-sampling path that
replaced this one, and what it costs in yield.

---

## What it costs

~35 s per render at 832×1216, 35 steps, on `juggernautXL_ragnarok` — about 10 s
more than the same graph without the adapter. The first render of a session adds
~110 s for the adapter, CLIP-vision and insightface to load.

---

## Traps

**The FaceID LoRA must live in `models/loras/`, not `models/ipadapter/`.**
`IPAdapterUnifiedLoaderFaceID` finds the adapter by pattern in `ipadapter/` but
resolves its LoRA through `folder_paths.get_filename_list("loras")`. Put both
files where the adapter goes and every render dies with `LoRA model not found.`
— a message that names neither the file nor the folder it looked in. Same shape
as the MSR LoRA gap in `HANDOFF.md`: a model that exists but not where the node
looks.

**`provider` must be CPU.** The dropdown offers CUDA and ROCM, and this
machine's ComfyUI venv carries `onnxruntime-gpu`, which advertises
`CUDAExecutionProvider` and `TensorrtExecutionProvider` on a box with no CUDA.
Only `CPUExecutionProvider` runs.

**A cosine-only sweep cannot see a framing override.** Our first calibration
reported that wide shots held identity as well as close-ups — true, and
meaningless, because at every weight tested the wide renders came back as
portraits. Score `face_fraction` alongside identity, against a no-reference
render of the same prompt as control.

**Multi-image references average, they do not sharpen.** Conditioning on the
promoted cluster's 7 members scored *worse* against the anchor (0.55–0.61) than
a single reference (0.75), while scoring better against the cluster's mean
(0.72). Several views of one person would help; seven similar-but-different
people blend. Our clusters are only ~0.54 internally, so they are the wrong
input. Their value is as extra training images, not as conditioning.

**The reference loads by absolute path.** Core `LoadImage` reads from ComfyUI's
`input/` directory and takes a filename from an enum. `VHS_LoadImagePath` takes
a path string, so the anchor can stay in the project where the evidence lives;
`VHS_LoadImagesPath` takes a directory for the batch case.

---

## Open questions

- Does the embedding path survive a framing change where the latent path
  collapsed? **Still unanswered here.** The wide-shot identity numbers look
  strong (0.72–0.79) but every wide render was pulled toward a portrait, so the
  framing never actually changed enough to test it. Answering it needs
  `start_at` high enough to hold the framing, which is where identity starts to
  fall.
- Is there a setting that holds identity without idealising skin? Nothing in the
  swept range did. Lower `lora_strength` reduces both together.
