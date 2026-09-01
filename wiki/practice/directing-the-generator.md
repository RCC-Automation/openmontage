---
title: Directing the generator — what actually decides a frame
status: measured
updated: 2026-08-31
sources: [../../projects/the-man-watches/scene_look/place-her/round.json, ../../scripts/retime_plan.py, ../../scripts/hero_stills.py, ../../projects/the-man-watches/artifacts/shoot_log.jsonl]
---

# Directing the generator — what actually decides a frame

Four separate failures on `The Man Watches` turned out to be the same mechanism.
Each cost renders, and three of them were misdiagnosed as capability limits
before the real cause was found. This is that cause, and the two levers that
answer it.

Related: [putting her small in a crowd](../character/placing-her.md) · [prompting](prompting.md) · [what we measured](../character/what-we-measured.md)

---

## What we know

### The mechanism: whatever has the most words wins

A generator renders **the thing the prompt is most about**, and "most about" is
measured in words, not intent. Everything below is one instance of it:

| what was asked for | what came back | the ratio |
|---|---|---|
| her, small in a crowd | a foreground portrait at 30% of frame height | 8 clauses about her, ~50 words of setting |
| a cinematic frame | flat, centred, evenly lit | every prompt ended `"documentary photograph, locked off, no tilt"` |
| a crew laying out scaffold | empty playa with a woman in it | plate paragraph (~90 words) vs action sentence (~12) |
| the Temple, a welding tent, a swing over fire | the same crowd-walking wide, twenty times | same as above |

**The fix is always the same shape: make the thing you want the loudest thing in
the prompt.** For the last two rows that meant literally re-ordering — the action
moved to the front and the location was compressed to its ground clause. Nine of
ten failing shots corrected on one re-render.

### Lever one: the negative, and it must be aimed

Naming the failure in the negative works, costs nothing, and beats machinery.
Measured repeatedly — see [DECISIONS #42](../../DECISIONS.md) and
[placing her](../character/placing-her.md), where a live negative solved in one
render what inpainting and a crop-upscale detailer pass had failed to solve in
nine.

**But one negative cannot serve a whole film.** `portrait, close-up, person
facing camera` is exactly right for a wide and exactly wrong for a close-up. A
single negative across 34 shots fought all eight close shots — it produced a
crowd wide where a face was asked for. The negative now depends on shot size:

```python
WIDE_ONLY  = "portrait, close-up, foreground subject filling the frame, ..."
CLOSE_ONLY = "full body, wide shot, distant figure, tiny in frame, ..."
```

It only works at all on a model whose negative branch is live — **6 of 19 here**.
The rest discard it silently.

### Lever two: state it, do not un-state it

`centred and static composition` sat in the negative while every frame came back
centred. The negative alone does not win: **centre is where a subject goes when
the positive does not say otherwise.** Composition had to be designed per shot —
placement on thirds, camera height, foreground occlusion — before it moved.

The same trap in its purest form: the bridge whiteout was given **no ground
clause at all**, on the theory that any ground contradicts a whiteout. With
nothing to anchor them the model invented an abstract blue gradient and *a red
boat on an ocean*. Stating the whiteout as a thing that is present — "a wall of
blowing white dust filling the frame, a few feet of cracked ground underfoot" —
produced it immediately.

> **Absence is not a description.** Remove a term and something fills the space;
> you do not get to choose what.

### Motion: a contradiction resolves as oscillation

Everything above is about stills. Video adds a failure the still pass cannot
show, and it has a different mechanism: **an instruction the model cannot satisfy
is not refused, it is averaged.**

`sc02` was written as *"a single truck enters as a dot on the horizon line and
**never arrives**"*, with `movement: dolly_in` putting *"a slow push in, the
frame closing"* into the prompt. Two forces pointing opposite ways: the truck is
told to come on and told not to get here, and the camera pushes in while the
subject approaches. Wan 2.2 i2v at 209 frames resolved it by moving the truck
back and forth — sampled at frames 0 / 52 / 104 / 156 / 208 it grows, shrinks
twice, then grows, and ends barely larger than it started. Thirteen seconds of
screen time in which nothing happens.

Nothing errored. The clip is the right length, the right size, and correctly
graded; only watching it reveals the shot is dead — the same lesson as
[DECISIONS #40](../../DECISIONS.md), one medium along.

The obvious fix was tried first, and it is the interesting part of this entry:
**it did not work.** The shot was rewritten to say one direction and to say it
continuously ("drives straight toward the camera … growing steadily larger for
the whole shot … closing the distance frame after frame"), the camera was locked
off so only the truck moved, and the reversal was named in the negative
(`reversing, driving backwards, receding, shrinking, back and forth,
oscillating, stationary truck, unchanging distance`).

The re-render, 50 minutes later, approached cleanly to **frame ~80** — a better
approach than before, genuinely — and then **the truck performed a U-turn,**
drove away until frame ~144, turned a second time and came back.

### The real ceiling: a motion cue survives about one training window

Wan 2.2 i2v is trained around **81 frames**. Up to that, it obeys the direction.
Past it, the cue is spent and the model generates plausible new motion — and for
a subject with an obvious axis, the plausible next thing is going back the way it
came. Sampled every 20 frames, the second sc02 render reads: grow, grow, grow,
grow (f0–f80) · turn · recede (f100–f140) · turn · approach again (f160–f200).

This is not drift, degradation or looping artifacts, which is what
[Q9](../../QUESTIONS.md) expected to find. Nothing errors, the clip is the right
length and correctly graded, and only watching it reveals the shot is dead
([DECISIONS #40](../../DECISIONS.md), one medium along).

**No prompt fixes this, because it is not a prompting failure.** Both levers at
the top of this page operate on what the model is *asked*; this is a limit on how
long it can keep being asked anything.

### It runs out of direction, not of quality — so most long shots are fine

The ceiling sounds like it caps every clip at 5 seconds. It does not. Measured on
three clips from this film:

| shot | frames | subject | |
|---|---|---|---|
| sc02 | 209 | a truck approaching | **broke** — U-turn at ~90, back again at ~160 |
| sc08 | 133 | her, head back, camera static | **held** — pose, framing, identity stable throughout |
| sc01 | 209 | empty horizon, drifting dust | **held** — no drift, no degradation |

Wan does not get *worse* past 81 frames. It runs out of **direction**, and a
shot whose subject is merely present rather than going somewhere has no
direction to lose. Hair moves, dust drifts, light shifts — none of that has an
axis that can reverse.

So the rule is not "cap everything over 81 frames", which would needlessly soften
two thirds of this film's long shots. It is: **cap a shot whose subject is going
somewhere.** Everything else renders at full length and is judged on arrival.

### What does work for the ones that do break: render one window, stretch it

Keep the frames that obeyed and spend them over the whole slot.

```bash
# the 81 frames that held
ffmpeg -i sc02_raw.mp4 -vf "select='lt(n\,81)',setpts=N/16/TB" -frames:v 81 clean81.mp4
# motion-compensated to fill a 12.89 s slot; overshoot, then trim to exact length
ffmpeg -i clean81.mp4 -vf "setpts=2.72*PTS,minterpolate=fps=16:mi_mode=mci:\
mc_mode=aobmc:me_mode=bidir:vsbmc=1" -frames:v 209 sc02.mp4
```

Motion is one-way for the full 13.06 s because every frame descends from the
stretch that obeyed. `minterpolate` **cannot extrapolate past the last input
frame** — asking for exactly 209 returned 204 and a short clip, which is a gap in
the film. Overshoot the factor and trim.

### Two mechanisms that look right and are not

Both were tried on `The Man Watches` after the stretch, on the reasoning that
slowing motion down is a compromise and real-time motion must be better. Both
cost renders and both were rejected by Raul watching the result.

**Context windows (`WanContextWindowsManual`) — wrong for image-to-video.**
The node slides an 81-frame window across a long generation with overlap, which
is exactly right for text-to-video. For i2v it **re-feeds the start image
conditioning into every window**, so each window generates motion beginning from
the still again. On sc11 the scarf whipped forward, snapped back to its opening
position at frame 52 — precisely the 81−30 stride — and repeated. It is
architectural: `retain_first_frame: false` does not help, because the I2V embed
reaches every window regardless. The upstream discussion is blunt about it —
*"context windows will not work well with I2V models, with no proper way
around it."*

**Chained segments — no restart, but a seam.** Render a segment, take its *last*
frame, start the next from it. The motion genuinely continues, because the model
is looking at where it actually got to. But Wan does not *reproduce* its start
image, it re-renders it, so the first frame of each new segment carries the
model's own re-interpretation. Measured, the seam was the single largest
frame-to-frame jump in every chained clip — 4.45× the median on sc11, 5.08 on
sc15, 4.44 on sc16, 6.67 on sc18, and three seams in sc31. Visible, and rejected
on sight: *"the face is good, but the sequence is broken."*

Smoothing the seam by cross-fading toward the previous frame **scored beautifully
and looked terrible** — the seam ratio fell from 3.6× to 0.72× and the frames
became a double exposure, two sets of goggles and ghost limbs. A blend lowers
frame-to-frame difference *by* ghosting. That number cannot tell a fix from a
smear; only looking can.

> One continuous generation has nothing to restart and nothing to seam. Every
> mechanism that adds a boundary adds an artefact at it.

### Why the stretch keeps winning

It is also **3× cheaper**: 81 frames is ~14.5 min against ~50 for 209. The
slow-down is not a compromise here — a truck taking 13 s to cover what it covered
in 5 reads as distance on a long lens, which is the shot.

**Where the negative still earns its place:** per-shot motion negatives live in
`scene_plan.metadata.negative_prompt_overrides`, keyed by scene id, so they
travel with the film rather than the render script — `stationary truck` is right
for sc02 and wrong for any locked-off shot whose subject should hold still. They
made the first 80 frames better. They could not make the clip longer.

> A dead shot costs the same GPU hours as a good one. sc02 was 209 frames,
> ~50 minutes, and was spent twice before the ceiling was the diagnosis.

### Uniformity is not a style

All 34 shots were `extreme_wide` + `static`, and every prompt carried the
documentary treatment. Neither was ever chosen — both were inherited from a
concept where the camera was a forty-foot effigy that could not move, and both
outlived it by weeks. A default nobody decided looks exactly like what it is.

After a designed pass: 6 shot sizes, 9 movement types, 5 focal lengths, 10
lighting keys, and centre used 4 times out of 34 — each time as a statement (two
whiteouts where symmetry is the emptiness, the turn where ten thousand people
face camera, and the bookend that must match).

---

## What it costs

Nothing but attention. Every fix here is a prompt change. The expensive
alternatives — ControlNet, inpainting, a crop-and-upscale detailer — were reached
for first on two separate occasions and lost to a named term in the negative both
times.

Render cost for reference: 109 s per 1536×640 still on Z-Image Base, so a 34-shot
pass is about an hour and a wrong global assumption costs that hour twice.

---

## Traps

**A misdiagnosis looks exactly like a capability limit.** "Inpainting cannot put
a small figure in a crowd" was wrong — the mask was empty because
`Image.paste(tile, box, tile)` with an all-zero alpha pastes nothing. "The model
cannot render a scarf at 60 px" was wrong — upscaling the patch first proved
pixels were not the constraint. Verify the mechanism before concluding the tool
cannot do the thing.

**Check what your measurement is actually measuring.** A red-blob proxy for "how
big is she" reported a bystander's t-shirt, a cyclist's tank top and an orange
sky as her, and returned *"found, 100% of frame height"* for the one frame where
she was least visible. A saturating proxy reads as the strongest possible
positive. Judgement about a rendered image is made by looking at it
([DECISIONS #40](../../DECISIONS.md)).

**Plate prompts carry their own light and their own camera.** A location plate
rendered under an old concept keeps saying `documentary photograph`, `elevated
forty feet` and `at first light` into every scene built on it, long after those
rules are dead. Strip them where the setting is composed, not one by one.

---

## Open questions

- **Does the ratio hold on other models?** Everything here is Z-Image Base and
  FLUX.1 dev. SDXL and Chroma have live negatives and are untested on it.
- **Is there a threshold, or is it continuous?** We know ~90 words of setting
  beats a 12-word action and that reversing the order fixes it. Where it flips is
  not measured.
