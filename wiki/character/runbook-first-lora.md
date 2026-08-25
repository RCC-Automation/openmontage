---
title: Runbook — our first character LoRA, step by step
status: assumed
updated: 2026-08-25
sources: [lora-training.md, dataset-bootstrap.md, reference-conditioning.md, ../comfyui/this-machine.md]
---

The concrete path from where this machine is today to a trained character LoRA
we can measure. **Nothing here has been executed yet** — the status is
`assumed`, and each phase names what to check before moving on.

**The character:** the clockwork heroine already cast through
[practice/casting](../practice/casting.md).
**The target model:** `juggernautXL_ragnarok.safetensors` — SDXL, the one that
reads the brief at 0.87 while drifting at 0.31. We fix the drift; we cannot fix
another model's inability to render brass.

**Machine state verified 2026-08-25:** `comfyui_ipadapter_plus` and
`comfyui-florence2` are installed. `insightface` is **absent from the ComfyUI
venv** (it lives in the repo venv). `onnxruntime` is present and
`onnxruntime-gpu` is absent — which is the clean state. `models/ipadapter`,
`models/insightface` and `models/instantid` **do not exist**.
`models/photomaker` exists and is empty. `clip_vision/` holds
`clip_vision_h.safetensors`.

---

## Phase 0 — turn the machine on properly (10 minutes)

**Everything downstream is 8× faster and needs 24× less memory after this.**

1. Set `TORCH_ROCM_AOTRITON_ENABLE_EXPERIMENTAL=1` in **ComfyUI's launch
   environment**, not just a shell. It matters for rendering as much as training.
2. Restart ComfyUI.
3. **Check it took:** the `Flash Efficient attention ... still experimental`
   warning should stop appearing in the log.
4. Do **not** set `PYTORCH_HIP_ALLOC_CONF=backend:malloc` — it crashes PyTorch
   on this stack.

**Gate:** re-run one casting round and compare wall time against the ~10.3 min
of round 1. If it is not meaningfully faster, stop and find out why before
building on it.

---

## Phase 1 — install the reference adapter (1 hour, ~2.5 GB)

We need **embedding-space** identity, because
[the latent path is the one that collapsed on us](reference-conditioning.md).
IP-Adapter FaceID PlusV2 is SDXL, which matches the target model.

1. **Install `insightface` into the ComfyUI venv** — not the repo venv:
   ```
   …\ComfyUI-Installs\ComfyUI\ComfyUI\.venv\Scripts\python.exe -m pip install insightface==1.0.1
   ```
   Leave `onnxruntime` as-is. Do **not** add `onnxruntime-gpu`; having both
   causes a cublasLt error, and CPU is what runs here anyway (~26 ms/image).

2. **Create the folders** under `ComfyUI-Shared\models\`: `ipadapter\`,
   `insightface\models\`.

3. **Copy the face pack the repo already downloaded** into where the node looks:
   `C:\Users\Barrul\.insightface\models\buffalo_l\` →
   `…\ComfyUI-Shared\models\insightface\models\buffalo_l\`

4. **Download** from `huggingface.co/h94/IP-Adapter-FaceID` into
   `models\ipadapter\`:
   - `ip-adapter-faceid-plusv2_sdxl.bin` (~1.0 GB)
   - `ip-adapter-faceid-plusv2_sdxl_lora.safetensors` (~370 MB)

5. **Fix the CLIP vision filename.** The loader's regex will not match
   `clip_vision_h.safetensors`; rename or copy it to
   `CLIP-ViT-H-14-laion2B-s32B-b79K.safetensors`.

**Gate:** load `IPAdapterUnifiedLoaderFaceID` in ComfyUI without an import
error, and generate one image. If it errors on insightface, step 1 went into the
wrong venv.

> **Licence note:** IP-Adapter FaceID is **research-licence only**. It is used
> here to *manufacture a training set*, and the LoRA that results is trained on
> our own generated images. If that distinction matters commercially, use
> **PhotoMaker** instead — core ComfyUI nodes, one download, no licence
> encumbrance — and accept weaker face binding.

---

## Phase 2 — choose the anchor (30 minutes, GPU)

1. **Render 40–60 close-ups** of the character from the description alone,
   varied seeds, on juggernautXL. No reference.
2. **Embed them all** with `lib/face_identity.py` (repo venv — it is CPU ONNX
   and independent of the GPU).
3. **Cluster** with `sklearn` KMeans(`init='k-means++'`), k ≈ n/8. Score each
   cluster by mean squared distance to its centroid.
4. **Take the most cohesive cluster.** Promote its **medoid** — not the mean, not
   your favourite — to be the anchor.

This is "The Chosen One" adapted. It replaces *"pick the image you liked"* with
something principled, and it starts you with ~8 mutually consistent images
rather than one.

**Gate:** the chosen cluster's mean pairwise ArcFace similarity should be
**≥ 0.80**. If nothing clusters that tightly, the description is not specific
enough — go back and tighten it before spending GPU on a dataset.

---

## Phase 3 — build the dataset as a ladder (2–3 hours, GPU)

**Not a batch. A ladder.** This follows directly from our measured
reference collapse: a reference is a *shot-family-local* identity carrier.

Quotas — write them down first and treat them as a checklist:

| family | target | anchor |
|---|---|---|
| close-up | ~10 | the Phase 2 medoid |
| medium | ~10 | promoted from the first close-up-anchored medium scoring ≥0.80 |
| wide / full body | ~10 | promoted the same way from the medium family |
| expression + lighting variation | ~6 | spread across families |

For each image:

```
generate (juggernautXL + IP-Adapter FaceID, anchored)
  → faces_in()          reject if != 1 face
  → cosine vs anchor    accept ≥0.80 | hold 0.70-0.80 | reject <0.70
  → record the score AND the family label
```

Rules that are easy to skip and expensive to skip:

- **Vary the background in every single image.** Anything constant across the
  set gets baked into the character.
- **No family above ~40%** of the set, or it becomes the LoRA's default framing.
- **Cache the anchor embedding once.** Do not re-embed per candidate.
- **Dedup on two axes before captioning** — PHash first, then DINOv2/CLIP cosine
  >0.95. A generated set's duplicates are *semantic*, not pixel-level: the same
  pose rendered twice is an unrequested repeat count.
- **Replace what you delete, in the same family**, or the quotas rot.

**Gate:** `face_identity_stability()` over the final accepted set. This is the
one-number acceptance test, and it is worth an hour of curation to pass it
rather than an hour of training to discover it failed.

---

## Phase 4 — caption (1 hour, CPU)

**Caption what VARIES. Omit what is CONSTANT about her.** Whatever you never
name gets absorbed into the trigger token; whatever you name stays steerable.

| Name it | Omit it |
|---|---|
| clothing, accessories, pose, expression | face structure |
| background, lighting, camera angle | eye colour, hair colour |
| **shot size, explicitly, every time** | the brass collar *if it is always present* |

1. **Pick a trigger**: 7–20 ASCII characters, invented, not a dictionary word.
2. **Caption with Florence-2** (`more_detailed_caption`) — already on disk at
   `models\LLM\Florence-2-large`, node already installed.
3. **Store the raw output, then post-process.** Caption once; the convention may
   change and you do not want to re-run the VLM.
4. **Strip identity invariants** from the output: face shape, eye colour, hair
   colour, age, build.
5. **Same field order in every caption.** Never reorder.

> The shot-size caption is what later lets you *prompt* the shot size and have
> it obey. It is the single most important field for our use case.

**Gate:** read ten captions end to end. If the character's face is described in
any of them, the trigger will bind weakly.

---

## Phase 5 — train (2–4 hours, GPU)

**Start with ComfyUI's own trainer.** Zero install, zero risk to the venv that
runs the whole production pipeline, and its optimisers are plain `torch.optim`.

```
LoadImageTextDataSetFromFolder → ResolutionBucket → VAEEncode
CLIPTextEncode over the same captions
TrainLoraNode  rank=32  optimizer=AdamW  loss=MSE
               training_dtype=bf16  lora_dtype=bf16
               gradient_checkpointing=true  batch=1  grad_accum=4
               learning_rate=5e-4          ← alpha is pinned at 1.0 here
→ SaveLoRA (wire `steps` in)  → LossGraphNode (wire LOSS_MAP in)
```

- **`learning_rate=5e-4`, not 1e-4.** ComfyUI pins alpha at 1.0, so scale is
  `1/rank` and kohya's numbers do not transfer.
- **bf16, never fp16.** fp16 without a GradScaler NaN'd on step 1.
- **Save every epoch.** Identity commonly peaks *before* the last checkpoint.
- **~1200 steps** as a starting point.

Copy the result from `output\loras\` to `ComfyUI-Shared\models\loras\`.

**If ComfyUI's trainer disappoints**, the next step is `kohya-ss/sd-scripts` in
its own venv — it trains the text encoders too, which is what binds a novel
trigger tightly to a face. Do **not** install `ComfyUI-FluxTrainer`; it puts
kohya's dependency surface into the one working ComfyUI venv.

---

## Phase 6 — measure, because nobody else has (1 hour, GPU)

**No one in the LoRA literature publishes ArcFace numbers.** Our harness can
answer a question the field cannot, and this is the experiment that settles the
whole approach.

Fix N prompts × 3 shot families × 3 seeds, **identical across four conditions**:

| | condition |
|---|---|
| a | description only |
| b | reference image matched to shot family |
| c | **LoRA only** |
| d | LoRA + matched reference |

- **Score every saved epoch**, not just the final one.
- **Report per-shot-family means, never a single average.** An average is
  exactly what hid the reference collapse in the first place.
- **Record CLIP look-consistency alongside ArcFace.** A LoRA that raises CLIP
  while lowering ArcFace is learning the costume, not the person.

**The prediction worth testing:** a LoRA should degrade far less across shot
size than a single reference does — because identity lives in the weights rather
than in a conditioning image that stops matching when the framing moves. If that
holds, this becomes the default path for every character.

**When it lands, this page becomes `measured` and the numbers go in
[what-we-measured](what-we-measured.md).**

---

## Total: roughly one long day

| Phase | Time | GPU |
|---|---|---|
| 0 — the flag | 10 min | no |
| 1 — install | 1 h | no |
| 2 — anchor | 30 min | yes |
| 3 — dataset | 2–3 h | yes |
| 4 — caption | 1 h | no |
| 5 — train | 2–4 h | yes |
| 6 — measure | 1 h | yes |

Phases 0, 1 and 4 need no GPU and can be done while something else renders.

## Where this can fail

- **Phase 2 gate fails** — the description is not specific enough. Cheapest
  failure, and the one that saves the most time by failing early.
- **IP-Adapter FaceID does not survive the framing change either.** Then the
  embedding-vs-latent hypothesis is wrong for our case, and the dataset has to be
  built by hand-curating across shot families. Slower, still possible.
- **The LoRA overfits** — face right, prompt-following dead. Take an earlier
  checkpoint, or lower the LoRA weight at inference. Do not retrain first.
- **Identity never rises above ~0.66.** That is the base model's own number and
  it means **the dataset is the problem.** Go back to Phase 3; do not tune
  hyperparameters.
