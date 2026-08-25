---
title: Techniques for holding a character — ranked for this machine
status: researched
updated: 2026-08-25
sources: [what-we-measured.md, ../comfyui/this-machine.md]
---

The survey of 2026 practice, filtered through what will actually run on
[this machine](../comfyui/this-machine.md). Ranked by *(identity strength ×
runnable here)*, not by popularity.

**Provenance:** a research workflow of 2026-08-25 — ten technique families, each
adversarially verified. Four families completed; **six failed on connection
errors and have not been run** (see Gaps at the bottom). Several verifiers
returned `refuted` on load-bearing operational claims, and those corrections are
folded in below. Two enabling findings were re-verified by hand and are
`measured`, not `researched`.

---

## The headline: the two things you want live in different models

Our own casting rounds found it, and the literature explains it. A model that
renders the *brief* well (juggernautXL, 0.87) drifts badly across seeds (0.31);
the model that holds a face perfectly (zImageUltimateNSFW, 1.00) renders
generic (0.25). See [what-we-measured](what-we-measured.md).

**The 2026 consensus is not reference-versus-LoRA. It is reference-THEN-LoRA:**
use a reference-conditioned model to manufacture a consistent 20–40 image
dataset, then train a LoRA on it. That resolves the split above — you get the
brief-reading model's look *and* a held identity — and it is the single most
important structural finding of this research.

---

## Enabling conditions — measured here, do these first

| | |
|---|---|
| **`TORCH_ROCM_AOTRITON_ENABLE_EXPERIMENTAL=1`** | 8.2× faster, 24× less memory on attention. Applies to rendering, not just training. Prebuilt in the torch ROCm wheel — *"no Triton" does not mean "no flash attention"*. |
| **`bitsandbytes` works** | 0.50.1, ROCm backend, `AdamW8bit` steps with real uint8 state. Our docs said otherwise and were wrong. Unblocks every kohya-family trainer. |
| **Train in bf16, never raw fp16** | reported: bf16 clean for 100+ steps; fp16 without a GradScaler NaN'd on step 1. |

---

## Ranked

### 1. Reference-conditioned generation (in-context / reference latents)

**The 2026 default is not an adapter at all.** Identity now travels as reference
*latents* concatenated into the diffusion transformer's own token stream —
Qwen-Image-Edit, FLUX Kontext, FLUX.2. This displaced the IP-Adapter /
InstantID / PuLID adapter family, which the research calls "mostly a dead end"
for new work.

- **Qwen-Image-Edit-2511** is reported as the strongest open-weight
  identity-holding model runnable here, via the ComfyUI-GGUF node pack.
- **`comfyui-ReferenceLatentPlus`** adds per-image strength and per-image
  timestep gating that plain `ReferenceLatent` lacks.
- **Multi-reference** — giving the model close, medium *and* wide at once — is
  FLUX.2's actual pitch and a genuine alternative to our one-reference-per-shot-family rule.
- **Z-Image cannot take a reference image today**, despite 2026 blog content
  saying otherwise. The ComfyUI plumbing exists; the model support does not.

**Why our reference collapses when framing changes:** the literature calls this
the *copy-paste versus variation* trade-off. A reference conditions strongly at
matched framing and fights the model when the framing moves — which is exactly
the 0.932 → 0.301 collapse we measured.

### 2. Character LoRA — and it is trainable here

See [lora-training](lora-training.md) for the detail. The short version: yes,
with `bitsandbytes` working and AOTriton enabled, and **ComfyUI 0.32.0's own
native Train LoRA node** is the lowest-friction path because it is already
installed and already running.

**Caveats the verifiers raised:** the Z-Image files on disk are all *Turbo*
derivatives, which are not the right base for training; the FLUX.2 Klein file
is the distilled fp8 inference model, not the trainable variant.

### 3. Downstream face repair — not conditioning

**Identity at wide framing is not a conditioning problem and should stop being
treated as one.** Fix it downstream with a face-region repass. Two routes are
already installed here:

- **VRGDG's own Face Fix** — better matched to this machine than any ONNX swapper.
- **Impact Pack's FaceDetailer** regenerating the face region with a character
  LoRA — a fully ONNX-free post-hoc route.

**A measurement warning that matters to us specifically:** ArcFace-scoring a
face-swapper's output is **partly circular** — swappers are trained to maximise
exactly the embedding similarity we score with. Do not read a swapped 0.95 as
equivalent to a generated 0.95.

**A swap fixes the face oval and nothing else.** Body, costume, hair, head shape
and silhouette are outside the mask by construction. It fails predictably below
~40–60 px faces and at large out-of-plane rotation, and frame-by-frame video
swapping produces "face swimming" — invisible on stills, obvious in motion.

**Licensing is the real blocker, not compute:** of the 13 swapper models
FaceFusion ships, only three are commercially usable. On this machine the only
working GPU path for the ONNX family is **DirectML**, and **ComfyUI-ReActor will
silently run on CPU** even after installing it, because its provider selection
mishandles ROCm's presence.

### 4. Video identity

See [video-identity](video-identity.md). The correction that matters most:
**LTX's ID-LoRA is a *voice* identity adapter, not a face one** — its visual
contribution beyond the first frame is approximately zero. Identity in
image-to-video is inherited from the start frame and then *decays*, and the fix
is to **re-anchor mid-clip with additional guide frames** (`LTXVAddGuide` can be
chained at multiple frame indices).

---

## Where the literature agrees with us

Independently, and worth knowing our measurements are not local flukes:

- **Dataset composition should span shot families** — the same finding as our
  reference-per-shot-family rule, arrived at from the training side.
- **Caption what varies, omit what is constant** about the character. That is
  the mechanism by which a trigger token absorbs identity.
- **CLIP and ArcFace disagreeing is not a quirk of our harness** — it is why
  every serious subject-driven benchmark reports both.
- **Skip regularisation images** for a character LoRA.

And one thing to *not* import: **nobody in the LoRA literature publishes ArcFace
numbers**, so their quality claims are not comparable to ours. Our harness is
the stricter instrument.

---

## Gaps — six families were never surveyed

The workflow lost these to connection errors. **Nothing here should be treated
as a complete survey:**

`flux-lora` · `reference-conditioning` (as its own deep pass) · `dataset-craft`
· `prompt-and-seed-craft` · `evaluation` · `rocm-training`

The synthesis agent also failed, on a session limit; the ranking above is
written from the four surveys that landed and is therefore *ours*, not the
workflow's.

Re-running is cheap and resumes from cache:
`Workflow({scriptPath: '…/character-consistency-research-wf_1deb0755-8a9.js', resumeFromRunId: 'wf_1deb0755-8a9'})`

---

## The cheapest next experiment

**Set the AOTriton flag in ComfyUI's launch environment and re-run one casting
round.** It costs nothing, and it tests three things at once: whether renders
speed up in practice, whether peak memory drops enough to make the four-model
round that crashed the backend survivable, and whether output is unchanged.
