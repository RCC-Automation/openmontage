---
title: Choosing an identity mechanism — the hierarchy, measured
status: measured
updated: 2026-08-29
sources: [measuring-identity.md, face-swap.md, faceid-on-this-machine.md, reference-conditioning.md, lora-training.md, ../comfyui/image-recipes.md]
---

Four ways to put a specific person in a frame, all measured against the same
approved anchor, at two shot sizes, across a 19-model pool. Until now each had
been measured in its own run against its own baseline; this is the first time
they have been ranked in one comparison, which is what a decision needs.

Measured 2026-08-28/29 on `projects/burningman`, one character, ArcFace cosine
against `anchor/anchor.png`, 26 scored cells.

---

## What we know

### The hierarchy

| mechanism | close-up | full body | cost |
|---|---|---|---|
| **ReActor face swap** | **0.77 – 0.79** | **0.76 – 0.77** | 6 s, on top of any render |
| Klein reference latent | 0.716 | *unmeasurable* | 30–42 s |
| IP-Adapter FaceID | 0.573 – 0.685 | 0.618 – 0.696 | 42–75 s |
| her trained LoRA | 0.392 | 0.358 | 39 s |
| **any description, all 19 models** | **0.18 – 0.42** | **0.18 – 0.40** | the render itself |

Against the bands on [measuring-identity](measuring-identity.md), where 0.70+
is "recognisably the same person" and 0.10–0.21 is "different people".

### No model renders her from her description

The best prompt-only score in the pool is **0.418**, and the median is ~0.29.
That is the family-resemblance-to-stranger band. It holds across SDXL merges,
Z-Image, both Klein files, Flux.1, Chroma — **and Qwen-Image 2512**, the
strongest instruction-following model available here, which scored 0.399 and
came *eighth*, below a Pony merge.

That last point is the one worth carrying: adding a better model did not raise
the ceiling. **The ceiling is a property of text-to-image, not of this pool.**
Effort spent shopping for a model that "holds her" is effort wasted; the
mechanisms are where the difference is.

### The face swap is the only mechanism indifferent to framing

It scores the same at head-and-shoulders and at full length, because it operates
on pixels after the render and never sees the prompt. Everything else degrades
or becomes unmeasurable when the face gets small.

It also works on **any base model**: three different bases landed within 0.024
of each other. So pick the base for the picture and attach identity afterwards.

**Its failure mode is silence.** One swap returned an image with no detectable
face at all — the target render's face was 1.27% of frame and ReActor needs a
face it can find. Nothing errors. Check the output, or check the target's face
fraction first ([shot-size](../practice/prompting.md) covers the same measure).

### FaceID is the conditioning route that survives distance

This answers an open question on
[faceid-on-this-machine](faceid-on-this-machine.md), which could not tell
whether the embedding path survived a framing change because every wide render
had been pulled into a portrait.

| framing | `start_at` | identity | face fraction |
|---|---|---|---|
| close-up | 0.0 | 0.573 | 23.0% |
| close-up | 0.4 | 0.685 | 14.8% |
| full body | 0.0 | **0.696** | 7.6% |
| full body | 0.4 | 0.618 | 6.1% |

It holds. But the face fractions give away the cost: prompt-only full bodies sit
at 0.35–5.2%, and FaceID's are 6.1–7.6%. **It is still pulling the camera in**,
just not far enough to destroy the shot. The framing override is real and
`start_at` trades it against identity in both directions.

Klein's reference latent, by contrast, became **unmeasurable** at full body —
its face came in under 1% of frame. That is the latent-vs-embedding split from
[reference-conditioning](reference-conditioning.md) showing up as a measurement.

### The trained LoRA does not compete

0.392 close-up, 0.358 full body — below the best plain description on a
different model. It does hold its level across framings, because it is baked
into the weights rather than conditioned per-render, but the level is too low to
matter. This reproduces `DECISIONS.md` #39 on a fresh run.

**Caveat, stated rather than hidden:** this is one checkpoint
(`bmgrlbr_1500_steps`) at one strength (0.9), not a swept result. The ceiling of
the route was established in [lora-training](lora-training.md); this run only
confirms it sits where that page said.

### Model ranking does not transfer between shot sizes

Chroma is 16th at close-up (0.281) and **1st at full body** (0.401). Juggernaut
goes 5th to 12th. Casting a model on close-up evidence and then shooting wides
with it is not supported by anything measured here.

---

## What it costs

The swap is the cheapest thing on the list at ~6 s, and it runs after a render
you were making anyway. FaceID and reference conditioning cost a full render
each. Training cost days and lands last.

---

## Traps

**A face swap that finds no face writes an image anyway.** No error, no warning.
Verify the output or pre-check the target's face fraction.

**Every number here is gated on face fraction.** Seven full-body cells were
excluded as unmeasurable, one with a *negative* cosine, including the model that
won the close-up round. See [measuring-identity](measuring-identity.md).

**Do not read the close-up ranking as a casting decision for wide shots.** It
inverts.

---

## Open questions

- Is there a mechanism that survives genuinely wide shots, or is the honest
  answer that at that distance the audience cannot see her face and identity
  stops mattering?
- Would a LoRA from a trainer that reaches the text encoder change the last row?
  A research pass has challenged the *explanation* in `DECISIONS.md` #39 —
  arguing a trigger token does not require text-encoder training — without
  challenging the measurement. Worth resolving before anyone trains again.
- Does FaceID stack with a face swap, or do they fight?
