---
title: What we measured about character identity
status: measured
updated: 2026-08-26
sources: [../../DECISIONS.md, ../../PROGRESS.md]
---

Every number on this page came from renders on
[this machine](../comfyui/this-machine.md), scored with the calibrated axes in
[measuring-identity](measuring-identity.md). Where the wider literature
disagrees, that is noted on [techniques](techniques.md) — but these are the
numbers we would bet on, because we watched them happen.

---

## The seed is not the character. The description is.

This is the most useful thing we know, and it is the opposite of what most
people assume when they first pin a seed.

| What was held fixed | What varied | Identity score |
|---|---|---|
| model, prompt | **seed** | **0.66** |
| model, **seed** | prompt | **0.47** |
| — | different people entirely | 0.10 – 0.21 |

Holding the seed and changing the prompt drifts the face **more** than holding
the prompt and changing the seed. A fixed seed buys **reproducibility** — the
same model, prompt and seed reproduce byte-identically, which is why sweeps pin
7777 — but it does not buy a character.

**What follows from it:** every scene description must re-state the character in
full. Never "the same heroine", never a pronoun with no antecedent. This is not
style advice; it is the mechanism.

**It has already failed in production once.** A scene whose description said
*"The same clockwork heroine"* rendered a visibly different woman — face 0.34,
look 0.33. Re-stating the description fixed it to 0.55 / 0.68 with nothing else
changed. (`DECISIONS.md` #29, #33.)

---

## A reference image is worth about 4× a description — until the framing moves

| Shot | Description only | With a close-up reference |
|---|---|---|
| close-up | 0.213 | **0.932** |
| medium | — | 0.301 |
| wide | — | 0.493 |

On a **matched** shot the reference is transformative. Change the framing and it
collapses — the medium shot with a close-up reference scored *worse* than a bare
description on a matched shot.

**What follows from it:** one approved reference **per shot family** — close,
medium, wide — not one reference for the character. A cast record that carries a
single image is a cast record that will fail the moment the camera pulls back.
(`DECISIONS.md` #30.)

---

## A face crop holds across a full-body framing on Klein — 2026-08-26

The collapse above (0.932 → 0.301 medium, 0.493 wide) was a *whole render*
used as the reference. Giving Klein's multi-reference route a **head-and-
shoulders crop of the face** and asking for a full-body shot behaved very
differently, on the Burning Man character:

| framing asked | n | ArcFace to the face crop | frame the face occupied |
|---|---|---|---|
| full body, front | 8 | **0.62 – 0.78**, mean 0.71 | 1.7 – 3.2 % |
| full body, three-quarter | 8 | 0.48 – 0.70, mean 0.62 | 2.9 – 4.2 % |

Every one of the sixteen was recognisably her by eye. So the earlier wide-shot
number was at least partly the *reference's* framing, not only the target's:
a close-up render carries a background and a torso the model tries to keep,
where a face crop carries the face. This is why the workflow's three masters
are a face crop plus two full-body views, and why `scripts/masters.py` crops.

Two things to know when reading these numbers. **Scores are against the
largest face**: a festival prompt put bystanders in 14 of the 16 frames, and a
scorer that demands exactly one face reports "no face" for all of them
(`HANDOFF.md`). And Klein at 832×1216 with a reference is **55–77 s per
render**, not the ~5 s of the Builder's 1024×576 default.

## The description carries the identity — confirmed from the other side

The clockwork heroine's brief names a costume ("brass filigree collar, amber
workshop light") and her 48-seed sweep found 6–19 siblings per render at
cosine ≥ 0.55, nearest neighbours ~0.60. The Burning Man brief names a **face**
("plaits, brown eyes, blonde, cute face, French") and the same sweep on the
same model found **20–37 siblings**, nearest 0.65–0.69, with two clusters
instead of six. Same seeds, same checkpoint; only what the prompt described
changed. `DECISIONS.md` #29 measured this by holding the seed and moving the
prompt; this is the same finding from a prompt that happened to describe the
right thing.

## Models differ enormously at holding a face, and single frames cannot tell you

From the casting rounds of 2026-08-24/25, same prompt, three seeds:

| Model | face | look | brief | verdict |
|---|---|---|---|---|
| zImageUltimateNSFW_v20 | **1.00** | 1.00 | 0.25 | the same woman, every time |
| darkBeast30 | 0.92 → 0.78 | 0.95 | 0.38–0.43 | holds, with variation |
| juggernautXL_ragnarok | **0.31** | 0.88 | **0.87** | reads the brief, three different women |
| gonzalomoZpop_v40 | **0.28** | 0.91 | 0.47 | three different women |

Two things worth sitting with:

**The two properties you want live in different models.** The model that renders
actual clockwork (0.87 on the brief) is the one that cannot hold a face (0.31).
The model that holds a face perfectly renders generic armour (0.25).

**`look` stays high while `face` collapses.** juggernautXL scored 0.88 on look
and 0.31 on face — the costume and palette are consistent while the *person*
changes completely. A pipeline judging on CLIP alone would have passed it. This
is the entire reason [both axes exist](measuring-identity.md).

**A single frame cannot show you any of this.** All four looked plausible in
round one. The drift only appears across seeds.

---

## Distilled checkpoints look broken until you drive them right

Checkpoints carrying DMD, LCM, Turbo or Lightning in the name are trained for
CFG ~1 and ~10 steps. Run one at CFG 4.5 for 35 steps and it returns saturated,
posterised output that reads as a corrupt file.

Two installed checkpoints were written off that way for a whole session. Driven
correctly they became the **fastest good models on the machine** — 35 s → 10 s,
sharpness 0.07 → 0.45 and 0.00 → 0.39.

Many merges embed the graph they were made with in `__metadata__.prompt`;
`lib/model_registry.infer_sampler_recipe` reads it. Six of the installed
checkpoints carry one. (`DECISIONS.md` #24.)

**But a recipe only transplants into a graph of the same shape** — see
[comfyui/models](../comfyui/models.md).

---

## Open questions

- Whether a trained character LoRA beats all of this, and whether one can be
  trained here at all — [lora-training](lora-training.md), `QUESTIONS.md`.
- `look_consistency` has never been shown a render that **keeps the face and
  drops the costume**, which is the failure it is named for. Every population
  measured so far varies both together. (`DECISIONS.md` #31.)
