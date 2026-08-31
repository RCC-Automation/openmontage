---
title: Putting a named character small in a crowd
status: measured
updated: 2026-08-30
sources: [../../projects/the-man-watches/scene_look/place-her/round.json, ../../workflows/image-bench/graphs.py]
---

# Putting a named character small in a crowd

Name a person in a prompt and the model renders them as **the subject** — large,
centred, facing the lens — no matter what the prompt says about their size. This
is the problem of any film where the character is one figure among hundreds, and
in `The Man Watches` it gates over half the shots.

The fix is a **live negative prompt**, and the constraint is that not every model
has one.

Related: [what we measured](what-we-measured.md) · [prompting](../practice/prompting.md) · [seeds](../practice/seeds.md)

---

## What we know

### The failure, stated precisely

Whatever is named is rendered as the subject, and **the subject expands to fill
whatever space it is given**. Ten renders on this machine, 2026-08-30:

| given | what came out |
|---|---|
| a full 1024 frame | a foreground portrait, ~30% of frame height |
| an 80 × 240 inpaint mask | an 80 × 240 person-shaped black silhouette |
| the same mask, scarf-led prompt | an 80 × 240 sheet of red cloth, no wearer |

The third row is the one that closes it. The patch was upscaled to 1024 first,
so the sampler had ~240 px of body to work in — **"too few pixels" is not the
cause.** Lead with the person and you get a person with no scarf; lead with the
scarf and you get scarf with no person. The named thing becomes the subject and
consumes the region.

### What does not fix it

All on FLUX.1 dev, one 1024² render each, seed held at 4402:

| strategy | result |
|---|---|
| state "far from camera and small in frame" | foreground portrait — the control |
| make the crowd the grammatical subject, her a subordinate clause | portrait gone **and she is gone** |
| state a fraction: "no taller than one twentieth of the frame height" | portrait gone **and she is gone** |
| img2img over a plate that already has her, denoise 0.35 / 0.55 | refines; cannot remove a plate's subject |
| inpaint at her real scale | correct size, no scarf |
| crop → upscale → inpaint → downscale | silhouette **or** cloth, never both |

The two middle rows are the important pair: reducing her emphasis far enough to
kill the portrait also removes her from the frame. **Prompt phrasing cannot make
a named thing subordinate** — there is no setting between "subject" and "absent".

### What fixes it

**Z-Image BASE with a live negative prompt.** First attempt, no tuning:

```
positive  … The crowd streams left to right across the middle of frame …
          One of the distant walkers in the crowd wears a deep red scarf
negative  portrait, close-up, foreground subject, large figure,
          person facing camera, person filling the frame,
          shallow depth of field, bokeh
```

**57 px tall, 5.6% of frame height**, and she reads at a glance because she is
the only saturated red in a dust-gold frame. She also came out separated from
the crowd, which is the shot's intent.

**The criterion is not that number.** Corrected 2026-08-30 at Raul's direction:
what matters is that she reads **the same size as the people around her at her
depth in frame**, not that she hits a share of frame height. The original plate
failed because she was 60% while nearby figures were 15% — a 4× mismatch. A
figure at 12% standing in a foreground lane is correct perspective and fine. An
absolute target quietly forbids every composition that brings her forward, which
is most of them.

This is [DECISIONS #42](../../DECISIONS.md) holding a second time: *change the
prompt before adding machinery.* ControlNet was the wrong answer to the
bystander problem and inpainting was the wrong answer to this one. Both times
the negative prompt cost nothing and worked first try.

### The constraint that decides which model you may use

A negative prompt only exists where the negative branch is live. On this machine
it is **absent, not weak**, in two situations:

- **at `cfg` exactly 1.0**, where ComfyUI never evaluates the branch — 10 of 19
  installed models (see [prompting](../practice/prompting.md));
- **where the graph zeroes it**, which `workflows/image-bench/graphs.py` does
  for FLUX.1 dev, Z-Image *Turbo*, and Klein distilled via `ConditioningZeroOut`.

Z-Image **Base** takes a real one (`real_negative=True`), as do SDXL and Chroma.

> **Any plate carrying a named character must be made on a model whose negative
> is live.** That is a casting-level constraint on the model, not a prompt tweak.

### It costs nothing in consistency here

`The Man Watches` shot L1, L2, L4 and the night round on the Z-Image family
already. Moving the people-bearing plates off FLUX.1 dev onto Z-Image Base makes
the film **more** consistent, not less.

---

## What it costs

One render. 292.8 s in the measurement above, but that was a **cold load** of
Z-Image Base over the WSL 9p filesystem — warm image renders on that server run
about 22 s ([two platforms](../comfyui/two-platforms.md)).

---

## Traps

**Do not diagnose this from a size measurement alone.** The proxy used here —
tallest saturated-red blob as a share of frame height — reported a bystander's
red t-shirt and a cyclist's tank top as "her" in four of ten runs. It is a proxy
for size, not a person detector. Every verdict above came from looking at the
frame ([DECISIONS #40](../../DECISIONS.md)).

**`Image.paste(tile, box, tile)` with an all-zero alpha pastes nothing.** The
mask argument decides *where* to paste, so a fully transparent tile used as its
own mask is a no-op. Two inpaint renders came back with the plate untouched,
which looks exactly like a model limitation and is not one. Verify a mask has
transparent pixels before spending GPU on it.

**An inpaint at ~60 px renders a body and no detail.** That is not a reason to
reach for a detailer pass — see above, upscaling does not fix it — it is a
reason to reach for the negative prompt.

---

## Open questions

- ~~**Does it hold at night?**~~ **Answered 2026-08-30.** The placement method
  works in all six night lighting states. The *colour* holds in five and fails
  in pure firelight, where the whole frame goes orange — see
  [what we measured](what-we-measured.md). No wide that carries her may be lit
  by fire alone.
- **Does the same negative hold her position?** The strategy controls *scale*.
  Whether she can be put on a chosen side of the frame, which the shot list
  needs for the Attention pushes, is untested.
