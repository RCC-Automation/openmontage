---
title: Face swap — the identity mechanism that actually works here
status: measured
updated: 2026-08-28
sources: [faceid-on-this-machine.md, lora-training.md, what-we-measured.md, https://github.com/Gourieff/ComfyUI-ReActor]
---

Three mechanisms can put a chosen face into a render on this machine. Only one
of them puts in *that* face.

| mechanism | identity to the anchor | what it does to her |
|---|---|---|
| Klein multi-reference | 0.53 – 0.68 | a family resemblance |
| IP-Adapter FaceID | 0.75 – 0.84 | consistent, and **younger** — see below |
| LoRA (native trainer) | 0.12 – 0.46 | weak; the trainer never trains the text encoder |
| **ReActor face swap** | **0.80 – 0.88** | copies the face; changes nothing else |

The first three *generate* a face from a description or a vector, so each one
re-imagines her. ReActor transplants pixels: it detects the face in the target,
warps the source face onto it, and blends. Nothing is imagined, so nothing
drifts.

---

## What we measured

**Klein render + swap, four seeds, one prompt** (a market scene, red dress):
0.28-0.33 before the swap, **0.80-0.81 after** — every seed, no outliers.

**Across a whole dataset**, 43 candidates: the swap added **+0.282 identity per
image** on average, turning a 0.53-consistency generator into a set at **0.815
mutual consistency**.

**On a face occupying 0.8% of the frame**: 0.163 → 0.778. It works at sizes
where ArcFace can barely measure the result.

## The two rules that decide whether it works

**1. The swap changes the face and nothing else.** Hair, build, wardrobe, pose
and lighting all come from the base render. A market shot generated without her
hair described came back a dark-haired woman with her facial geometry, scored
0.778, and read as a different person to any human. **Her non-facial features
must be in the generation prompt** — hair colour and style first.

**2. The face must be visible and large enough to detect.** Below roughly 0.4%
of frame the detector finds nothing and the swap silently does not happen. An
over-the-shoulder shot has no face at all, and that is fine: at those distances
a character is read by silhouette and costume, both of which the *prompt*
controls. Do not chase a cosine score on a shot where the face cannot be seen.

## Settings, and why

    swap_model              inswapper_128.onnx
    boost_model             codeformer-v0.1.0.pth      <- not optional
    boost_codeformer_weight 0.7
    face_restore_visibility 0.5

**Face boost is not optional.** inswapper reconstructs at 128x128, so pasting
into a 1216 px frame gives a face that reads blurred against a sharp body -
measured **sharpness 0.099 against the source render's 0.326**. `ReActorFaceBoost`
upscales and restores the face *before* the blend, which fixes it:

| setting | identity | face sharpness |
|---|---|---|
| source render, no swap | — | 0.326 |
| swap, no boost | 0.876 | **0.099** |
| boost + restore-after | 0.830 | 0.309 |
| **boost with CodeFormer** | **0.831** | **0.368** |
| boost with GFPGAN | 0.840 | 0.499 (over-sharpened) |

## What it does not fix

The swapped face is **cleaner than the original**. GFPGAN and CodeFormer are
*restoration* models - removing blemishes is their job - so freckles, blotchy
tone and specular breakup do not survive. A `FaceDetailer` pass afterwards was
tried to bring native texture back and is not worth it: identity falls from
0.831 to 0.654 at denoise 0.2 and to 0.384 at 0.4, while measured sharpness
barely moves (0.368 → 0.29). It costs the identity and does not buy the texture.

So: you get her face and her age, not her skin. For training data that is the
right trade, because the base model supplies skin at generation time.

## Traps

**ReActor globs `folder_paths.models_dir` directly.** On ComfyUI Desktop that
is the *install* tree, not the Shared tree that holds the checkpoints - they are
two real directories, neither a link to the other. `inswapper_128.onnx` must sit
in `<install>/models/insightface/`, and the restore models in
`<install>/models/facerestore_models/`, or `swap_model` is an empty dropdown.

**A blank swap output is silent.** On one 1280x720 frame ReActor returned a
black 512x512 image at every upscale factor tried, with no error. Check the
mean brightness of the result and fall back to the unswapped render.

**`face_restore_visibility` has a floor of 0.1**, not 0. Asking for 0 is a
validation error, not a no-op.

**Licence:** InsightFace's pre-trained models, `inswapper_128` included, are
released for **non-commercial research use only**.
