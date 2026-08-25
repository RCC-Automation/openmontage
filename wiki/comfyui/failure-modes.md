---
title: How ComfyUI fails here, and how to tell which failure it is
status: measured
updated: 2026-08-25
sources: [../../HANDOFF.md]
---

Most of these do not look like errors. That is what makes them expensive: the
render returns something, or nothing, and the reason is somewhere else
entirely. Each one below cost real time on this project.

---

## Out of memory kills the process, not the job

The most destructive one. A four-model × three-seed sweep exhausted memory, and
then the recovery path died:

```
[ERROR] Got an OOM, unloading all loaded models.
Fatal Python error: Aborted
  comfy/model_patcher.py:1156 in unpatch_model
  comfy/model_management.py:2048 in unload_all_models
```

Freeing memory tried to move tensors off the device, **that allocation failed
too**, and Python aborted. So you do not get a failed render with an error — you
get a dead backend mid-round, every result lost.

**Symptoms:** the client reports "no candidate produced an image", which says
nothing about the real cause. `queue_depth()` returns `None`.

**How to tell:** check whether anything is listening on port 8188. If nothing
is, the backend is gone.

**How to avoid:** keep a round under about nine renders when it spans more than
one model family. VRGDG ships `build_clear_memory_prompt` — a graph whose whole
job is unloading models and freeing VRAM — which is the real fix, unapplied
because it may corrupt the render clock's timing samples (`QUESTIONS.md` Q6).

---

## The Desktop app outlives its own backend

When the Python server dies, the Electron shell keeps running and the window
looks completely normal. Ten `Comfy Desktop` processes alive with **nothing on
port 8188** is the signature.

This is genuinely confusing from the user's side — they look at an open
ComfyUI window and reasonably report that it is available. **Check the port,
not the window.** Recovery is a full quit and restart; a window left open from
before the crash is attached to a backend that no longer exists.

---

## A mis-driven checkpoint looks like a corrupt one

Distilled checkpoints (DMD, LCM, Turbo, Lightning in the name) want CFG ~1 and
~10 steps. At CFG 4.5 for 35 steps they return saturated, posterised garbage
that reads as a broken file. Two installed checkpoints were written off that way
for a whole session; driven correctly they became the fastest good models here.

**A low `technical` score is the tell** — it is a gate on the render, not a
judgement of the model. See
[character/what-we-measured](../character/what-we-measured.md).

---

## `list_models()` returns empty dicts when the server is down

Not an error — empty results. A caller that reads "no models" as "nothing
installed" will be wrong and quiet about it. Check `is_available()` first.

Its mirror: `VRGDGClient.unavailable_reason()` **always returns text**, whether
or not the client is available. It only means anything once `is_available()` is
`False`; printing both makes a healthy server look broken.

---

## The HTTP server stalls while loading weights

ComfyUI serves HTTP from the same process that reads the model off disk, so a
large first load can block a request for tens of seconds. A 10-second timeout on
`_history_entry` turned every slow first load into a failed render; it is now
60. **Budget for the stall in anything you add to the generation path.**

---

## A finished download can report as partial

The installer decides `[have]` two ways. Entries with a known expected size are
checked byte-for-byte and are trustworthy. Entries with `size = 0` are judged
**only** by a sidecar `<file>.complete` marker. Delete the markers and five
complete files report `[part] … will resume` with the byte count they have
always had.

That cost this project a documented claim that a 19.5 GB GGUF "may be truncated"
when it was byte-identical to the server all along. **Check the file, not the
report** — compare its size against the server's `Content-Length`.

---

## VRGDG names models it does not ship

The Builder's saved defaults set `msr_lora_name` to a Licon MSR LoRA that no
VRGDG download provides. LTX Reference-to-Video was silently unavailable with
nothing explaining why. If a mode refuses to run, **check whether the model its
settings name actually exists** before debugging anything else.

---

## A dead branch in a template blocks the whole graph

ComfyUI validates the *entire* submitted prompt. VRGDG's Z-Image template hangs
a `RAMCleanup → VRAMCleanup` pair off the VAE decode feeding nothing — and an
uninstalled node pack on a branch that cannot affect the output still blocks the
render. Unreachable nodes are pruned before submission for exactly this reason.
