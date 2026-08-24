# PLAN — the production workflow, the cockpit, and the lab

**Written:** 2026-08-24, during the first live LTX render.
**Owner:** Raul. **Status:** proposed, awaiting approval before any build starts.
**Relates to:** `IDEAS.md` #1–#3 (the ideas), `DECISIONS.md` (the constraints),
`PROGRESS.md` (what exists today).

This plan answers one requirement, stated after the end-to-end test:

> I need a real workflow where I can identify the steps that are executed with
> OpenMontage, and I can influence them, with reviews and the possibility for
> modifications. And a more interactive workflow with the Agent: the Agent does
> the required work — defining the perfect character, trying multiple seeds,
> multiple prompts, multiple LoRAs, multiple models.

Plus three things decided since: **standalone skills** that a pipeline strings
together; a **dashboard** modelled on VRGDG's Video Wizard to trigger any step
and check its result; and a **ComfyUI Lab** where the agent tunes graphs,
samplers and parameters without hand-editing in ComfyUI.

---

## 1. The workflow at a glance

A film is made in eight steps. Each step has one owner, produces one thing you
can look at, and stops for your approval before the next one starts.

```
 1. Brief ──► 2. Casting ──► 3. Scene plan ──► 4. Export ──► 5. Render ──► 6. Import ──► 7. Dailies ──► 8. Post
    you+agent    loop           agent            agent         you            agent         loop           agent
                (agent renders,                               (Builder)                    (agent flags,
                 you pick)                                                                  you decide)
```

| # | Step | What happens | Who | You get to see | You can |
|---|---|---|---|---|---|
| 1 | **Brief** | You say what the film is; the agent turns it into a written brief: story, character, look, length, mood. | you + agent | the brief, one page | edit any line, or rewrite it |
| 2 | **Casting** | The agent renders your character across models, seeds, prompts and LoRAs, round by round. You react to a contact sheet each round ("more like #3, warmer, keep the collar"). It ends with a **cast record** — a locked look. | agent renders, **you pick** | a contact sheet per round, with measured identity/look scores | steer every round; pick; ask for another round; stop |
| 3 | **Scene plan** | The agent writes the shots: what happens, framing, camera, lighting, timing, music. Every scene re-states the character. | agent | the plan, scene by scene, on the board | edit a scene, reorder, change a shot, add/remove |
| 4 | **Export** | The plan, the cast, the reference images, the prompts, the stills and the music land in a VRGDG Builder project, ready to render. | agent | the Builder timeline, fully filled | change anything in the Builder before rendering |
| 5 | **Render** | You press render in the Builder. This is the creative eye on each take. | **you** (Builder) | the clips | re-take a scene, tweak a prompt, try a seed |
| 6 | **Import** | Your clips and your timeline come back into the film's record with the same scene ids they left with. | agent | the manifest and the cut | — (it is a read) |
| 7 | **Dailies** | The agent checks every clip against what the scene asked for and against the cast record: wrong motion, artifacts, the character drifted. It flags; it never decides. | agent flags, **you decide** | a dailies report: which takes look wrong and why | keep, re-shoot one scene (back to step 4 for that scene), or change the plan |
| 8 | **Post** | Colour, grain, face repair, enhance, stitch, final. | agent (VRGDG's post routes) | the final cut | approve, or send back |

Two rules hold everywhere:

- **The machine narrows, the human picks.** Every ranking, flag or score is
  input to your decision, never the decision (DECISIONS #15).
- **Nothing runs unseen.** Every step writes a checkpoint you can approve or
  send back, logs what it chose and why, and appears on the board while it is
  happening (AGENT_GUIDE, Rule Zero).

Steps 2 and 7 are **loops** — the two places where quality actually comes from.
Everything else is a straight line.

---

## 2. What exists today, per step

Honest inventory. "Exists" means built, tested and run live on this machine.

| Step | Exists | Missing |
|---|---|---|
| 1 Brief | `creative-intake`, `taste-direction` meta skills; `brief` artifact schema | a VRGDG-aware brief (character block, look, music intent) |
| 2 Casting | the instrument: `screen_test` tool, five calibrated axes, model registry, render clock, cast record shape | **the conversation** — a skill that turns your reaction into the next round |
| 3 Scene plan | scene-director skills in every pipeline; `scene_plan` schema; shot-language vocabulary | a VRGDG-aware director: character re-stated per scene, shot families, beat-aware timing |
| 4 Export | the bridge, cast-aware: model, seed, references per shot family, both prompts, stills, music with beats | a skill with a checkpoint around it; session bootstrap still manual (HANDOFF trap) |
| 5 Render | the Builder | — |
| 6 Import | the bridge | a skill with a checkpoint around it |
| 7 Dailies | `visual_qa`, `composition_validator`, ArcFace + CLIP — wired to nothing | **the loop** |
| 8 Post | VRGDG's LUT / grain / face-fix / enhance / stitch routes (L4) | everything on our side |

The plumbing between 3 → 4 → 5 → 6 is proven as of today (round trip in
progress; the export half verified live). What is missing is almost entirely
*skills and gates* — the layer that makes the steps visible and steerable.

---

## 3. Principles this plan will not break

These come from the repo's constitution and from what was measured this week.

1. **The agent orchestrates; Python is tools and persistence.** No workflow
   engine in Python. A dashboard button cannot run a step — it can only *ask*
   the agent to (see WP4).
2. **VRGDG authors its session; we mutate known keys** (DECISIONS #2). The one
   place this may be revisited is session bootstrap, and only through a VRGDG
   route that constructs the session for us (#32).
3. **Calibrated or marked NOT CALIBRATED** (#27). Four guessed constants were
   checked this week; all four were wrong. The Lab inherits this rule whole.
4. **A recipe travels only into a graph of the same shape** (#25).
5. **Standalone first.** Each skill works on its own from a plain request; the
   pipeline is just the order and the gates.
6. **Every step re-states the character** (#33). "The same heroine" produced a
   different woman. The scene-plan skill enforces it.

---

## 4. Work packages

### WP1 — `WORKFLOW.md` and the skill contract

**What.** The user-facing manual: the eight steps of section 1, and for each —
how to start it (the words to say, or the button), what it needs, what it
produces, where the result lands, how to review and how to send it back. Plus
a one-page *skill contract* that every step skill follows:

```
skills/production/<step>.md
  triggers      the phrases and the dashboard action that start it
  needs         artifacts in, and which must be approved
  does          the work, in numbered moves
  produces      artifact(s) + checkpoint + decision_log entries
  presents      what the human sees, and the questions asked
  send-back     what a rejection re-runs
```

**Why first.** It is the spec for everything below, and it makes every gap a
sentence you can point at. Half its rows will say "not yet" on the day it is
written; the plan is done when none do.

**Done when.** Every step has a page; every "not yet" is linked to a WP.

### WP2 — the casting skill (the interactive loop)

**What.** `skills/production/casting.md` + a small `lib/casting_session.py`
that keeps a casting's state on disk (`projects/<id>/casting/session.json`:
brief, rounds, reactions, favourites, the running shortlist).

The loop:

```
 brief ─► round 1: models only, one shared seed          → contact sheet
        ─► you react ─► round 2: seeds × prompts on picks  → contact sheet
        ─► you react ─► round 3: LoRAs × conditions        → contact sheet
        ─► "that's her" ─► cast record locked, references per shot family
```

**Reactions become rounds.** The skill owns a small vocabulary and maps it to
matrix changes — *warmer / cooler* → lighting key and colour temperature;
*more like #3* → that candidate's model and seed seed the next round; *keep
the collar* → the phrase is pinned into every prompt variant; *try LoRAs* →
the registry's LoRA list for that family; *different face* → seed sweep on
the same description. Anything outside the vocabulary is asked back in plain
words.

**What it reuses.** `screen_test` (the matrix, the axes, the contact sheet),
`model_registry` (candidates, LoRAs, recipes), `render_clock` (how long a
round costs, and whether it fits the evening), `cast_record`.

**What it adds.** Round history that survives the session; references rendered
per shot family (close / medium / wide) for the winner, so DECISIONS #30 is
satisfied on export; a `casting` decision_log category.

**GPU.** Yes — a round is 5–40 renders. Must wait for the LTX render to end.

**Done when.** A character is cast end-to-end in conversation, the cast record
carries three references, and export consumes it with no hand edits.

### WP3 — production skills and the pipeline definition

**What.** One skill per remaining step, then the manifest that orders them.

| Skill | Wraps | Gate |
|---|---|---|
| `brief` | intake + taste direction, VRGDG-aware | approve |
| `scene-plan` | scene director; character block injected per scene; shot family per scene; beat-aware durations from the music | approve |
| `export` | `vrgdg_project_sync export` | approve the Builder state (screenshot + summary) |
| `render` | none — a human step with a checklist and the traps | you say "done" |
| `import` | `vrgdg_project_sync import` | auto |
| `dailies` | `visual_qa` + `composition_validator` + ArcFace/CLIP against the cast record; per-clip verdicts | approve / re-shoot scene N |
| `post` | VRGDG post routes (L4), one at a time | approve |

`pipeline_defs/vrgdg-character-film.yaml` orders them with
`checkpoint_required: true` everywhere and `human_approval_default: true` on
brief, casting, scene_plan, export, dailies, post. Backlot reads this manifest
and shows the rail automatically — no board work needed for visibility.

**Re-shoot path.** A dailies send-back names scenes. Export then re-exports
*only those scenes* into the existing Builder project (the bridge already
matches segments by stable id; it needs a `scene_ids` filter and must refuse to
touch segments with videos unless told).

**Also in this WP** (small, each a HANDOFF trap or a #32 leftover):
`ConceptPrompts.txt` / `I2VMotionNotes.txt` synced on export; per-scene
`i2v_video_settings` (an orbit needs different settings than a static shot);
the session-bootstrap route so step 4 needs no click in the Builder.

**Done when.** A film runs all eight steps through checkpoints, every gate
stops, a send-back at dailies re-exports one scene, and the whole run replays
on the board.

### WP4 — Backlot as the cockpit

**What.** Grow the read-only board into the Wizard-style dashboard.

- **A stepper rail** (the eight steps) with state chips: waiting / running /
  awaiting you / approved / sent back. Backlot already derives these from
  checkpoints; the rail is a layout change.
- **A panel per step**: the artifact rendered readably (brief as a page, plan
  as a filmstrip, casting as contact sheets with scores, dailies as a
  verdict list), the decision_log entries for that step, and the actions.
- **Actions**: *Run this step*, *Approve*, *Send back with a note*, *Re-shoot
  scene N*, *Another casting round with: …*.

**How an action runs anything** — the constitution says Python may not
orchestrate, and the agent is not inside the server. So an action writes a
**request file**, `projects/<id>/requests/<timestamp>_<action>.json`, and the
agent consumes the queue: in Claude Code, a `/loop` that checks the folder;
later, the Agent SDK running headless. The board shows "requested → picked up
→ running → done" from the same watcher it already has. Approvals go the same
way: the board records the human's decision; the agent writes the checkpoint
with `human_approved` set, because that is the only path that validates.

**Not a ComfyUI node** — it could not show a screenplay or a contact sheet,
and it lives inside a canvas the workflow does not. **Not a new app** —
Backlot is that app.

**Done when.** A casting round and a scene re-shoot can each be started from
the board and their results appear there without touching a terminal.

### WP5 — the ComfyUI Lab

**What.** The screen test, generalized from *which model* to *which graph*.

- **Graph variants.** Take a graph — a bundled workflow, a VRGDG template, or
  a user's API-format JSON — and produce controlled variants: sampler,
  scheduler, steps, CFG, denoise, LoRA stack and strengths, resolution,
  attention/precision switches, and node substitutions (swap a sampler node,
  insert an upscale pass, add a detailer). API-format JSON mutation, the same
  way VRGDG's routes patch their own templates; `prune_to_output` keeps every
  variant valid.
- **The funnel.** Coarse sweep → shortlist → fine sweep, costed by the render
  clock before it runs, on one shared seed unless the axis under test is
  stability.
- **Measurement.** The five calibrated axes plus a graph-shape fingerprint, so
  a result can never be compared across shapes (#25). Any new axis ships
  calibrated or marked (#27).
- **The record.** A winning variant becomes a **recipe** in the registry,
  keyed by graph shape, with the population it was measured on. The
  knowledge outlives the session.
- **The skill.** `skills/production/lab.md`: "make this graph better at X" →
  proposes the variant plan in plain language → you approve the budget → it
  runs, shows a contact sheet, explains what moved the score, and asks what
  to keep.

**Boundary.** Same as casting: it proposes and measures; you choose. It never
overwrites a working recipe without a measured win and an approval.

**GPU.** Yes, and the most of any WP.

**Done when.** One bundled workflow is improved on a stated axis with a
measured, recorded, reproducible recipe, chosen by you from a contact sheet.

---

## 5. Order, dependencies, and what each needs

```
 WP1 WORKFLOW.md ──────────────────────────────────────────────► (no GPU)
   └─► WP2 casting skill ──────────────► needs GPU, after the LTX render
   └─► WP3 skills + pipeline ───► needs the round trip closed (import)
           └─► WP4 cockpit ─────► needs WP3's checkpoints to exist
   └─► WP5 lab ──────────────────► needs GPU; independent of WP3/WP4
```

| WP | Prerequisite | GPU | Rough size |
|---|---|---|---|
| WP1 | none | no | one sitting |
| WP2 | WP1, render finished | yes | one session, plus your reactions |
| WP3 | WP1, round trip closed | little (import, dailies analysis) | two sessions |
| WP4 | WP3 | no | two sessions |
| WP5 | WP1 | yes | two sessions |

**Now, during the render:** WP1 in full, and the *design* of WP2 (the
reaction vocabulary, the session file, the round planner) so that the moment
the GPU is free the first round can start.

**Immediately after the render:** close the round trip (import, verify scene
ids), then WP2.

---

## 6. How we will know it worked

Each WP ends with a live run, not just tests — this week's lesson is that
green tests against a fixture nobody had checked ("what new_project hands
back") hid a false assumption for days.

- WP1: you read `WORKFLOW.md` and can say what happens at every step without
  asking.
- WP2: a character cast in conversation; identity ≥ the darkBeast bar (0.92
  across seeds) or a stated reason why not; three references.
- WP3: the eight gates stop; a dailies send-back re-exports one scene; the
  board replays the run.
- WP4: a round started from the board, result on the board, no terminal.
- WP5: a measured, recorded improvement to one workflow, chosen by you.

---

## 7. Risks and open questions

- **Session bootstrap** (#32): still one click in the Builder. Candidates:
  seed through `save_project_as`, or an upstream fix. Decide in WP3.
- **The agent as queue consumer** (WP4): a `/loop` is fine for one person at
  one machine; it is not a service. The SDK path is the real one, later.
- **GPU contention.** Casting rounds and Lab sweeps both want the evening.
  The render clock decides, and only one runs at a time (the timing trap:
  a busy machine corrupts measurements).
- **The reaction vocabulary will be too small.** Expected. Every phrase the
  skill does not understand gets asked back and, if it recurs, added.
- **Dailies without LTX finished** is guesswork; it is why WP3 waits for the
  round trip.
- **Locations and props** deserve casting too (IDEAS #1). Out of scope until a
  character casts cleanly.

---

## 8. What this plan does not change

The constitution: pipelines in YAML, intelligence in skills, tools as
registered `BaseTool`s, artifacts validated against schemas, checkpoints as
the only save points, the decision log as the only audit trail. Every WP
above is a new skill, a new manifest, a new tool, or a new panel — none is a
second framework.
