---
title: Seeds — what they do, what they cannot do, how to sweep them
status: measured
updated: 2026-08-26
sources: [../character/what-we-measured.md, ../../DECISIONS.md]
---

The seed initialises the PRNG that draws a render's starting noise. On a fixed
prompt it is the dial that decides *which* person you get, which makes it the
variant generator when casting a character — render one description across many
seeds and pick the version you want.

What it is not is a coordinate. Seed 100000 and seed 100001 produce noise
tensors as unrelated as any other pair, because the mapping from seed to noise
is an avalanche function. That single fact answers most questions about seed
management, and the rest of this page is what we measured when we stopped
assuming it.

ComfyUI's `KSampler` accepts **0 to 18446744073709551615** (2^64 − 1). Every
value in that range was rendered successfully, including the boundaries and both
sides of 2^32 — there is no truncation and no aliasing.

---

## What we know

### Seed distance carries no signal

48 renders on one prompt, seeds `100000 + i × 1009`, 1128 pairs, scored by raw
ArcFace cosine:

| | |
|---|---|
| correlation between seed gap and face similarity | **r = +0.010, p = 0.73** |
| adjacent seeds (gap ≈ 1,009), 47 pairs | mean cosine 0.4760 |
| distant seeds (gap > 23,000), 300 pairs | mean cosine 0.4734 |
| difference | +0.0026, p = 0.82 |

Seeds a thousand apart give exactly as much variety as seeds forty-seven
thousand apart. **A "narrow" band of seeds is not a narrow region of anything.**

### Seed magnitude carries no signal either

Eight seeds spanning the full range — `0`, `1`, `42`, `2^32 − 1`, `2^32`,
`7391441554250`, `2^63`, `2^64 − 1` — all rendered normally. A big seed from
someone else's workflow is not a richer draw than `42`.

### Variety saturates early, and more seeds will not fix it

Same 48 renders, measured as the sweep grows:

| n | mean pairwise | distinct faces | best sibling pair |
|---|---|---|---|
| 6 | 0.4831 | 4 | 0.5923 |
| 12 | 0.4838 | 5 | 0.5923 |
| 24 | 0.4767 | 7 | 0.6453 |
| 48 | 0.4721 | **7** | 0.6696 |

Mean pairwise is flat from n=6 to n=48. **You are sampling a stationary
distribution, not exploring outward.** Distinct faces plateaus near 7–10 and
novelty per new render decays from 0.472 to 0.391. More seeds densify; they do
not expand. Rendering 500 instead of 48 mostly buys tighter sibling groups.

### Scattered draws may beat an arithmetic progression — unproven, but free

The distance test above cannot see this, because every pair in it comes from the
same progression. Run at equal n, same prompt, same model:

| | mean pairwise | distinct faces |
|---|---|---|
| arithmetic, span 47,423 | 0.4721 | 7 |
| scattered, span 1.8 × 10^19 | **0.4448** | **12** |

Scattered won on both. **Neither result is significant**: permutation test over
20,000 reshuffles gives **p = 0.054** on mean pairwise and **p = 0.26** on
distinct faces. An earlier 8-seed probe landed at the 1.6th percentile of the
bootstrap, so this is the second independent test leaning the same way — which
is more than either alone, and still not proof.

**Use scattered draws anyway.** It costs nothing and removes a question the
sweep design created. `scripts/anchor_select.py --seed-mode scattered`.

---

## What to do

- **To cast a character**: one prompt, 40–60 seeds, then pick by eye. See
  [casting](casting.md) and the chooser in `scripts/anchor_chooser.py`.
- **To get genuinely different characters**: change the conditioning, not the
  seed. Same seed with a different prompt drifts the face to 0.47; same prompt
  with a different seed only reaches 0.66 (`DECISIONS.md` #29). **The prompt is
  the stronger lever**, and a brief that names hair, wardrobe and lighting but
  no face structure gives ArcFace nothing to hold — which is exactly the brief
  we cast from.
- **To reproduce a render**: pin the seed *and* the prompt. A seed alone
  reproduces nothing if any conditioning moved.
- **Sibling count as a tiebreaker**: a version with many near-neighbours in the
  sweep is one the model can hit again, which makes it a better anchor than an
  equally good one-off. Count neighbours per image at a stated threshold, never
  the size of its cluster — see the trap below.

---

## Traps

**A fixed seed is reproducibility, not character consistency.** Hold the seed
and change the prompt and the face drifts *more* than holding the prompt and
changing the seed. `DECISIONS.md` #29.

**"Seed distance does not matter" is not "seed pattern does not matter."** They
are different claims and the obvious test only checks the first. We treated the
first as licence for a tidy arithmetic sequence and then measured that scattered
draws may be more varied. If you take one shortcut from this page, take
scattered.

**Cluster size is not a per-image sibling count.** A chooser that labels every
member of a 15-member cluster "15 siblings" reports the same number for the
dense centre and the ragged edge. Count each render's own neighbours above a
stated cosine.

**A tighter description raises reproducibility and shrinks your casting range.**
These are opposite goals. Which one you want depends on whether you are still
choosing a character or have already chosen one — do not let a reproducibility
gate push you into tightening a brief you are still casting from.

---

## Open questions

- Is the arithmetic-versus-scattered effect real? Two tests lean yes at
  p = 0.054 and p = 0.26. Settling it needs more sweeps at equal n, and the
  practical answer (use scattered) does not depend on the outcome.
