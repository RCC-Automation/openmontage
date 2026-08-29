---
title: Turning a still into a shot — the methods that work here
status: measured
updated: 2026-08-29
sources: [video-render.md, video-engines.md, ../comfyui/image-recipes.md]
---

Everything on this machine that takes a picture and gives back a moving shot,
with what each one needs and what it costs. Measured on `the-man-watches`
2026-08-29 unless marked otherwise.

The organising fact: **a shot needs a first frame, and the methods differ in
what else they need.** Sorting them that way is more useful than sorting by
engine, because the extra input is what decides whether a method is usable for a
given shot at all.

---

## What we know

### Image to video — one still, and it invents the motion

**Wan 2.2 14B with the LightX2V 4-step LoRA**, `wan22-i2v-4step.json`.
81 frames at 24 fps (3.38 s), 640x640: **30.9 min cold, and the models stay
resident afterwards.** Every clip submitted has completed.

Always applicable, because every shot has a first frame. It reads the prompt as
a description of the world rather than as instructions: asked for a subject who
holds still while a crowd moves, it walked her along with the crowd — and that
clip was the most convincing of the bench. **Prompt it for what the scene is
doing, not for what one person must not do.**

### First to last frame — two stills, and it generates the travel

**Wan 2.2 14B FLF**, `local_workflows/my_video_wan2_2_14B_flf2v.json`, same
weights as i2v. Same clip length and size: **10.5 min warm, 13.1 min semi-cold.**

Verified to genuinely interpolate between the frames it is given: run once with
the frames in each order, and the shot plays forwards and backwards
respectively. **This is the only method that lets an action be authored.**

`start_image` is node **68** and `end_image` is node **62** — read off the
consuming `WanFirstLastFrameToVideo` node. Loader order in the file implies the
opposite.

### Where a truthful end frame comes from

The method above is only as good as its second frame, and **a generated
continuation is an invention, not a future.** Two sources give a real one:

**A geometric transform of the first.** A push-in *is* the start frame cropped
and scaled; a pan is it translated. Those end frames are the same pixels
reframed, so nothing can drift, and the engine supplies parallax and crowd
motion between them. Untested here, and the cheapest open idea we have.

**The last frame of the previous clip.** Real by definition, free, and it makes
consecutive shots continuous. Points forwards only.

### Motion transfer — a still plus a driving video

`wan_animate_2_int8_convrot.safetensors`, **15.9 GB, on disk**, with
`local_workflows/my_video_wan_animate2.json` (51 nodes). Supplies the
performance instead of the endpoint, so it needs no last frame at all. Not yet
run here.

### LTX 2.3 — the reference implementation is the generator

`workflows/vrgdg-i2v-generator/` reads VRGDG's **shipped** API workflow
(`custom_nodes/comfyui-vrgamedevgirl/Workflows/UsedForUIDoNotTouch/Singlei2vForUI_API.json`,
74 nodes) and patches scene values into it. It rendered **BurningManGirl scenes
6–15 unattended, 15 of 15 complete**, with tiled decode at 256 and the refine
pass off. That is the path to use.

The shipped workflow carries **both** loaders — `DiffusionModelLoaderKJ` on the
int8 transformer (node 938) and `UnetLoaderGGUF` on the Q6_K (node 271:215) —
selected by a `ComfySwitchNode`. Keep the switch: a graph pruned down to one
branch is no longer the graph anyone has measured.

## What it costs

| method | extra input | per 3.4 s clip |
|---|---|---|
| Wan i2v | none | 30.9 min cold, resident after |
| Wan first-to-last-frame | a truthful end frame | **10.5 min warm** |
| crop-derived camera move | a crop of the first frame | 10.5 min + a crop |
| chained shots | the previous clip | same as the method rendering it |
| Wan Animate | a driving video | not yet measured |
| LTX via the generator | none | 3 min 23 s, one measurement, film 1 |

## Traps

**Read the wrapper log for progress, not the Python log.** `s/it` lines land in
`ComfyUI-Installs/ComfyUI/logs/comfyui.log`; `ComfyUI/user/comfyui.log` did not
carry them for these runs. A slow job and a stalled one look identical without
that line, and mistaking one for the other cost a day.

**Wan's graphs default to 640x640 square.** Nothing warns you; a 2.39:1 film
rendered at the default is silently the wrong shape. Set width and height
explicitly.

**A killed runner does not kill the render.** ComfyUI keeps executing a
submitted prompt after the script that submitted it exits, and a fresh run will
queue *behind* it — so a second measurement can be pure queue wait. Record the
prompt id at submit time and reattach instead of resubmitting.
