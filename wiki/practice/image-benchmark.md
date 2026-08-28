---
title: Benchmarking the image models — how to compare eighteen fairly
status: assumed
updated: 2026-08-28
sources: [../comfyui/image-recipes.md, ../comfyui/models.md, casting.md, measuring-before-believing.md]
---

How to build a comparison across every installed image model that tells you
which one to reach for. The method, not the results — the measured settings and
timings live in [image recipes](../comfyui/image-recipes.md).

The reader's version of this plan is [`docs/image-bench.html`](../../docs/image-bench.html).

This is the [screen test](casting.md) generalised. Casting asks *which model
holds this character*; a benchmark asks *what is each model for*. The instrument
is the same and the axes are different.

`status: assumed` — the graphs and recipes are measured, but this comparison
design has not been run end to end. It is a plan with evidence under it, not a
result.

---

## What we know

### The axes are per family, so a global grid is the wrong shape

Klein has no LoRA column. SDXL has no encoder column. A single models × axes
grid would be mostly empty cells, and filling it would mean testing things that
cannot vary. The structure that fits is:

- **one fixed scene** every model renders — same prompts, same seed, same size;
- **one knob strip per family**, varying only what that family can vary.

The per-family axis table is in [image recipes](../comfyui/image-recipes.md).

### Per-model recipes, not one global setting

Holding steps and CFG constant across models measures our ability to mis-drive
half of them. Three SDXL checkpoints embed their own recipe; Z-Image Turbo and
Base want different settings from the same architecture; Klein distilled and
Base differ by 5× in steps. The sweep must carry a recipe per model and **say so
in its output** — a comparison where the settings vary is only honest if it
declares that. [DECISIONS #24](../../DECISIONS.md).

### The prompt dialect problem

Illustrious and Pony checkpoints want booru tags; Z-Image, Klein and Flux want
prose. Sending one dialect to all eighteen advantages half the pool for reasons
that have nothing to do with model quality.

The fix: author each prompt in **both dialects** from one shared intent record,
run the tag families on both, and score prompt adherence against the single
natural-language intent — never against the tag string. The dialect effect then
appears *on the sheet* rather than hiding inside it.

### A shared seed buys less than it looks like

Within a family, one seed across models is a clean comparison — same noise, only
the weights differ. **Across** families it is bookkeeping only: different latent
channel counts and shapes mean the same integer produces unrelated noise. Say
which of the two a given sheet is doing.

### What the machine may print, and what it may not

Print: the technical gate (only when it fails), CLIP prompt adherence *within* a
prompt row, and wall-clock split into cold load and warm render.

Do **not** print: the weighted casting total (those weights were built for
casting one character, not for comparing capability), identity or look
consistency on single-seed cells, or adherence compared across different
prompts. A ranking that launders a guess as a measurement is worse than no
ranking — [DECISIONS #15](../../DECISIONS.md), and
[a number narrows, a look decides](measuring-before-believing.md).

### Tiers

| tier | shape | cost | answers |
|---|---|---|---|
| quick | 1 prompt × 18 models × 1 seed | ~28 min | what does each do with my prompt? which are broken? |
| standard | 7 prompts × 18 models, ordered by model | ~2.5 h | what is each model *for*? |
| deep | + per-family knob strips | +1 h per family | what are this model's best settings? |

---

## What it costs

Cold loads dominate. Measured cold-inclusive renders ran **26–148 s** across
the pool, and the load portion alone reached ~95 s on `flux1-dev` (148 s cold
against 52.6 s warm). Warm renders are far cheaper: 14.1 s for Z-Image, 10.6 s
for Klein distilled.

**Order by model, not by prompt — from the standard tier upward.** With 7
prompts that is 7 renders per load instead of 18 reloads per prompt. It buys
nothing in the quick tier, which is one render per model however it is ordered.

---

## Traps

**System RAM is the binding constraint, not VRAM.** Order the sweep so
`flux1-dev` (23.8 GB) and the FluxDAIO (17 GB) never share residency, and flush
between them. Ignoring this took the backend down mid-run on 2026-08-28. See
[this machine](../comfyui/this-machine.md).

**Vary the seed between every cell**, or ComfyUI's prompt cache returns a
2-second non-render that the harness records as a real timing.

**The calibrated bands were measured on portraits.** Every band in
`lib/screen_test.py` — face 0.21–0.70, look 0.58–0.97, adherence 0.29–0.39,
detail 0.0035–0.020 — came from close-up portrait renders. A prompt with no
people, or an illustration, may sit outside the detail band and be flagged as
broken when it is fine. Check by eye before demoting anything.

**A model is not demoted for our own driver bug.** A render failure counts
against a model only when it is about that model —
[DECISIONS #21](../../DECISIONS.md).

---

## Open questions

- Should the benchmark live in `tools/graphics/screen_test.py` or beside it? It
  shares matrix expansion, the contact sheet and the render clock, but not the
  identity axes.
- What is the right prompt suite? Seven is a proposal: photoreal face, hands and
  full body, wide environment, text in image, multi-subject binding, stylised
  illustration, and one long constraint-heavy prompt.
- Is there an OCR check worth installing? Text rendering is the capability that
  most separates current models and is judged by eye today.
