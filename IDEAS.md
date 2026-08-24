# IDEAS

Proposals that are **not decided and not scheduled**. Nothing here is committed
to. `DECISIONS.md` holds what was chosen; `PROGRESS.md` holds what exists; this
file holds what we think might be worth building next, and why.

Delete an entry when it is either accepted (move it to DECISIONS.md) or ruled
out (say why, keep the entry).

---

# 1. The Screen Test — a systematic lab for casting looks

*proposed 2026-08-23 · Raul's idea, elaborated · **status: built 2026-08-23**, not yet run live · see PROGRESS.md*

## The problem

There are nine image models and eight image LoRAs installed. Which produces the
best character for a given film is currently answered by generating a few
pictures and squinting. That is slow, not repeatable, and the knowledge
evaporates — next month the same question gets re-answered from scratch.

Worse, "best" is being judged on the wrong axis. A model that makes one gorgeous
portrait but a different face every seed is **useless for filmmaking**. Nobody is
measuring that.

## The idea

Borrow the film term. Actors do a **screen test**: same scene, same lighting,
several candidates, and you compare them side by side before committing to one
for the whole picture.

Run the same character brief across a matrix of models, LoRAs and settings, in
the conditions the film will actually use, and produce a ranked contact sheet
plus a locked decision.

## What the real output is

Not a grid of pictures. A **cast record**:

```
character: "Wren, the clockwork heroine"
model:     zImageTurbo_turbo.safetensors
loras:     [ZIT_Radiant v2.0 @ 0.6, Z-Detail-Slider @ 0.3]
settings:  {first_pass: 1280x720, second_pass: 1920x1080, steps: …, cfg: …}
seed:      24082301
reference: assets/casting/wren/hero.png
identity_stability: 0.94
cast_on:   2026-08-23
```

Casting is not choosing a model. It is **locking an identity** — so every later
shot in the film is generated against the same record, and the continuity check
(see idea 2) measures drift from that reference rather than from nothing.

## The metric nobody thinks of: identity stability

This is the strongest technical idea in the proposal.

Generate the same character 8 times with **different seeds**, same everything
else. Embed the faces. Measure how much they vary. A combination that yields a
stable face across seeds is worth more for a film than a prettier one that
drifts — because you are going to generate that character 40 more times.

`lib/clip_embedder.py` already provides `embed_images()` and `pool_frames()`.
The measurement is a handful of lines on top of machinery that exists.

## Test in the conditions of the film

One portrait proves nothing. A face that holds in close-up and falls apart in a
wide shot is the wrong cast. The screen test should cover a small deliberate
spread:

- 3 shot sizes — close-up, medium, wide
- 2 lighting keys — the film's key look and one contrasting
- 2 angles — front and three-quarter

12 renders per candidate combination. That is the minimum that tells you
anything true.

## What the machine may and may not judge

**Be strict about this boundary.**

The machine *can* measure, reliably:

| | |
|---|---|
| Identity stability | face embedding variance across seeds |
| Prompt adherence | CLIP text↔image similarity |
| Anatomy failures | hands, eyes, limb count — detector pass |
| Technical quality | sharpness, banding, obvious artifacts |
| Cost | seconds per image on this GPU |

The machine *cannot* judge whether a face is right for the part. That is taste,
it is the whole job, and it stays with the human.

**So the design is: the machine narrows, the human picks.** A sweep of 60
candidates is reduced to the 8 that are technically sound and identity-stable,
presented as a contact sheet, and the human chooses. The system never selects
the final look — it only removes the candidates that were never viable.

## Sweep strategy: a funnel, not a grid

Nine models × eight LoRAs × settings is combinatorially hopeless, and each image
costs ~2.5 minutes. Stage it:

1. **Round 1 — models only.** Every model, no LoRAs, 3 seeds, one shot size.
   ~27 images, roughly an hour. Cut to the top 3.
2. **Round 2 — LoRAs on the survivors.** 3 models × relevant LoRAs × 3 seeds.
   Cut to the top 2 combinations.
3. **Round 3 — the real screen test.** 2 candidates × 12 conditions × 3 seeds.
   ~72 images. Human picks from a contact sheet.

Roughly 4–6 GPU-hours total, and it runs unattended overnight. Which is exactly
why the render budget (idea 2) should exist first — a sweep is the one thing on
this machine that genuinely needs a clock.

## What to reuse rather than build

- **VRGDG** already has `VRGDG_LTXPreviewXYZPlot`, `VRGDG_VideoFolderGridPlot`,
  `VRGDG_ImageCompare` and a `/vrgdg/krea2_studio/create_xyz` route. Use them for
  the contact sheets instead of writing a plotter.
- **`vrgdg_build`** already generates from any image model by payload, so a sweep
  is a loop over payloads — no new graph work.
- **`lib/scoring.py`** already does weighted multi-dimensional scoring with an
  `explain()` method. The ranking is a new scorer, not a new framework.
- **`lib/clip_embedder.py`** provides the embeddings.

## Downstream value

- The cast record becomes the reference for the continuity ledger (idea 2.4).
- Once a character is cast, L6 can train a LoRA **on the winner** — turning a
  chosen look into a reliable one.
- The results are a durable asset. "On this machine, for photoreal faces, Z-Image
  Turbo + Radiant at 0.6 is the cast" is knowledge worth more than any single
  image, and it currently has nowhere to live.

## Open questions

- Does a screen test belong to a film (in `projects/<id>/casting/`) or to the
  machine (a shared library reused across films)? Probably both: run per film,
  promote findings to a shared look book.
- Should the same treatment apply to **video** models? Same principle, ~25× the
  cost. Probably later, and only for the two or three finalists.
- Locations and props deserve the same treatment as characters. Same machinery,
  different brief.

---

# 2. The Dailies Loop — judge the footage, not just make it

*proposed 2026-08-23 · status: idea*

## The problem

Both OpenMontage and VRGDG assume generation succeeds and the first result is
the result. Filmmaking is not like that: you shoot, you watch, you reshoot. That
loop is where the quality comes from, and nothing in the stack models it.

On a real set, dailies are the evening screening of the day's footage where you
decide what to keep and what to shoot again. Four pieces would give us that.

## 2.1 A render budget, in GPU-minutes — **built**

`tools/cost_tracker.py` is 523 lines of dollars. On this machine everything is
$0 and the real currency is **time**: a Z-Image still is ~2.5 minutes, a
SCAIL-2 clip took **66**.

Nothing knows this, so nothing can say the useful thing: *"you have 4 hours, this
plan needs 11, here is what to cut."*

Same shape as the existing estimate → reserve → reconcile flow, different unit.
`BaseTool.estimate_runtime()` already exists as the hook.

**Smallest of the four, needs no models, changes decisions immediately.**

## 2.2 A shot ledger — takes, not assets

`asset_manifest` records one asset per scene, with no take, version or supersedes
field (verified against the schema). Everything that lost is discarded.

But the craft is in the other four attempts and why the fifth won. Record every
take with its seed, graph hash, verdict and reason. That is the creative history
of the film, and it also makes "the Tuesday version was better" a recoverable
statement instead of a regret.

VRGDG keeps `video_history` / `image_history` per segment — the raw material is
there, unlabelled.

## 2.3 A dailies critic

`tools/analysis/visual_qa.py` (346 lines) and `composition_validator.py` (275)
exist and are wired to nothing. VRGDG has Florence-2 and VLM nodes.

Connect them: as each take finishes, a vision model compares it against the
scene's **stated intent** from the scene plan and flags the obvious failures —
broken motion, artifacts, wrong hands, does not show what the scene was for.

Same boundary as the screen test: it flags, it does not decide. On a 20-shot film
this is the difference between an evening of review and half an hour, because you
only spend your own eyes on the takes worth looking at.

## 2.4 A continuity ledger

The hardest problem in AI film, and nothing is watching it. The character drifts
between shot 2 and shot 7, and you notice at the end when it is expensive.

Embed each new shot, compare against the cast record's reference (idea 1), flag
drift **while shooting**. Again: `clip_embedder` exists.

## What it would feel like

Each evening: *here is what rendered, these four look wrong and why, your
character drifted in shot 7, you used 3 of your 4 hours, and here is what is
left to shoot.*

The human still has the taste and still decides. They stop having to notice
everything.

---

# 3. The Production Room — a visible, gated, interactive workflow

*requested 2026-08-24 by Raul, during the first live render · status: **direction
given, not designed***

## What was said

After the end-to-end test: *"even though we have done progress I am still not
satisfied. I need a real workflow where I can identify the steps that are
executed with OpenMontage, and I can influence them, with reviews and the
possibility for modifications. And in the future I need a more interactive
workflow with the Agent: the Agent does the required work — defining the
perfect character, trying multiple seeds, multiple prompts, multiple LoRAs,
multiple models."*

## What it means

Two requirements, both about **who is in control and can see it**:

1. **Visible, gated steps.** Today's round trip was driven by hand: a
   scene_plan written directly, tools called from scripts, no checkpoints, no
   decision log, no board. That was deliberate for a plumbing test and it is
   exactly what Rule Zero forbids for production. The user wants the real
   thing: a pipeline definition for VRGDG films whose stages checkpoint, gate on
   human approval, log decisions, and show on the Backlot board — so every step
   can be reviewed, sent back, or edited before the next one starts.

2. **An interactive casting loop.** Not "run the screen test and hand me a
   ranking" but a conversation: the agent proposes a character brief, renders a
   round (models × seeds × prompts × LoRAs), shows a contact sheet, the human
   reacts ("more like #3, warmer, keep the collar"), the agent runs the next
   round from that reaction, until a cast record is locked. Idea 1 built the
   instrument; this is the session that plays it.

## Shape to propose (not yet agreed)

A `pipeline_defs/vrgdg-character-film.yaml` with stages roughly:
`brief → casting (interactive, gated) → scene_plan (gated) → export → render
(human, in the Builder) → import → dailies (gated) → post`. Each stage a
director skill; casting and dailies are the two loops from ideas 1 and 2, made
conversational. The export/import stages are the bridge as it exists.

## Answered 2026-08-24, and extended

- **Standalone skills, integrable into a pipeline** — decided. Raul wants a
  *set* of skills, one per production step, usable on their own; a pipeline
  strings them together. If a step already exists, a **workflow document**
  must explain how to use it.
- **A dashboard for interaction**, modelled on VRGDG's Video Wizard
  (`assets/references/AIVideoBuilder_Wizard.png`): a stepper rail, one panel
  per step, current-state chips, quick actions, Back/Next. "An easy way to
  trigger whatever step of the workflow and check results." Candidate hosts
  named by Raul: a ComfyUI node, a standalone app. Backlot already exists as a
  read-only board with a server and an SSE watcher; the natural move is to
  grow it from observer into cockpit.
- **A ComfyUI Lab**: test, generate and modify ComfyUI workflows without
  hand-editing in ComfyUI — where the agent's expertise tunes nodes, samplers
  and parameters, and combines nodes, to reach the best result. The screen
  test generalized from "which model" to "which graph": same funnel, same
  calibrated axes, results recorded as recipes (DECISIONS #24/#25).

## Open questions

- How does a dashboard button *trigger* a step when the agent is the
  orchestrator and Python may not orchestrate (AGENT_GUIDE)? A request queue
  the agent consumes keeps the constitution; the Agent SDK is the eventual
  headless path.
- How does a send-back at `dailies` re-enter the Builder — re-export one scene,
  or the whole timeline?

---

## How the two ideas fit

They are the same production sequence a real film follows:

```
Screen Test  ──►  cast record  ──►  shoot  ──►  Dailies  ──►  retake
 (pre-production)                              (production)
```

Casting happens once, before the shoot, and produces the reference. The dailies
loop runs during the shoot and measures against it. Building them in that order
is also the cheapest order — the screen test needs only images, the critic wants
LTX finished.

Neither is a competing framework. Every piece extends something OpenMontage
already has: `cost_tracker`, `asset_manifest`, the reviewer skill,
`variation_checker`, `scoring`, `clip_embedder`. That is deliberate — the repo
already has one constitution and does not need a second.

## Suggested order

1. ~~**Render budget** (2.1)~~ — built.
2. ~~**Screen test** (1)~~ — built; still to be run live once a sweep is affordable.
3. **Shot ledger** (2.2) — cheap once takes are being generated in volume.
4. **Dailies critic** (2.3) — after LTX lands.
5. **Continuity ledger** (2.4) — needs a cast record to compare against.
