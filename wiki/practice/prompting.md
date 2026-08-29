---
title: Prompting — what binds, and what we reached for instead of reading the prompt
status: measured
updated: 2026-08-29
sources: [../comfyui/image-recipes.md, ../character/choosing-a-mechanism.md, ../../DECISIONS.md]
---

This page exists because a whole afternoon went into fixing a problem with
ControlNet that a line in the negative prompt fixed for free. It is narrow on
purpose: only what was measured here, not a general prompting guide.

---

## What we know

### The bystander problem was a prompting failure, not a control failure

A character brief containing *"Rave, outdoors, burning man ... outdoor
festival"* produced people nobody asked for in **13 of 36 renders** — 8 of 18
close-ups and 5 of 18 full bodies, up to **seven** in one frame. Since identity
is scored on the largest face, some of those scores were measuring a stranger.

Three fixes were measured against it.

| fix | realismIllustrious | babesIllustrious | cost |
|---|---|---|---|
| baseline | 7 people | 4 people | — |
| canny ControlNet | 3 | 1 | 45–46 s |
| pose ControlNet | 1 | 4 | 46–48 s |
| **crowd terms in the negative** | **1** | **1** | **22–25 s** |

The negative prompt won on every model where it applies, cost nothing, and was
**faster than either ControlNet** because it adds no extra pass.

Terms used, appended to the standard negative:

```
crowd, group of people, multiple women, two women, background people,
bystanders, several people, duplicate person
```

### Why ControlNet could not fix it

This is the part worth keeping. The pose run was given a control image and told
`max_detections: 1`, and the pose map it generated **contained exactly one
skeleton** — verified by saving the map itself. The renders still came back with
3 and 4 people.

**ControlNet constrains the structure of the subject. It does not stop the model
painting other people elsewhere in the frame.** The extra figures were never a
structure problem; they were the prompt being obeyed.

The canny run failed for a second, compounding reason: canny encodes *every*
edge in the control image, so a festival photograph hands the model its
background crowd along with its subject.

**Corollary:** always save the intermediate. Without the pose map on disk this
would have read as "pose control does not work here" rather than "pose control
worked and the problem is elsewhere".

### Half the pool cannot use the fix

At `cfg` exactly 1.0 ComfyUI never evaluates the negative branch at all, so the
negative prompt is inert — not weak, absent. **10 of 19 installed models run at
cfg 1.0**: the three DMD SDXL checkpoints, all five Z-Image Turbo merges, Klein
distilled and the FluxDAIO.

Measured control: `darkBeast30` at cfg 1.0 with the same crowd negative stayed
at 2 people, unchanged, while three cfg>1 models went to 1.

For those ten, the options are ControlNet (partial — 7→3 on canny) or a model
that counts. See [image-recipes](../comfyui/image-recipes.md) for which model
runs at which CFG.

### Framing binds; subject count does not

A separate measurement, and the more encouraging one: asked for `close-up
portrait` and `full body shot, head to feet in frame`, **all 18 models obeyed
the framing at both sizes** — face fraction 12.0–56.2% for close-ups and
0.35–5.2% for full bodies, two ranges that do not overlap.

So shot size is reliably promptable on this pool and subject count is not. That
distinction was invisible until face fraction and face count were measured;
`lib/shot_size.py` does both, and the bands above are where its thresholds come
from.

### Prompt dialect appears to matter, unquantified

The character brief is written in comma-separated tag style. On it, the
tag-trained families (Pony, Illustrious) took the top prompt-only identity score
while the prose-trained ones (Z-Image, Klein Base, Chroma) clustered at the
bottom. That is consistent with dialect mattering, but nothing has been run both
ways, so it is an observation and not a result.

---

## Traps

**A negative prompt at cfg 1.0 does nothing, silently.** It is not applied
weakly; the uncond pass is skipped entirely. Writing one there and believing it
helped is the easy mistake.

**Reaching for a model patch before re-reading the prompt.** 4.5 GB of
ControlNet was downloaded to solve this, on a recommendation that turned out to
be wrong about the cause. ControlNet earns its place for pose and composition
control the pool otherwise lacks — it was simply the wrong tool for this.
`DECISIONS.md` carries the reversal.

---

## Open questions

- Does writing the same intent in both dialects change the ranking, or is the
  tag-family advantage really about training data?
- For the ten cfg-1.0 models, is there a prompt-side lever at all, or is
  ControlNet the only one?
