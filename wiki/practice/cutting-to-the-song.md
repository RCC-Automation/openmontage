---
title: Cutting to the song — sections, beats, and clip length
status: measured
updated: 2026-08-31
sources: [../../scripts/retime_plan.py, ../../scripts/audit_timing.py, ../../projects/the-man-watches/artifacts/beat_map.json]
---

# Cutting to the song — sections, beats, and clip length

In a music video the track decides when to cut. That was the stated principle
for `The Man Watches` from its first day, and the implementation did something
else twice before anyone noticed — both times because the number that mattered
was never checked against the layer above it.

Related: [the song](the-song.md) · [checkpoints](checkpoints.md) · [directing the generator](directing-the-generator.md)

---

## What we know

### There are four layers and each can drift from the next

```
beat_map     measured from the delivered track
   |
song         section boundaries, aligned to the vocal
   |
scene_plan   34 scenes, retimed onto those boundaries
   |
session      what the Builder actually cuts to
```

Every join is a place two different steps have to agree, and nothing warns when
they stop. `scripts/audit_timing.py` checks all four and reports rather than
fixing.

### Failure 1: scenes fitted sections but not beats

The retime scaled each section's shots proportionally to fill it. Section
boundaries were right — they came from the aligned song — but the cuts *inside*
a section were arbitrary fractions.

| | before | after snapping |
|---|---|---|
| cuts within 0.12 s of a beat | **12 / 33** | **29 / 33** |
| median offset | 0.18 s | **0.00 s** |

The fix: place cuts proportionally, then move each to the nearest beat that
still leaves every remaining shot above the 1.5 s floor. At 86.13 BPM a beat is
**0.70 s**, so the floor is about three beats and there is normally room.

**The four that stay off-grid are section boundaries**, placed by `lyric_align`
against the vocal. A verse can legitimately begin between beats, and moving it
would break sync with the words. Leave them.

### Failure 2: every clip was rendered at one fixed length

81 frames is the benchmark configuration — it is what every timing on this
machine refers to. It was left as the *default for real renders*, so 34 scenes
with 34 different lengths all got 5.06 s:

- **27 shots are shorter than 5.06 s** → the clip overruns and the Builder cuts it
- **7 are longer** → the clip runs out and leaves a gap. A 13.05 s shot got 5.06 s:
  **7.9 seconds of nothing**

Rendering at true length is also **11% cheaper in total** — the film is 150 s and
34 clips at 5.06 s is 172 s of video nobody asked for.

| | frames | wall clock |
|---|---|---|
| true length | 2,446 | ~7.3 h |
| fixed 81 | 2,754 | ~8.2 h |

### Frames: snap up to 4n+1

Wan's temporal architecture works in 4n+1 (81 is 4×20+1). Snapping **up** rather
than down means a clip is never shorter than its slot — a frame or two over is
trimmed by the timeline, a gap cannot be filled.

---

## What it costs

Nothing but getting the number from the right place. A shot's length is not a
setting; it comes from the scene plan, which comes from the song.

Measured render cost, Wan 2.2 i2v at 832×352 on the WSL install:

| frames | clip | wall clock |
|---|---|---|
| 41 | 2.56 s | 5 min |
| 81 | 5.06 s | ~14.5 min |
| 209 | 13.06 s | 42–48 min |

Cost is close to linear in frames, so a per-shot timeout must scale with the
frame count.

---

## Traps

**A fixed timeout marks finished renders as failed.** A 45-minute wait against a
209-frame clip that takes 48 marked two completed renders FAILED; one was
recovered by hand, the other sat on the server untouched. Scale the wait with
the work.

**Two tools writing the session will silently revert each other.** Beat-snapped
timings were written, then reverted by a later tool holding a stale copy, and
the timeline still *looked* complete. Run `audit_timing.py` after anything
touches the session, not only after a retime.

**`SaveVideo` reports its output under `images`, not `videos`**, with
`animated: true` alongside. A collector looking only at `videos`/`gifs` reports a
successful render as missing.

---

## Open questions

- **Does Wan hold together at 209 frames?** It is trained around 81. sc01 and
  sc02 rendered at 209 without failing, but nobody has judged them for drift or
  looping against an 81-frame equivalent.
- **Should section boundaries be nudged onto beats after all?** Four cuts sit up
  to 0.37 s off. Keeping them preserves lyric sync; moving them would make every
  cut land. Untested which reads better.
