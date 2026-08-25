---
title: This machine, and why it decides everything
status: measured
updated: 2026-08-25
sources: [../../HANDOFF.md, https://github.com/ROCm/ROCm/issues/6034, https://huggingface.co/docs/bitsandbytes/main/en/installation]
---

Almost every guide you will read about ComfyUI, LoRA training and diffusion
tooling assumes an NVIDIA card. This is not one. That single fact invalidates
more advice than any other property of the setup, so it belongs at the top of
any page that recommends a tool.

## What it is

| | |
|---|---|
| Host | Windows 11, device `desktop-gfe43h0` |
| GPU | **AMD Radeon 8060S** (`gfx1151`, Strix Halo iGPU) |
| VRAM | ~90 GB reported — **unified memory**, shared with system RAM, not dedicated |
| RAM | 64 GB |
| Stack | **ROCm 7.14**, PyTorch 2.12.0+rocm7.14.0, Python 3.13.12 |
| Attention | pytorch attention; `comfy_kitchen` HIP backend available (fp8/int8/w4a4/AWQ kernels) |
| ComfyUI | 0.32.0, Desktop install |

## Two flags that change everything — measured 2026-08-25

Before the constraints, the two things that make this machine far more capable
than its reputation. Both were verified here, not read.

### `TORCH_ROCM_AOTRITON_ENABLE_EXPERIMENTAL=1`

PyTorch-ROCm ships **AOTriton** — ahead-of-time-compiled flash and
memory-efficient attention kernels — but gates them behind an env var on
`gfx1151` because they are marked experimental. Without the flag, attention
falls back to a math path that materialises the whole attention matrix.

Measured here, pure SDPA forward + backward, batch 4 × 8 heads × 2048 × 64, bf16:

| | time (30 steps) | peak memory |
|---|---|---|
| unset | 2.164 s | 2.250 GB |
| **`=1`** | **0.264 s** | **0.094 GB** |

**8.2× faster and 24× less memory.** PyTorch prints the hint itself at every
SDPA call, and the warning disappears once the flag is set.

**"No Triton" does not mean "no flash attention"** — AOTriton is prebuilt
inside the torch ROCm wheel. This is probably the single most valuable thing on
this page: it applies to *rendering*, not just training, and the memory
reduction directly addresses the OOM that killed the backend on 2026-08-25
(see [failure-modes](failure-modes.md)).

Do **not** set `PYTORCH_HIP_ALLOC_CONF=backend:malloc` — it crashes PyTorch on
this stack.

### `bitsandbytes` works — our own docs were wrong

`HANDOFF.md` said bitsandbytes was unavailable. **It is not.** Verified here on
2026-08-25 against the ComfyUI venv (torch 2.12.0+rocm7.14.0, Python 3.13.12,
gfx1151):

```
bnb version : 0.50.1
bnb backend : ROCm | lib: CudaBNBNativeLibrary
state keys  : ['absmax1','absmax2','qmap1','qmap2','state1','state2','step']
  state1: dtype=torch.uint8   state2: dtype=torch.uint8
param moved : 1.049e-03  ->  OPTIMIZER IS STEPPING     finite: True
```

`AdamW8bit` steps with genuine `uint8` optimiser states. bitsandbytes 0.50.x
ships one fat wheel per platform bundling `libbitsandbytes_rocm714.dll`, and
picks the backend from `torch.version.hip` at import.

**This unblocks every kohya-family trainer**, all of which reach for
`AdamW8bit` by default — including VRGDG's own bundled LoRA trainer, which
hard-codes it.

A cosmetic `Could not detect ROCm GPU architecture: [WinError 2]` appears at
import; it shells out to a `rocminfo` binary not on PATH and does not affect
anything.

## What genuinely is unavailable

**Triton and SageAttention.** These remain absent, and rule out a long tail of
custom kernels including several quantisation and speed-up node packs.
`xformers` likewise — but with AOTriton enabled, PyTorch's own attention is no
longer the slow path it was.

## The memory is unified, and that cuts both ways

~90 GB "VRAM" is not 90 GB of dedicated card memory — it is system RAM the GPU
can address. That is why unusually large models load at all. It is also why
**capacity is not the constraint; memory bandwidth is**, and why a run can
exhaust memory in a way a discrete card would not.

Prefer **fp8, GGUF and int8-convrot** weights. The last of these matches the
HIP kernels directly.

## Traps

**Memory pressure kills the backend, not the render.** A four-model × three-seed
sweep ran out of memory, and then the OOM *handler* aborted the process —
`unload_all_models` tried to move tensors off the device, that allocation failed
too, and Python called `abort()`. The result is a dead server mid-round with
every result lost, not a failed job with an error. See
[failure-modes](failure-modes.md).

**The Desktop app survives its own backend.** When the Python server dies, the
Electron window stays open and looks completely normal. Ten `Comfy Desktop`
processes alive with **nothing listening on port 8188** is the signature. Check
the port, not the window.

## Open questions

- Whether diffusion training is viable here at all, and with which trainer and
  optimizer — see [character/lora-training](../character/lora-training.md).
- Whether WSL2 or a dual-boot Linux would materially change the answer.
