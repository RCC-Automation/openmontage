---
title: Measuring before believing
status: measured
updated: 2026-08-25
sources: [../../DECISIONS.md]
---

The house rule, and the reason it exists: **every constant this project guessed
turned out to be wrong when it was finally measured.** Not most. All of them.

## The four that were checked

| Guessed band | What it actually was | How it was wrong |
|---|---|---|
| `identity_stability` | 0.21 → 0.70 | compressed into a range too narrow to act on |
| `look_consistency` | 0.58 → 0.97 | scored every real candidate 0.80–0.90 |
| `prompt_adherence` | 0.29 → 0.39 | |
| detail / sharpness | band-limited, not monotonic | more detail scored *worse* past a point |

`look_consistency` is the instructive one. It was not obviously broken. It
returned plausible numbers in a plausible range, and those numbers read as
**agreement between candidates** rather than as an axis that could not
discriminate. A wrong constant that looks wrong costs an afternoon. A wrong
constant that looks reasonable costs a season of decisions.

## The rule

**Calibrate against output from this machine, or ship the axis marked NOT
CALIBRATED with the population it needs.**

Both halves matter. "NOT CALIBRATED" in a source comment is not an apology — it
tells the next reader exactly how much weight the number can carry, and naming
the population that would fix it turns a vague doubt into a piece of work
someone can do.

Live example: `beat_map.confidence` ships marked NOT CALIBRATED. The one real
track measured lands at **0.833 against a 0.85 threshold** — a verdict decided
by a single interval out of eighteen. That is not a measurement, and the page
says so. (`QUESTIONS.md` Q1.)

## Its siblings

**Never store anything derived from code in a cache.** The model registry cached
each family's driver alongside the model. When the driver resolution changed,
every scan reported the files unchanged and never refreshed — and a filename
this machine has never had went to ComfyUI for three consecutive sweeps.
Testing the resolver in isolation passed the whole time, because that reads from
code. (`DECISIONS.md` #22.)

**A verdict earned under one driver expires when the driver changes.** Two
checkpoints were marked broken, then became the fastest good models on the
machine once driven at their own settings. The verdict was about the driving,
not the model. (`DECISIONS.md` #23, #24.)

**Green tests against a fixture nobody checked hide the bug.** The music-reference
defect survived a full contract suite because the test fixture never wrote an
audio file to disk — so no test could see that the reference pointed at nothing.
The fix included fixing the fixture to match reality.

**Run it for real before believing it works.** Every design bug found in the
last two days came from a live run, not from a test: a lyric line duplicated
across a cut, a chorus shot labelled `verse`, a reaction parser that silently
dropped a typo, another that could not read a bare number at all. All had
passing tests over fixtures.

## What this looks like in practice

- A number in a doc carries where it came from, or it does not go in.
- A page in this wiki is `measured` only with a number and its provenance.
  Everything else is `researched`, `assumed` or `stub`.
- An axis that could not be computed is **left out and the ranking reweighted**,
  never defaulted to zero. A missing measurement is not a bad score.
- Unknown routes stay unknown in the render clock rather than being given a
  plausible number — and an unknown route is still allowed to run, or the clock
  could never learn it.
