---
title: Holding identity without training — and the two mechanisms that fail oppositely
status: researched
updated: 2026-08-25
sources: [what-we-measured.md, https://huggingface.co/h94/IP-Adapter-FaceID, https://github.com/cubiq/ComfyUI_InstantID, https://huggingface.co/guozinan/PuLID]
---

## The structural fact everything else follows from

**There are two different mechanisms here and they fail in opposite ways.**
This is the single most useful thing the research produced, because it explains
a number we measured and could not account for.

| | **Latent / pixel reference** | **Embedding identity** |
|---|---|---|
| Examples | FLUX.2 Klein, Kontext, Redux, Qwen-Image-Edit, UNO/USO | IP-Adapter FaceID, InstantID, PuLID, InfiniteYou |
| What it conditions on | the reference image, VAE-encoded and appended as extra tokens | a 512-d ArcFace vector from the face crop |
| Why that matters | the DiT attends to **real image tokens**, so it reproduces what it sees **at the scale it sees it** | the vector is **pose- and scale-normalised by construction** |
| Peak strength | very high on matched framing | lower peak (~0.6–0.7 reported) |
| Failure mode | **collapses when framing changes** | **holds the face and nothing else** — no costume, no hair styling, no palette |

**Our measured 0.932 → 0.301 → 0.493 collapse was taken through the latent
path** — the 0.93 is attributed to `flux_klein`. That is exactly the failure
mode the latent mechanism has by construction. It is not a flaw in our setup; it
is what that mechanism does.

**Which means the embedding path has never been tested here, and it is the one
whose failure mode does not match our problem.**

### The experiment that would settle it

Take the existing close-up reference. Generate the **same medium and wide
shots twice** — once via Klein multi-reference, once via an embedding method.
Score both with our ArcFace harness, per shot family.

**If the embedding numbers land flat around 0.6–0.7 while Klein's collapse to
0.30**, the pipeline answer is: *Klein carries costume, palette and world; an
embedding adapter carries the face across framings; use both.*

That is one afternoon and ~2 GB of downloads.

---

## What is already here

### FLUX.2 Klein multi-reference — installed, wired, Apache-2.0

The only reference-conditioning path on this machine that is **commercially
usable**. VRGDG ships `VRGDG_MultiReferenceConditioningFromPaths`, which takes
up to **50 reference images**, VAE-encodes each and appends the latents to both
positive and negative conditioning.

The whole stack is 8.2 GB and already on disk: `flux-2-klein-4b-fp8` (3.79 GB),
`qwen3_4b_fp8_scaled` (4.11 GB, the Klein text encoder), the FLUX.2 VAE.

- **The shipped templates need fixing before they run.** They fail as-is.
- **Set `megapixels` per reference.** Default is 1.0; drop wardrobe and location
  references to 0.25–0.5 MP to cut token cost. Each extra reference adds ~1 MP of
  image tokens to *every* attention op — four references at 1.0 MP roughly
  quintuples the cost.
- **Keep the full character description in the prompt on every shot.** BFL's own
  guidance, and it agrees with our measured finding that
  [the description carries identity](what-we-measured.md). Do not let the
  reference replace the words.
- FLUX.2-klein-**9B** exists (Apache-2.0, GGUF quants) and this machine has the
  memory for it.

### PhotoMaker — nodes already in core ComfyUI

`PhotoMakerLoader` and `PhotoMakerEncode` are **first-party core nodes**, and
`models\photomaker\` already exists, empty, waiting.

**The lowest-friction multi-reference identity path on SDXL**: one download
(`photomaker-v1.bin`), **no InsightFace, no ONNX, no new Python packages** — so
nothing can break the ComfyUI venv.

It fuses *several* photos of the same person into one stacked ID embedding and
splices it into the text conditioning at a trigger token (`photomaker` by
default). Feed it a **batch** of cast stills — the stacking across several
photos is the whole point, and our cast record already holds more than one.

---

## What needs an hour of setup

### IP-Adapter FaceID PlusV2 (SDXL) — the cheapest untested lever

`comfyui_ipadapter_plus` is **already installed**. What is missing is ~1.2 GB of
weights, `insightface` in the *ComfyUI* venv (it is in the repo venv, not that
one), and one filename fix on the CLIP vision tower.

It fuses two signals: the framing-invariant ArcFace embedding **plus** a
controllable amount of CLIP-ViT-H from the same crop — the "PlusV2" part.

**Research licence only.** Face only: it will not hold wardrobe, hair styling
detail or palette.

### InstantID (SDXL) — strongest single-image face identity, with a catch worth knowing

Its big caveat is precisely the one we care about: **it copies the reference's
pose** unless you feed a separate keypoint image — *which is also the escape
hatch that lets it change shot size.*

Feed `image_kps` a keypoint image derived from a medium- or wide-shot blocking
reference while `image` stays the close-up cast still. That is the framing
experiment, and it is the reason InstantID is interesting to us rather than just
strong.

Needs `antelopev2`, **not** `buffalo_l` — different alignment, different
embedding space. Heavy-handed: drop CFG to 4–5 or add RescaleCFG.

### PuLID-FLUX v0.9.1 — best for FLUX.1-dev

Use the **`lldacing` fork, not `balazik`'s** — balazik's has a hard
CUDA-compute-capability gate (`"doesn't work on HW with CUDA compute < v8.0"`)
that is a coin flip on gfx1151. Verify the gate in one line before installing
anything.

`lldacing` also added `PulidFluxFaceNetLoader` specifically as the
commercial-friendly path.

---

## What to skip, and why

| | |
|---|---|
| **FLUX.1 Redux** | An image-*variation* adapter that overwhelms the text prompt. BFL's own card: *"outputs are heavily influenced by the input image."* No face-specific signal at all. The community `attn_bias` fix is damage control, not identity control. |
| **InstantX FLUX.1 IP-Adapter** | Disqualifies itself in its own model card: *"supports image reference, but is not for fine-grained style transfer or character consistency."* |
| **InfiniteYou** | Highest published quality, and the one **not** to run here: 43 GB peak at bf16 on a machine that has already had an OOM take down the backend *and its own OOM handler*. CC-BY-NC. |
| **UNO / USO / UMO** | Native ComfyUI support exists (`FluxKontextMultiReferenceLatentMethod` has a `uxo/uno` method) but they are latent-space subject references — same framing sensitivity as Klein, and Klein is Apache-2.0 while these need FLUX.1-dev. Only worth it for **two or more named characters in frame**. |

---

## Traps

**`onnxruntime-gpu` alongside `onnxruntime`** causes a cublasLt error; installing
plain `onnxruntime` is the clean fix. CPU is already what runs here anyway —
measured InsightFace cost on this box is 26 ms/image for detection.

**Install into the ComfyUI venv, not the repo venv.** They are different
environments and `insightface` currently lives only in the repo one.

**Do not substitute `buffalo_l` for `antelopev2`.** Different alignment,
different embedding space. Our [ArcFace harness](measuring-identity.md) uses
`buffalo_l`; InstantID needs `antelopev2`.
