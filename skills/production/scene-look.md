# Scene look — find each scene's look *(loop)*

Step 5 of `vrgdg-character-film`. Also usable on its own: "show me some looks
for this scene".

**The same instrument as casting, pointed at a different question.** Casting
varies model, seed, prompt and LoRA to find a *person*. Scene look varies
direction, lighting, composition and framing to find a *place and a frame*,
with that person already in it. Both render, both show contact sheets, both end
when the human picks.

The gap this fills: casting says who she is, the scene plan says what happens,
and until this step nothing decided what a scene *looks like* before it was
locked and rendered as video.

**Where it is not the answer:** when a scene is right but the *rendering* is
poor — mushy, artefacts, wrong detail — that is the Lab's job, not another
prompt. Scene look explores what the image shows; the Lab explores how the
graph renders it.

---

## triggers

*"what does scene 2 look like"*, *"show me other looks"*, *"find the look"*.
Dashboard action: `scene_look.start` (per scene).

## needs

| Artifact | Required | Why |
|---|---|---|
| `scene_plan` | **yes**, approved | what happens in the scene |
| `cast_record` | **yes**, approved | who is in it, and the reference for this shot family |
| `beat_map` | no | the scene's duration, if you want the still to suit its length |

## produces

| | |
|---|---|
| a hero still per scene | in `assets/images/`, in the `asset_manifest` — the frame the video starts from |
| a look record per scene | the chosen direction, its prompt, and the continuity score |
| checkpoint | `checkpoint_scene_look.json`, **gated** |
| `decision_log` | `category: "scene_look"`, subject `"Scene <id> look"` |

---

## does

### 1. Propose directions, not variations

For each scene, write **three to five genuinely different readings** of the
same scene — dawn through the window / night with brass lamps / rain on the
glass. Different *ideas*, not the same idea at four temperatures. Four
near-identical frames waste a round and teach nothing.

### 2. Render them with the cast in place

Every direction uses the cast record's model, seed and settings, and the
reference for **this scene's shot family** — close, medium or wide, read from
`shot_language.shot_size`. Using a close-up reference on a wide shot is worse
than using none (0.493 with, against 0.213 for a bare description on the
matched shot): the reference stops helping when the framing changes.

**Re-state the character in every prompt.** Never "the same heroine" — no image
model can resolve that. It has already produced a different woman in
production: a scene whose description said "The same clockwork heroine"
rendered someone else, and restating the description fixed it (face 0.34 →
0.55, look 0.33 → 0.68).

### 3. Measure continuity, then show the sheet

Score each render against the cast record — is this still her? Present the
sheet with the scores. Then **end the turn.**

### 4. Their pick becomes the hero still

Then either refine within the chosen direction, or lock it.

---

## the loop

State in `lib/loop_session.LoopSession(project_dir, "scene_look")`, one loop
per scene (`subject` = the scene id).

| They say | You change |
|---|---|
| *the lamp one* | that direction becomes the base; vary within it |
| *more directions* | three new readings, none like the ones shown |
| *darker* / *wider* / *closer* | lighting key, shot size — and re-pick the matching reference |
| *she doesn't look like herself* | strengthen the character restatement; check the shot family's reference is the right one |
| *that's the frame* | lock the still, write the look record |
| *the render is mushy* | **not this loop** — hand the scene to the Lab |

---

## presents

```
Scene sc2 — "close on her face as the gears catch the light"     round 1

  A  dawn through the window     identity 0.88   the warm one
  B  night, brass lamps          identity 0.91   <- strongest continuity
  C  rain on the glass           identity 0.72   the reference is fighting the wet light

  contact sheet: scene_look/sc2/round_1/sheet.png
  reference used: close_up (matches this scene's shot size)

  Pick a direction, ask for more, or change something.
```

## send-back

Rejecting a hero still re-runs this loop **for that scene only** — the other
scenes keep their stills and their approvals. That per-scene granularity is the
point: a film should not lose nine good frames because the tenth was wrong.

A dailies send-back (step 9) lands here when the *look* was wrong, and at
export when the motion was wrong.

---

## traps

**One reference per shot family, and use the right one.** DECISIONS #30.

**A direction is not a temperature.** If two proposals differ only in warmth,
you have proposed one direction twice.

**The still is the first frame of the video.** A beautiful frame that cannot be
moved from is a worse pick than a good frame with somewhere to go. Read the
scene's `movement` before choosing, and prefer a frame whose composition leaves
room for it.
