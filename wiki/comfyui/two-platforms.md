---
title: Two ComfyUI installs, split by engine
status: measured
updated: 2026-08-31
sources: [this-machine.md, failure-modes.md, ../vrgdg/video-render.md]
---

This machine runs **two** ComfyUI installs against one GPU, and which one a job
belongs on depends on the engine. That is not a preference; it is what nine
hours of matched measurement on 2026-08-29/30 says.

| | Windows (Comfy Desktop) | WSL (Ubuntu-24.04) |
|---|---|---|
| default port | 8188 | 8189 |
| torch | 2.12.0+rocm7.14.0 | 2.11.0+rocm7.13.0 |
| reported VRAM | 87.9 GiB | 95.7 GiB |
| custom nodes | 25 packs, the full production stack | VRGDG, GGUF, KJNodes, LTXVideo, ReActor, IPAdapter |

**Both report far more "VRAM" than the machine has.** System RAM is **63.6 GiB**
and the GPU shares it; the 87.9 / 95.7 figures count shared memory and are not a
budget you can spend.

---

## What we know

### The split, by measurement

Wan 2.2 I2V at 640x640 / 81 frames, SDXL at 1280x720, LTX through the generator's
known-good graph. Three runs each, cold and warm reported separately, identical
inputs, sized to what memory is actually free.

| workload | Windows | WSL | winner |
|---|---|---|---|
| SDXL image, sampling | **16.8 s** | 20.7 s | Windows, 19% |
| LTX 2.3, warm end-to-end | **292.7 s** | 743.8 s | Windows, 2.5x |
| **Wan 2.2 I2V, warm** | 1341 s | **905 s** | **WSL, 33%** |

**Run Wan in WSL. Run everything else on Windows.**

The Wan gap is in sampling, not loading: **861 s against 1296 s**, so Windows
takes 50% longer at the same work. Nothing we changed closes it - not the mmap
flag, not the attention backend, not model placement.

### The `--disable-mmap` flag should be off

It was in the Windows launch args with no recorded reason, and this page's
predecessors cited it twice as a *contributing cause* of dead backends. Removed
and measured over three runs:

| | with the flag | without |
|---|---|---|
| cold model load | 72.5 s | **18.5 s** |
| peak RSS | 42.6 GiB | **36.5 GiB** |
| warm end-to-end | 1359.8 s | **1341.3 s** |

Four times faster loading, six gigabytes less memory, and marginally *faster*.
No downside appeared in nine runs. **Leave it off**, and note that on a
unified-memory machine the memory saving matters more than the speed.

### Both may run; two big jobs may not

2026-08-29: Windows died with `Windows fatal exception: access violation` inside
`load_torch_file` while an **idle** WSL held ~41 GiB. ComfyUI reported 77 GB
"usable" moments before. It was not an out-of-memory error and not a broken
library - it was 41 + 27 > 63.6 on a machine where GPU memory *is* system RAM.

**The rule that followed was wrong in shape.** "Never run both servers" is a
proxy for the real constraint and forbids combinations that fit. What matters is
the sum of *resident* weights against 63.6 GiB. Peak resident memory per job,
measured here:

| job | platform | peak |
|---|---|---|
| video | WSL | 43.7 GiB |
| video | Windows | 42.6 GiB |
| image | Windows | 27.7 GiB |
| image | WSL | 8.3 GiB |

So two video jobs cannot coexist however the processes are arranged, an image
job beside a video job can, and two idle servers cost almost nothing. Lifted to
a memory check 2026-08-30 at Raul's direction; `assert_headroom()` reads the
OS's free-physical number and refuses on it.

**When it is tight, `/free` first** - with the asymmetry below in mind.

### `/free` behaves differently on each

| | released |
|---|---|
| Windows | **14.6 GiB** |
| WSL | 0.8 GiB |

WSL keeps its allocation, and that is why the crash above happened after a
`/free` that looked successful.

**Corrected 2026-08-31.** This page previously said `wsl.exe --shutdown` was the
only thing that reclaims WSL's share. That was true of the behaviour and wrong
about the cause: `.wslconfig` had `memory=96GB` on a 63.6 GiB machine and no
`autoMemoryReclaim`, so WSL never met pressure and never returned its page
cache. With a cap below physical RAM and `autoMemoryReclaim=gradual`, memory
comes back without a shutdown — Windows went from 1.7 GiB available to 45.5.
See [WSL memory](wsl-memory.md).

## What it costs

**Every path our tooling hands to ComfyUI has to be translated for WSL.** Three
distinct incompatibilities, each failing at validation with a different message:

- absolute Windows paths (`C:\Users\...`) for project folder, audio, SRT, image folder;
- **model names with backslash separators** (`LTX_8bit\ltx-...`), which Linux lists
  with forward slashes - a missed one silently selects a different file rather
  than erroring;
- model files themselves, which must exist on the target.

`projects/the-man-watches/scripts/bench_suite.py::to_wsl_paths` handles the first
two. Production use would need the same inside `lib/vrgdg_bridge.py` and
`tools/video/vrgdg_project_sync.py`.

**Models must be on native storage.** `/mnt/c` reads at **155 MB/s** over 9p:
SDXL cold-loaded in 186.7 s from there against 14.7 s natively. Copy what a run
needs into the WSL filesystem, and verify byte size afterwards - a truncated copy
otherwise surfaces as a mystery later.

## Traps

**The port is not the platform.** Comfy Desktop reassigns ports when it thinks
one is busy, and a Windows instance can appear on 8189. Identify a server by its
reported `vram_total` - 87.9 GiB is Windows, 95.7 GiB is WSL - not by port.

**The WSL disk image only grows.** Deleting models inside WSL does not shrink
`ext4.vhdx`; that needs an explicit compact from Windows.

**A ComfyUI service outlives your shell, and a render outlives its runner.** A
submitted prompt keeps executing after the script that submitted it exits, and a
second run will queue *behind* it - so a naive re-measurement records queue wait.
Record the prompt id at submit time and reattach.

---

## Where the Wan weights live, and what routes to them

**2026-08-30: the Wan weights were deleted from Windows.** All 17 files - 116.5
GiB - now exist only in the WSL filesystem, each verified byte-identical against
its Windows original immediately before deletion.

| kept in WSL only | GiB |
|---|---|
| `wan2.1_14B_SCAIL_2_fp16` (character replacement) | 30.5 |
| `wan_animate_2_int8_convrot` (motion transfer) | 15.5 |
| `wan2.2_i2v` high + low noise 14B | 26.6 |
| `wan2.2_t2v` high + low noise 14B | 26.6 |
| `umt5_xxl_fp8_e4m3fn_scaled` (the Wan text encoder) | 6.3 |
| `wan2.1_fun_inp_1.3B_bf16` | 2.9 |
| six LoRAs - i2v, t2v, SCAIL, lightx2v | 6.2 |
| `wan_2.1_vae`, `Wan2_1_VAE_bf16` | 0.4 |

`clip_vision_h.safetensors` was **kept on Windows** despite being referenced only
by Wan workflows: its renamed twin `CLIP-ViT-H-14-laion2B-s32B-b79K` is what the
FaceID adapter loads, and 1.2 GiB is not worth the risk that one is ever
re-derived from the other.

### Routing is code, not discipline

**`lib/comfy_routing.py`** decides which server a workflow goes to. Routing per
*capability* cannot express this split - Wan and LTX are both "video" - so it
routes per workflow:

```python
server, graph = prepare("wan22-i2v-4step.json", graph)   # -> WSL, paths translated
server, graph = prepare("juggernaut-xl-txt2img.json", g) # -> Windows, untouched
```

Three things it does that matter:

- **matches by pattern, not by list**, so a new `wan22-*.json` routes correctly
  the day it is added rather than silently running where the weights no longer are;
- **identifies a server by its reported `vram_total`** (87.9 GiB Windows, 95.7
  WSL), because Comfy Desktop reassigns ports and a Windows instance did appear
  on 8189;
- **`assert_headroom()`** refuses when free physical memory is below the
  measured peak for the job about to run, and names `/free` or what to close.

`tests/contracts/test_comfy_routing.py` holds 20 tests on it. **A misrouted Wan
workflow now fails by finding an empty model dropdown - no error, no
explanation** - which is the same silent shape as the missing MSR LoRA in
`HANDOFF.md`, and is why the routing is tested rather than remembered.

`COMFYUI_WAN_SERVER_URL` (default `http://127.0.0.1:8189`) sets the WSL server;
`COMFYUI_SERVER_URL` (default 8188) the Windows one.

### Starting each server

Use the scripts, not Comfy Desktop's Start button:

    scripts/start_comfyui_windows.ps1     # port 8188, no --disable-mmap
    scripts/start_comfyui_wsl.sh          # port 8189, HSA_ENABLE_DXG_DETECTION=1

The Windows one pins the port explicitly and clears stale port locks first. On
2026-08-30 Comfy Desktop moved itself to 8189 - the Wan port - because of an
orphaned lock file, which would have sent LTX to the Wan server and Wan to a
server whose weights had just been deleted.
