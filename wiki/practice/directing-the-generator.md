---
title: Directing the generator — what actually decides a frame
status: measured
updated: 2026-08-31
sources: [../../projects/the-man-watches/scene_look/place-her/round.json, ../../scripts/retime_plan.py, ../../scripts/hero_stills.py]
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
