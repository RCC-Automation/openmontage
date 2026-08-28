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

| | base pass | upscale refine |
|---|---|---|
| 1280×720, 273 frames | 8 steps, **26 s/step** — 3 min 23 s | 3 steps, **610 s/step** — 30 min 19 s |
| 1920×1080 | 8 steps, **141 s/step** — 18 min 49 s | never completed (2.5 h, then killed) |

**The refine pass is 24× more expensive per step than the base render.**
Doubling resolution should cost roughly 4×; 24× is the machine out of headroom.
Three "refinement" steps cost ten times the entire main render.

At 1920×1080 the second pass has never finished. At 1280×720 it finished once
in 30 minutes, and on the next scene the process died with a native stack fault
after it completed — no Python traceback, no video written.

## What to do

**Turn the upscale off.** A scene then costs ~3.5 minutes instead of ~35, and
stops losing renders to crashes. The output is the base resolution rather than
an upscaled 2×.

Either clear `upscale_model_name` in the Builder's LTX settings, or set the
second sigma schedule to `0.0`. In the exported standalone workflow that is
`--no-upscale`.

## Traps

**"Did not finish before the 2-hour wait limit" usually means hung, not slow.**
The Builder gives up at two hours; ComfyUI does not. Check the log: a completed
progress bar followed by hours of silence is a deadlock, and "wait then use
Recover Scene Videos" will not help because there is nothing to recover.

**A deadlocked job ignores `/interrupt`.** The interrupt flag is only checked
between node executions, so a job stuck inside one call never sees it. The
escape hatch is `POST /free {"unload_models": true, "free_memory": true}`,
which released 19 GB and cleared a job that `/interrupt` alone could not.

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
