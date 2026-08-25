---
title: This machine, and why it decides everything
status: measured
updated: 2026-08-25
sources: [../../HANDOFF.md]
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

## What is unavailable, and what that rules out

**Triton, SageAttention, xformers and bitsandbytes do not work here.** Anything
that needs them will fail, or — worse — silently fall back to something slower
and different.

The consequences are specific and worth knowing before you plan work:

- **`bitsandbytes` absent means no 8-bit optimizers.** Most LoRA training guides
  reach for `AdamW8bit` by default. That option does not exist here, and the
  fallback changes the memory budget the whole guide was written around.
- **`xformers` absent means no memory-efficient attention** from that path.
  PyTorch's own attention is what runs.
- **`Triton` absent rules out a long tail of custom kernels**, including several
  quantisation and speed-up node packs.

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
