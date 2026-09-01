---
title: Video identity — what the render eats, and where to put it back
status: measured
updated: 2026-09-01
sources: [../../projects/the-man-watches/artifacts/identity_check.json, ../../projects/the-man-watches/artifacts/shoot_log.jsonl, ../../scripts/swap_clip_faces.py]
---

# Video identity — what the render eats, and where to put it back

The stub asked "what drifts across a clip and what stops it". The answer turned
out to be blunter than drift: **image-to-video does not drift the face, it
redraws it**, and the wider the shot the less of her survives. A swap performed
before generation is overwritten by generation.

Related: [face swap](face-swap.md) · [measuring identity](measuring-identity.md) · [choosing a mechanism](choosing-a-mechanism.md) · [DECISIONS #48](../../DECISIONS.md)

---

## What we know

### The stills all passed. The footage did not.

`The Man Watches` established identity on its 34 hero stills — ReActor swap,
ArcFace mean 0.057 → 0.587, every still above the 0.45 floor — and then rendered
video from them without measuring again. Same reference, same metric, on the
clips:

| scene | shot size | still | clip | |
|---|---|---|---|---|
| sc31 | close_up | 0.84 | **0.76** | holds |
| sc16 | medium_close | 0.79 | **0.54** | holds |
| sc09 | medium_close | 0.65 | **0.38** | borderline |
| sc18 | medium | 0.79 | **0.25** | lost |
| sc11 | wide | 0.76 | **0.20** | lost |
| sc05 | medium_wide | 0.69 | **0.11** | lost |
| sc08 | medium_close | 0.48 | **0.09** | lost |

The ordering is shot size, not still quality. sc11's still scored 0.76 and its
clip 0.20; sc31's still scored 0.84 and its clip 0.76. **The render keeps roughly
what it has pixels for.** A face occupying a few hundred pixels is re-imagined
from the prompt, and the prompt fixes a look, never a face
([DECISIONS #47](../../DECISIONS.md)).

This was found because Raul watched the film and said "she is not she". It was
true of more scenes than he named — the measurement had simply never been taken
on the artifact anyone actually looks at.

### The fix is to swap the clip, not the still

Re-applying identity after generation, over the clip's frames
(`scripts/swap_clip_faces.py`, WORKFLOW step 7b):

| scene | before | after | |
|---|---|---|---|
| sc05 | 0.15 | **0.67** | +0.52 |
| sc08 | 0.14 | **0.59** | +0.44 |
| sc09 | 0.35 | **0.66** | +0.31 |

At full frame the operation is invisible: grade, hair, scarf, fur and background
are untouched, because only the face region is replaced. Cost is ~135–200 s per
clip on the Windows install, which can run **beside** a Wan shoot in WSL — the
two do not compete for weights.

Swapping the still is still worth doing. It is what makes the render *start* from
the right face, and it is cheap. It is just not where identity is verified.

### Try it even when you are sure it cannot work

sc08 is a pure profile, head tilted fully back, showing the underside of a jaw.
It was predicted unfixable — no face to swap onto — and it gained **+0.44**.
ReActor's detector found the profile. The prediction cost nothing to be wrong
about only because the stage measures.

When the stage genuinely finds nothing it says `no face in frame`, and on this
film that was true of exactly the scenes with no person in them — the two dust
whiteouts, the fire, the empty-playa bookends. There, re-directing the shot is
the only answer, and usually the shot is fine as it is.

---

### What the shot has to give the swap: toward camera, upright, unoccluded

The swap is not the variable. **The framing is.** Every scene on this film that
resisted identity did so because the shot gave inswapper nothing to work with,
and every one was fixed by re-directing the shot rather than by changing a
setting:

| scene | was | why it could not work | after re-direct |
|---|---|---|---|
| sc06 | **−0.02** | a silhouette at the edge of a pool of light — no lit face | **0.85** |
| sc27 | **0.04** | already a close-up, but its text carried a "dense crowd of several hundred people" plate that outweighed her face | **0.84** |
| sc08 | **0.09** | head thrown fully back over a ground-level camera: the underside of a jaw | **0.80** |

Three failure modes, and sc15 produced all three in sequence, each one revealed
only after the previous was fixed:

1. **Not toward camera.** Flat on her back, camera underneath looking past her
   at the sky. **0.004.**
2. **Not upright.** Camera moved overhead — face now large at 2.54% of
   frame — but her head was at the *bottom* of frame, so the face was inverted.
   **0.04.** Detection and inswapper are both trained on upright faces;
   orientation beats size.
3. **Not unoccluded.** Camera moved beyond her head, face upright at 3.35%. She
   was wearing the goggles **down over her eyes**. **−0.056.** Recognition takes
   most of its signal from the eye region, so occluded eyes are unrecognisable
   at any size — and lying on her back looking up is exactly the pose that
   invites a model to lower goggles.

> A face has to be **turned toward camera, upright in frame, and unoccluded.**
> Any one missing and the size does not matter.

The costume carries its own trap here: a character defined with "ornate goggles
worn up on her head" will have them put *down* by any pose where goggles down is
plausible. State the eyes as clear, and name the alternative in the negative.

**Diagnose from the still, not the clip.** All of this is visible in the hero
still for the price of one image, and every one of these was caught there —
twice by stopping a run that was about to spend a render on a shot that could
not carry her.

---

## What it costs

~135–200 s per clip, CPU-and-GPU light, on the idle server. Nothing is
re-rendered — this is post, not generation, so a 50-minute Wan render is never
repeated to fix a face.

The measurement itself is the slow part on CPU (ArcFace over sampled frames,
twice per clip).

---

## Traps

**Verifying a stage's input is not verifying its output.** This is
[DECISIONS #37](../../DECISIONS.md) for the third time, in its least obvious
form: the metric was right, the reference was right, the floor was right, and it
was being applied to the still while the deliverable was the clip. Twice before
the failure was a bad proxy for the right artifact. Here it was a good metric on
the wrong artifact, which reads exactly like success.

**A face-swap stage without a before/after check is a way to make footage
worse.** ReActor replaces the largest face in frame; in a crowd that is often a
bystander, and the swapped clip looks confident either way — sc07's *still* once
scored worse after its swap for exactly this reason. `swap_clip_faces.py`
discards any swap that does not improve the number and keeps the original.
`--faces-index` picks the face when the largest is wrong.

**Do not read a high still score as a solved scene.** The still is one frame of
several hundred, and it is the one frame the swap was applied to.

---

## Open questions

- **Does identity hold *across* a swapped clip, or only at the sampled frames?**
  Scoring samples 6 frames. A face that is right at frame 5 and wrong at frame 90
  would average acceptably.
- **Is there a shot size below which swapping stops being worth it?** sc05 at
  medium-wide recovered to 0.67. Nothing has been measured on a true wide where
  she is a few dozen pixels tall.
- **Does the swap survive post?** Grain, LUT and any upscale in step 10 run
  after this, and none of them have been measured against identity.
