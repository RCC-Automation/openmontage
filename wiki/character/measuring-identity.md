---
title: Measuring identity — ArcFace, CLIP, and what each one sees
status: measured
updated: 2026-08-25
sources: [../../DECISIONS.md]
---

You cannot hold a character you cannot measure. Two metrics do the work here,
they disagree with each other usefully, and both were calibrated against
renders from [this machine](../comfyui/this-machine.md) rather than taken from
a paper.

---

## ArcFace — is this the same person?

InsightFace `buffalo_l`: detect the face, align it to canonical landmarks,
embed it, compare embeddings by cosine similarity. CPU through onnxruntime,
about 0.3 s per image, so it is cheap enough to run on every candidate.

**Calibrated bands, measured here:**

| Score | Means |
|---|---|
| 0.10 – 0.21 | different people |
| ~0.30 | barely above strangers — treat as drift |
| 0.70+ | recognisably the same person |
| 0.92 – 1.00 | the same woman every time |

### The score is only valid where the face is big enough — measured 2026-08-29

**Report face fraction beside every identity number, and refuse to score below
1% of frame.** The cosine does not degrade gracefully as the face shrinks; it
becomes noise that is indistinguishable from a measurement.

Measured across one character at two shot sizes, prompt-only renders:

| shot | face fraction | identity |
|---|---|---|
| close-up | 12.0 – 56.2% | all 18 scored, 0.19 – 0.42 |
| full body | 0.35 – 5.2% | **7 of 18 fell under 1% and are not scoreable** |

Among the seven: a **negative** cosine (−0.041), and — worse — the model that
had *won* the close-up round on identity. Reporting its −0.041 as a result would
have been inventing one.

`lib/shot_size.py` computes both numbers from the same detector pass that
identity already runs, so this costs nothing. `MEASURABLE_FACE_FRACTION = 0.01`
is the gate.

This is `DECISIONS.md` #40 turned into a check rather than a warning: an
afternoon was once spent on identity numbers read off frames where the face was
a handful of pixels.

The raw band was rescaled 0.21 → 0.70 after measuring; the unscaled numbers are
compressed into a range too narrow to act on.

**What it cannot do:** it measures *faces*. A render can hold the face perfectly
and lose the pink hair and the brass collar, and ArcFace will not notice. It
also needs a detectable, reasonably sized, roughly frontal face — profile views,
small faces in wide shots, and non-human subjects all degrade it.

---

## CLIP — does this look like the same *thing*?

Two uses, and they are different:

- **`look_consistency`** — CLIP image-to-image similarity across a candidate's
  own renders. Catches the costume-and-palette question ArcFace ignores.
  Calibrated 0.58 → 0.97.
- **`prompt_adherence`** — CLIP image-to-text against the brief. Answers "did it
  render what was asked for", which is a different question from identity
  entirely. Recalibrated 0.29 → 0.39.

---

## The disagreement is the point

The clearest example measured here: juggernautXL scored **look 0.88, face 0.31**.
Costume and palette held; the person changed completely between every seed.

A pipeline scoring on CLIP alone passes that model. A pipeline scoring on
ArcFace alone cannot tell you the collar went missing. You need both, and you
need to read them as answering different questions:

> **face** — is she the same person?
> **look** — is she wearing the same things, lit the same way?
> **brief** — is this what we asked for at all?

---

## The five axes, and their weights

| Axis | Weight | What it is |
|---|---|---|
| `identity_stability` (ArcFace) | 0.30 | same person across seeds |
| `prompt_adherence` (CLIP) | 0.25 | rendered what was asked |
| `technical` | 0.20 | **a gate, not a score**: 1.0 usable, 0.0 broken |
| `look_consistency` (CLIP) | 0.15 | same costume and palette |
| `speed` | 0.10 | relative to the slowest candidate |

`technical` being a gate rather than a quality measure matters: a low technical
score usually means the checkpoint is **mis-driven**, not bad. See
[what-we-measured](what-we-measured.md).

An axis that could not be computed is **left out and the ranking reweighted
around it**, never defaulted to zero. A missing measurement is not a bad score.

---

## The house rule

**Calibrate against output from this machine, or ship the axis marked NOT
CALIBRATED with the population it needs.**

Four guessed bands have been checked here. All four were wrong. One was wrong by
an order of magnitude; one — `look_consistency` — was wrong in the quieter way,
scoring every real candidate 0.80–0.90, which reads as agreement rather than as
a broken axis. (`DECISIONS.md` #27, #31.)

The newest example is live: `beat_map.confidence` ships marked NOT CALIBRATED,
and the one real track measured sits at 0.833 against a 0.85 threshold — a
verdict decided by a single interval, which is not a measurement.
(`QUESTIONS.md` Q1.)

---

## Traps

**A low identity score is a flag, not a verdict.** A scene where she is in
shadow, or turned away, will score low and be exactly right. Look before
believing the number.

**A perfect score deserves suspicion.** `face 1.00` should prompt you to check
the renders are three distinct files rather than one image counted three times.
It was checked here and was genuine — but checking cost seconds and would have
caught a real bug.

**Timings corrupt easily.** They are measured from submission, so a busy machine
records a load as a render. `queue_depth()` is checked before each render;
unknown depth is treated as busy, because losing a clean sample only slows
learning while keeping a dirty one corrupts it silently.
