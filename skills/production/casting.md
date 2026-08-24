# Casting — find the character *(loop)*

Step 2 of `vrgdg-character-film`. Also usable on its own: "cast a clockwork
heroine for me" with no film in progress. A cast record outlives the film it
was made for.

**Casting is not choosing a model. It is fixing an identity.** The output is
the thing every later shot is generated against and the thing the dailies check
measures drift from. A model that makes one beautiful portrait and a different
face every seed is useless for a film, however good that one portrait is.

---

## triggers

*"let's cast her"*, *"who is she"*, *"cast the character"*, *"find the look"*.
Dashboard action: `casting.start`.

## needs

| Artifact | Required | Why |
|---|---|---|
| `brief` | no | supplies the character description when there is one |

Approved first: nothing. Ask for a description if there is no brief.

## produces

| | |
|---|---|
| `cast_record` | model, seed, LoRAs, settings, a reference **per shot family**, and the measured axes |
| contact sheets | one per round, under `casting/round_N/` |
| checkpoint | `checkpoint_casting.json`, **gated** |
| `decision_log` | `category: "casting"`, subject `"Character: <name>"` |

---

## does

### 1. Cost the round before running it

```
render_clock  -> how long this matrix takes, and whether it fits the evening
```

A `full` preset is ~117 renders. Say the number and the estimate before
starting, and say when a route's timing is unknown rather than inventing one.

**One GPU job at a time.** A casting round and a Builder render cannot share
the machine — and worse, timings measured while something else is rendering are
corrupted, which quietly poisons the render clock's learning. Check
`queue_depth()` first.

### 2. Round one: models only, one shared seed

```
screen_test  preset=quick
```

`quick` is the only preset allowed to run a single seed, because only the model
is varying. It prints its own caveat: **one seed cannot measure identity
stability.** Do not present round-one scores as if it could.

Candidates come from `lib/model_registry` — identified by safetensors header,
never by filename. Two of the installed Z-Image models carry nothing in their
names that would identify them, and one file that looks like an SDXL checkpoint
is a Flux.1 bundle.

### 3. Show the sheet. Ask. Stop.

Present the contact sheet and the measured axes. Then **end the turn.**

### 4. Their reaction becomes round two

See the vocabulary below. Round two is normally seeds × prompts on whatever
they favoured — this is the round that first measures whether an identity
*holds*, which round one could not.

### 5. Round three and beyond: LoRAs, conditions

Until they say "that's her".

### 6. Lock it

Render a reference **per shot family** — close, medium, wide. A reference is
worth about 4× a description on a matched shot and collapses when the framing
changes: close-up identity went 0.213 → 0.932 with a reference, while the same
reference on a wide shot gave 0.493. One image is not enough, and the export
needs all three.

Write the `cast_record` with `chosen_by: "human"`. An agent-chosen record is a
draft, not a cast.

---

## the loop

State in `lib/loop_session.LoopSession(project_dir, "casting")`. Store the
reaction verbatim *and* what you made of it — the pair is what lets a later
reader see a misreading.

| They say | You change |
|---|---|
| *more like #3* | that candidate's model and seed seed the next round |
| *warmer* / *cooler* | `lighting_key`, `color_temperature` |
| *keep the collar* | pin the phrase into every prompt variant |
| *different face* | seed sweep, same description |
| *try the LoRAs* | the registry's LoRA list for that family |
| *softer* / *sharper* | sampler steps and cfg, within the family's recipe |
| *that's her* | render the three references, lock the record |

Outside the vocabulary: ask in plain words. If a phrase recurs, add it here.

---

## presents

```
Casting: clockwork heroine                                    round 2 of ?

  #1  darkBeast30          face 0.92  look 0.96  prompt 0.41   41s   <- holds
  #2  flux-2-klein         face 0.71  look 0.94  prompt 0.39    5s
  #3  gonzalomoZpop_v40    face 0.42  look 0.91  prompt 0.44   10s   <- drifts

  contact sheet: casting/round_2/sheet.png
  face = same person across 3 seeds (ArcFace). #3 is three different women.

  More like one of these, something changed, or is that her?
```

Never present the ranking as a recommendation to accept. It narrows; they pick.

## send-back

A rejection re-runs a round. It **keeps** every previous round and every
reaction — a rejected candidate is still evidence about what they want. If the
brief itself was wrong, update it and start a fresh loop rather than continuing
one built on a description nobody meant.

---

## traps

**A fixed seed is reproducibility, not consistency.** Same model + prompt +
seed reproduces byte-identically, which is why sweeps pin 7777. But hold the
seed and change the prompt and the face drifts *more* (0.47) than holding the
prompt and changing the seed (0.66). **The description carries the identity,
not the noise.** This is why every scene must re-state the character.

**A checkpoint that looks broken may be mis-driven.** Distilled checkpoints
(DMD, LCM, Turbo, Lightning in the name) want CFG ~1 and ~10 steps. Run one at
CFG 4.5 for 35 steps and it returns posterised garbage that reads as a corrupt
model. Two installed checkpoints were written off that way for a whole session;
driven correctly they became the fastest good models on the machine.

**A recipe only transplants into a graph of the same shape.** A checkpoint's
embedded settings apply to the bundled SDXL workflow — one loader, one sampler,
which is what they were authored in. Forcing them into VRGDG's two-pass zimage
schedule produced speckled artefacts. `use_embedded_recipe` takes
`auto`/`always`/`never`; `auto` is right.

**ArcFace measures faces and nothing else.** A render can hold the face
perfectly and lose the pink hair and the brass collar. `look_consistency` is
the guard for that, and its *sensitivity* has never been tested against a
population that keeps the face and drops the costume.

**Never trust a filename.** Use the model registry, which reads the header.
