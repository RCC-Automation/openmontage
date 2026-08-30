---
title: Rendering video — what it costs, and the stage that breaks it
status: measured
updated: 2026-08-28
sources: [../comfyui/this-machine.md, ../comfyui/graph-sources.md, traps.md]
---

LTX 2.3 image-to-video through the Builder, measured on `BurningManGirl`
2026-08-27/28. Three clips rendered; one hung for 2.5 hours; one crashed the
process. All three failures were the same stage.

**LTX renders in two passes.** A base pass at the configured size, then a
`LatentUpsampler` doubles the latent and a short refine pass runs on top. The
second pass is where the time and the failures are.

---

## The numbers

Re-measured 2026-08-29 through the generator's own workflow, reading `s/it` from
the wrapper log rather than waiting for a file. **Everything below supersedes the
first pass of measurements on this page.**

| 640x640, scene 5 | steps | s/step | minutes | total |
|---|---|---|---|---|
| base pass, refine off | 8 | **13.1** | 1.7 | **4.5 min** |
| base pass, refine on | 8 | 9.8 | 1.3 | **4.2 min** |
| latent-upscale refine | 3 | **39.5** | 2.0 | |

**The refine pass costs 4.0x the base pass per step here, and completes in two
minutes.** An earlier reading of 610 s/step against 26 s/step at 1280x720 gave a
ratio of 24x; both numbers can be true, because **the ratio is not constant - it
grows with resolution.** Treat 24x as a 1280x720 figure, not a property of the
pass.

At 640x640 the refine is cheap enough to leave on. Whether that still holds at
1280x720 and above is the open question; the way to answer it is to read the
per-step rate for one clip, not to schedule a batch and hope.

| earlier, 1280x720, 273 frames | 8 steps, 26 s/step - 3 min 23 s | 3 steps, 610 s/step - 30 min |
|---|---|---|

## The final VAE decode is a separate failure

The latent-upscale/refine pass and the final video VAE decode are independent
stages. On this AMD/ROCm Windows host, a render can finish both sampling passes
and then abort Python inside the LTX VAE's 3D convolution. The native exit is
`0xC0000409`; it is not a catchable Python out-of-memory exception.

The Builder's LTX 2.3 visual workflow contains a tiled decoder configured with
a spatial tile of **1280**, while its embedded API prompt still contains plain
`VAEDecode`. The working compatibility setting is `VAEDecodeTiled` with spatial
tile **256**, overlap 64, temporal size 32 and temporal overlap 16. This reduces
the individual MIOpen convolution workload. It does not make the expensive
upscale/refine pass cheaper.

`workflows/vrgdg-i2v-generator/` packages that correction for one, selected or
all scenes. It reads the complete installed VRGDG API workflow, preserves all
connections, and can additionally disable the second pass.

## Traps

**"Did not finish before the 2-hour wait limit" usually means hung, not slow.**
The Builder gives up at two hours; ComfyUI does not. Check the log: a completed
progress bar followed by hours of silence is a deadlock, and "wait then use
Recover Scene Videos" will not help because there is nothing to recover.

**`/interrupt` works; a very slow node just makes it look otherwise.** Tested
2026-08-29 on a running 120 s render: interrupted 30 s in, the queue cleared
**26.4 s later** and the job was recorded as errored. An earlier note here said a
job "ignores" the interrupt - what was actually observed was a node taking 25
minutes, so the interrupt was received and simply had no checkpoint to act on
until that node finished. Interrupt, then allow one step. `POST /free
{"unload_models": true, "free_memory": true}` remains the harder escape and also
frees the weights.

**A crash leaves empty scaffolding.** The failed attempts each created an
`image_to_video_clips_<timestamp>/` folder containing only empty `remake/` and
`vrgdg_temp/` subdirectories. An output folder with no `.mp4` and no other files
means the process died mid-render.

**Restarting ComfyUI destroys the evidence.** `user/comfyui.log` is truncated on
start; the previous session survives as `user/comfyui.prev.log`, and the Desktop
wrapper keeps its own timestamped copy under `ComfyUI-Installs/ComfyUI/logs/`.
That wrapper log is where the native crash trace lands — the Python log shows
nothing.

## Exporting the render as a standalone workflow

`scripts/export_i2v_workflow.py` writes the Builder's own i2v graph to a file
that opens in ComfyUI, so the settings are visible and adjustable instead of
buried in project-wide defaults. Two things it has to fix on the way out:

- **The loaders come back empty.** The shipped template carries the pack
  author's filenames, and only the payload fills yours — so the export supplies
  every model name from `GET /vrgdg/music_builder/model_defaults`.
- **Dead branches block validation.** The template hangs `RAMCleanup` and
  `VRAMCleanup` off the graph feeding nothing; those node types are not
  installed here, and ComfyUI validates the whole prompt (`DECISIONS.md` #5).
  Pruning to the output node removed 13 unreachable nodes, 72 → 59.

ComfyUI 0.32 / frontend 1.48 opens API-format JSON directly. The layout is
generated, so the graph is correct but mechanically arranged.

## Unattended scene round trip

`workflows/vrgdg-i2v-generator/run_scene_roundtrip.ps1` closes the gap between
an exported standalone graph and the Builder project. It generates one scene,
submits the API graph to ComfyUI, waits on the returned prompt id, locates the
audio-bearing MP4, calls VRGDG's `restore_scene_video` route, then persists the
scene's video fields through `save_session`.

Measured on `BurningManGirl` scene 5 on 2026-08-28:

- prompt id `f3b5ac45-d33b-40b0-b3c5-3589b695c444` completed without manual UI work;
- the generated scratch clip was restored as
  `rendered_scene_videos/video_0005-audio.mp4`;
- the restored file is non-empty and **4.416667 s** for a 4.4 s scene;
- VRGDG generated `video_0005-audio.jpg` and the saved segment reports
  `video_status: done`, `preview_mode: video`;
- the run used tiled decode 256 and disabled the upscale/refine pass.

The runner refuses to submit when ComfyUI already has a running or pending job,
so it cannot silently associate another render with the selected scene. On a
timeout it reports the existing prompt id and does not submit a duplicate.

An open Builder panel retains a JavaScript copy of the session. The project is
complete on disk after the unattended restore, but the panel may need one
project reload to display the new clip.

The resumable batch wrapper
`workflows/vrgdg-i2v-generator/run_remaining_scenes.ps1` checks both the saved
`done` status and the existence of the recorded MP4. It skips valid completed
scenes, renders sequentially and stops on the first failure.

Also measured on `BurningManGirl` on 2026-08-28: the batch rendered and restored
scenes **6–15** without intervention or failure. A final integrity pass found
**15/15** session segments marked `done`, with a non-empty MP4 and thumbnail for
every scene; the ComfyUI queue was empty. Running the same batch command again
reported no remaining scenes, confirming the resume/skip boundary.

## Wan 2.2 as an alternative engine — measured, and it is not the cheap one

Benchmarked on `the-man-watches` 2026-08-29, same keyframe, 81 frames at 24 fps
(3.38 s), through the bundled `wan22-i2v-4step.json` and
`local_workflows/my_video_wan2_2_14B_flf2v.json`.

| engine | resolution | frames | wall clock |
|---|---|---|---|
| **LTX 2.3**, upscale off | 1280×720 | 273 | **3 min 23 s** |
| Wan 2.2 14B i2v, LightX2V 4-step | 640×640 | 81 | **30.9 min** (cold) |
| Wan 2.2 14B first-to-last-frame | 640×640 | 81 | **13.1 min** (warm) |

**LTX is roughly four times faster at four times the pixels and three times the
frames.** Per pixel-frame the gap is about fiftyfold. The four-step LoRA does
reduce the step count as advertised; what it cannot reduce is loading **two 14B
fp8 UNets — about 27 GB — per clip** on a bandwidth-bound integrated GPU. Step
count beats parameter count only when the parameters are already resident.

The 30.9 vs 13.1 minute spread between the two Wan runs is the cold load. Budget
~13 min per clip in a warm batch, ~31 for the first.

**So Wan is not a replacement for LTX here; it is a special-purpose tool.** The
thing it buys that LTX does not is `WanFirstLastFrameToVideo`: given a start
frame and an end frame it generates the motion between them, so an action can be
*authored* rather than described and hoped for. At 13 minutes a clip that is
affordable for a handful of shots where a specific thing has to happen, and
unaffordable for a whole film.

Both engines produced coherent, believable crowd motion at these settings, and
i2v **ignored a prompt instruction to hold a subject still** — the character
walked off with the crowd. That is the failure first-to-last-frame exists to fix.

### Trap: node order does not tell you which frame is which

`WanFirstLastFrameToVideo` reads `start_image` from node **68** and `end_image`
from node **62** in the shipped graph — the higher id is the *start*. A role
prober that lists image loaders in numeric order will imply the opposite, and
feeding them backwards renders the shot in reverse: a working mechanism that
looks like a broken one, at 13 minutes a look. Read the consuming node's input
names, never the loader order.

## It was never a deadlock. It was 1,486 seconds per step

**This section replaces two earlier wrong conclusions and is the corrected
record.** 2026-08-29 it was written here that LTX "deadlocks", first blaming the
upscale pass, then the Q6_K GGUF loader, then declaring the engine unavailable.
All three were wrong, and they were wrong for the same reason: **the progress
bar is not in the log that was being read.**

| log | carries `s/it` progress |
|---|---|
| `ComfyUI/user/comfyui.log` (the Python log) | not for these runs |
| `ComfyUI-Installs/ComfyUI/logs/comfyui.log` (the Desktop wrapper) | **yes** |

Read the wrapper log and the "silence" turns out to be work:

```
 0%|      | 0/8 [00:00<?, ?it/s]
12%|##3   | 1/8 [24:46<2:53:26, 1486.59s/it]
25%|##5   | 2/8 [49:44<2:29:17, 1492.96s/it]
```

**~1,490 s/step, against the 26 s/step measured on film 1** - roughly 57x
slower, for a job at a quarter of the pixels and a quarter of the frames. The
process was healthy the whole time. A "hang" that is really a pathological
slowdown looks identical from outside, and the only thing that tells them apart
is a progress line.

### What made it slow, and what did not

The run that produced those numbers was **not** VRGDG's own graph. It was a
hand-modified copy, and the modifications are the suspects:

| | shipped `Singlei2vForUI_API.json` | the slow copy |
|---|---|---|
| UNet | GGUF, selected through a `ComfySwitchNode` | GGUF wired direct, switch pruned away |
| int8 branch | present (node 938) and selectable | pruned out |
| `compute_dtype` | `default` | **`bf16`** |
| decoder | `VAEDecode` -> replaced with `VAEDecodeTiled` 256 by the generator | plain `VAEDecode` |

Forcing `compute_dtype: bf16` on a file whose whole point is
`convrot_w4a4 / asym_w4a8_int8 / int8_tensorwise` native ops is the change most
likely to have thrown it onto an emulated path.

### The path that works, and has 15 clips to prove it

`workflows/vrgdg-i2v-generator/` reads VRGDG's **shipped API workflow**
(`custom_nodes/comfyui-vrgamedevgirl/Workflows/UsedForUIDoNotTouch/Singlei2vForUI_API.json`,
74 nodes) and patches scene values into it. It rendered **BurningManGirl scenes
6-15 unattended, 15 of 15 complete**. That is the reference implementation.

**Do not rebuild an LTX graph from `build_i2v_prompt` and prune it.** Pruning
removes the switch node and the alternate loader, and the result is a graph that
is subtly not the one anyone has ever measured. Use the generator.

### The rule this cost a day to learn

**Never diagnose a hang from the absence of output.** Confirm the progress bar
in the wrapper log first. If a job looks stalled: find the `s/it` figure, and
only call it a hang when there is no progress line at all after the model has
loaded and the wrapper log has been checked.
