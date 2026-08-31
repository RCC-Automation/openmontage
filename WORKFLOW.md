# WORKFLOW — how to make a film with OpenMontage + VRGDG

How to run each step, what it needs, what you get back, and how to change it.
For *why* the workflow is shaped this way, see [`PLAN.md`](PLAN.md). For what
is built, [`PROGRESS.md`](PROGRESS.md). For the traps, [`HANDOFF.md`](HANDOFF.md).

Pipeline: `pipeline_defs/vrgdg-character-film.yaml`.

---

## Overview

Ten steps. Each one has a single owner, produces one thing you can look at,
and stops for you before the next begins.

```
1 Brief ─► 2 Casting ─► 3 Score ─► 4 Scene plan ─► 5 Scene look ─► 6 Export ─► 7 Render ─► 8 Import ─► 9 Dailies ─► 10 Post
  agree     LOOP         LOOP        write           LOOP            hand over    YOU         collect     LOOP           finish
            who is       what does               what does                        press                   does it
            she look     it sound                it look like?                    render                  hold?
            like?        like?
```

| # | Step | In one line | Who does it | You get |
|---|---|---|---|---|
| 1 | **Brief** | Agree what the film is | you + agent | a one-page brief |
| 2 | **Casting** | Find the character | agent renders, **you pick** | contact sheets → a cast record |
| 3 | **Score** | Write and make the song | agent makes, **you listen** | a track, its lyrics, its measured beat grid |
| 4 | **Scene plan** | Write the shots, on the beat | agent | the plan, scene by scene |
| 5 | **Scene look** | Find each scene's look | agent renders, **you pick** | contact sheets → a hero still per scene |
| 6 | **Export** | Fill the Builder timeline | agent | a ready-to-render VRGDG project |
| 7 | **Render** | Make the clips | **you**, in the Builder | the footage |
| 8 | **Import** | Bring it back | agent | the manifest and the cut |
| 9 | **Dailies** | Check the footage | agent flags, **you decide** | a report: what looks wrong, why |
| 10 | **Post** | Colour, grain, stitch | agent | the final film |

**Four of them are loops** — 2, 3, 5 and 9. They repeat until you say stop. The
other six run once and pass on.

**The song comes before the shots on purpose.** In a music video the track
decides when to cut. Written first, the shot boundaries land on real beats
because they were planned that way — not nudged into place afterwards.

**Two rules hold everywhere:**

- *The machine narrows, you pick.* Scores and flags are input to your decision,
  never the decision.
- *Nothing runs unseen.* Every step stops at a checkpoint you approve or send
  back, and records what it chose and why — see
  [How every step ends](#how-every-step-ends--the-checkpoint). Skipping the
  gate is a hard error, not a habit.

**To start anything, just say it in words** — "let's cast the character",
"show me other looks for scene 2", "export it". The agent reads the pipeline,
runs the step's skill, and stops at the gate.

---

## Before you start

| | |
|---|---|
| ComfyUI Desktop | running, with the VRGDG node pack loaded |
| Models | `Install-VRGDGModels.ps1 -Preview` shows all 14 `[have]` |
| Project | `python -m backlot open <project-id>` to watch it happen |
| GPU | one job at a time — a casting round and a render cannot share it |

---

## How every step ends — the checkpoint

**This is the way to work. It is not optional, and it is not paperwork.**

A step is not finished when the files exist. It is finished when a *checkpoint*
records that it finished — which stage, what it produced, whether you approved
it, and what it left unresolved. Artifacts on disk prove work happened. Only a
checkpoint proves it was **approved**, and only a checkpoint tells a session
opening this project cold what to do next.

```bash
# what state is the film in?
.venv/Scripts/python.exe scripts/checkpoint.py --project <id> --list

# a step produced something; show it and stop
.venv/Scripts/python.exe scripts/checkpoint.py --project <id> --stage score     --status awaiting_human --note "what it produced" --open "what it did not settle"

# you approved it
.venv/Scripts/python.exe scripts/checkpoint.py --project <id> --stage score     --status completed --approved
```

Run it with **the repo venv** — writing a checkpoint validates every artifact
against its schema, which needs `jsonschema`.

### The protocol, in order

1. The agent runs the step and writes the artifact to `artifacts/<name>.json`.
2. The agent writes `--status awaiting_human`, shows you what it made, **and
   stops**.
3. You approve, or you send it back.
4. Only then does the agent write `--status completed --approved`.

Step 4 before step 3 is a **hard error**, not a convention:

```
GATE VIOLATION: stage 'brief' requires human approval
(human_approval_default: true in the 'vrgdg-character-film' manifest)
but status='completed' was written without human_approved=True.
```

So is running a step whose predecessors are not finished and approved:

```
PREREQUISITE VIOLATION: stage 'score' cannot advance;
incomplete or missing: ['brief', 'casting'].
```

Which stages gate is declared per stage in the pipeline manifest
(`human_approval_default`), never decided by the agent.

### What this buys, concretely

| | Without a checkpoint | With one |
|---|---|---|
| **Resume** | `get_next_stage()` always answers `brief`, however much of the film is made. What is done lives in prose a new session must read and believe. | The session asks the project and gets an answer. |
| **Gate** | Exporting a half-picked film to the Builder is something we *remember* not to do. | It is refused. |
| **Send back** | Dailies finds shot 22 drifted and there is nothing to reopen — only redoing it by hand. | The superseded checkpoint is copied to `history/`; the stage reopens with its record intact. |

### Carry the unresolved things forward

`--open` is how something unsettled survives the step that found it. It is
recorded *in the checkpoint*, so it travels with the film and appears on the
status page under **Carried forward**, instead of living in a chat transcript
that the next session will not read.

Use it for anything true and unfinished: a success criterion the stage did not
meet, a plan the work overturned, a number nobody measured. An honest `--open`
is worth more than a clean-looking `completed`.

---

## Your status page — one HTML per film

Every project carries **`projects/<id>/status.html`** — the film's live state as
one page you can read on a phone: the ten stages, the track with its measured
sections, the plates you picked, all the shots, the render clock, the clips.

```bash
python scripts/project_page.py --project <id>
```

It is **generated, never written**. Every number, image and stage state is read
off the project on disk at the moment it runs, so it cannot drift — there is
nowhere for it to keep a stale copy. `scripts/checkpoint.py` regenerates it on
every write, so it stays current without anyone remembering.

Two readings sit side by side on it and are never merged:

- **Checkpoint** — what the governance record says.
- **Evidence** — what is actually on disk.

When they disagree, that *is* the finding: a stage that ran outside the
pipeline, or a checkpoint written for work that never landed.

Publish it once as an Artifact and republish the same file path afterwards; the
URL stays put, so the link you hold is always the current state of the film.

---

## 1. Brief — agree what the film is

**Say:** *"I want to make a short film about …"*

**You get:** a one-page brief — story, character, look, length, mood — written
from your description.

**Review:** the character block is the part that matters. It gets pasted
verbatim into every scene later, so it must stand alone: *"a clockwork heroine
with luminous pink hair and a brass filigree collar"*, not *"the heroine"*.

**Change it:** edit any line, or say what is wrong and it is rewritten.

**Status:** the meta skills exist (`creative-intake`, `taste-direction`); the
VRGDG-aware brief skill is **not yet written** — today the agent writes the
brief conversationally.

---

## 2. Casting — find the character *(loop)*

**Say:** *"let's cast her"*

This is a conversation, not a batch job:

```
round 1   every eligible model, one shared seed        → contact sheet
          you react:  "more like #3, warmer, keep the collar"
round 2   seeds and prompt variants on your picks      → contact sheet
          you react:  "try the LoRAs"
round 3   LoRAs, conditions                            → contact sheet
          you say:    "that's her"                     → cast record locked
```

**You get, each round:** a contact sheet, plus measurements — how stable the
face is across seeds (ArcFace), how steady the whole look is (CLIP), how well
it matches the prompt, technical soundness, and speed.

**Why the measurements matter:** a model that makes one beautiful portrait but
a different face every seed is useless for a film. On this machine that showed
up as darkBeast **0.92** versus Zpop **0.42** — the same brief, three seeds,
three different women in one case.

**What you end up with — the cast record:** model, seed, LoRAs, settings, and
a reference image *per shot family* (close / medium / wide). Everything after
this uses it.

**Change it:** ask for another round, change the brief mid-way, or stop and
keep the best so far.

**Status:** the instrument is **built and calibrated** (`screen_test`, five
axes, model registry, render clock). The **conversation skill is not yet
written** — today a round is run by hand with `scripts/quick_screen_test.py`.
Needs the GPU.

---

## 3. Score — write and make the song *(loop)*

**Say:** *"let's do the song"*

The track comes before the shots because in a music video the track decides
when to cut. Write it first and the scene boundaries land on real beats
because they were planned that way, instead of being nudged into place after
everything else is locked.

Like casting, this is a conversation:

```
round 1   agree the song: what it is about, the style, the lyrics   → words on a page
          you react:  "second verse is too wordy, make it darker"
round 2   generate it locally (ACE-Step)                            → a track to play
          you react:  "slower, and lose the vocal in the intro"
round 3   generate again                                            → a track to play
          you say:    "that's it"                                   → score locked
```

**You get, each round:** the lyrics to read and the track to play. Once you
approve one, it is measured — tempo, beat positions, sections — and that
measurement, not what we asked for, is what the rest of the film is timed to.

**Why the measurement matters:** the generator was asked for 90 BPM on this
machine and delivered **117.5**. Anything planned from the number we requested
would have been out by 30% — every cut in the wrong place, for a reason
nothing would have reported.

**What you end up with:**

| | |
|---|---|
| the track | an audio file, in the project |
| the song | the lyrics, in sections, each line with a time and (optionally) who sings it |
| the beat map | measured tempo, beat positions, sections — what the scene plan cuts to |

**Who sings what.** If the film has more than one character, a line can be
assigned to one of them. The singers are the same characters you cast in step
2 — no separate casting, no second identity system. The Builder understands
this natively.

**Change it:** rewrite a line and regenerate, change the style, ask for
another take on the same lyrics, or bring your own track instead — dropping a
file in skips generation entirely and goes straight to measuring it.

**Status:** **not built.** The pieces exist and are proven — local generation
with lyrics (`comfyui_music`, ACE-Step 1.5 Turbo, about 30 s for a 9-second
track), and VRGDG's beat analysis, which already runs on export and produced
the 117.5 above. What is missing is the loop, the `song` and `beat_map`
artifacts, and carrying lyrics across into the Builder. That is **WP6** in
`PLAN.md`. Needs the GPU for generation.

---

## 4. Scene plan — write the shots

**Say:** *"write the scene plan"*

**You get:** the film, scene by scene — what happens, framing, camera move,
lighting, timing — as `artifacts/scene_plan.json`, shown on the board.

**Review:** every scene description must **re-state the character**. This is
not a style rule; it is measured. A scene that said *"the same clockwork
heroine"* rendered a different woman: identity 0.34. Restating her brought it
to 0.55 and back to pink hair.

**Change it:** edit a scene, reorder, add or drop one, change a shot size.
Shot sizes should match the shot families your cast record has references for.

**Retime it against the delivered track — always.** The shot list is written
before the song exists, so its times are placeholders. `retime_plan.py` maps
each shot-list section onto the song's *measured* boundaries, keeps the relative
durations inside a section, and writes `artifacts/scene_plan.json`:

```bash
python scripts/retime_plan.py --project <id> --dry-run   # look first
python scripts/retime_plan.py --project <id>
```

It runs two gates and reports rather than edits, because the fix is yours:

- **Too short** — nothing under 1.5 s. Below that a shot is a flicker, not an
  image. Three shots in the first film were invisible for exactly this reason.
- **Too long** — anything longer than the longest clip this machine has actually
  rendered (5.06 s) needs more frames, and render cost scales with frames.

**Status:** scene-director skills exist for other pipelines; the VRGDG-aware
one is **not yet written**. Today the agent writes the plan directly, retimes it
with `retime_plan.py`, and validates it against the schema.

---

## 5. Scene look — find each scene's look *(loop)*

**Say:** *"show me looks for scene 2"* — or let it run for the whole plan.

Same instrument as casting, pointed at a different question:

```
round 1   3-4 genuinely different directions           → one sheet
          (dawn / night with brass lamps / rain at the window)
          you pick a direction
round 2   prompt variants, composition, lighting       → sheet
          you pick a frame                             → hero still locked
```

**You get:** a contact sheet per scene, each frame rendered with your cast
character in it, scored — including **whether she is still herself** in that
scene, measured against the cast reference. Catching drift here costs 80
seconds; catching it after the video costs two hours.

**What you end up with:** a *hero still* per scene — the exact frame the video
will start from — and a look record (direction, prompt, seed, model,
references).

**If the scene is right but the render is not** — mushy, bad hands, banding —
that is not another prompt. Say *"send scene 2 to the lab"*: same prompt,
different graph settings, compared and measured.

**Status:** **not yet written.** Today the agent renders one still per scene
with `comfyui_image` and nothing is compared. Needs the GPU.

---

## 6. Export — fill the Builder timeline

**Say:** *"export it"*

**What lands in the VRGDG project:**

| | from |
|---|---|
| two scenes on a timeline with the right durations | scene plan |
| the image prompt (Image Prep) | shot language + style |
| the video prompt (Video Prep) | the scene's movement text |
| the cast model + fixed seed, per scene | cast record |
| reference images, per shot family | cast record |
| the hero still on each scene | asset manifest |
| the music, with beat markers and tempo | your track, analysed by VRGDG |
| a silent bed and an SRT if there is no music | scaffolded |

**Then, in the Builder: reload the project.** The Builder does not watch the
session file — it shows what it loaded. Worse, saving from a stale view
overwrites the export. Always reload first.

**Review:** open the project and look. Two scenes, prompts filled, stills on
the timeline, waveform with beat markers.

**Change it:** anything, in the Builder, before rendering. Or fix the plan and
re-export.

**One manual step remains:** the project must exist first. VRGDG's
`new_project` route creates folders but never writes a session — only its UI
does. So: **New Project** in the Builder once, then export into it.

**Status:** **built and verified live**, including cast, references, stills,
prompts and audio.

---

## 7. Render — make the clips

**In the Builder:** select a scene → **Create Scene Video**. Or **Render All**.

**This step is yours.** It is the creative eye on each take, and the agent
cannot have it.

**Know before you start:**

- **The first render looks frozen.** ~21 GB of LTX weights load off disk and
  ComfyUI serves HTTP from the same process. The UI can sit unresponsive for
  minutes. It is not hung — do not restart ComfyUI.
- **This machine's measured LTX pace:** ~75 s per step, and the upscale pass
  ran ~34 min per step at 1920×1080 — nearly two hours for one scene. Drop the
  export resolution to 1280×720 for tests.
- **Render Log** shows progress and an ETA.
- Once a scene has a video, its timing locks. Expected.
- Don't rename or move the project folder — import finds everything through it.

**Status:** works. This is VRGDG's own path.

---

## 8. Import — bring it back

**Say:** *"import it"*

**You get:** your clips and stills copied into the OpenMontage project, an
`asset_manifest`, and `edit_decisions` with the cut read off your timeline.

**The thing that proves the system:** the scene ids come back the same as they
went out. Reorder scenes in the Builder and they still map correctly.

**Status:** **built**, not yet run live end-to-end (waiting on the first
render).

---

## 9. Dailies — check the footage *(loop)*

**Say:** *"run dailies"*

**You get:** a per-clip report — does the clip show what the scene asked for,
is the motion right, are there artifacts, and **is the character still
herself**, measured against the cast record.

**It flags; it never decides.** You keep a take, re-shoot a scene, or change
the plan.

**Re-shoot path:** *"re-shoot scene 2"* re-exports only that scene into the
existing project. Scenes with finished videos are not touched unless you say so.

**Status:** **not yet written.** The parts exist (`visual_qa`,
`composition_validator`, ArcFace, CLIP) and are wired to nothing.

---

## 10. Post — colour, grain, stitch

**Say:** *"finish it"*

LUT, film grain, face repair, enhance, stitch to a final cut — VRGDG's post
routes, applied one at a time so you can see each.

**Status:** **not yet written** on our side (VRGDG's routes exist — L4).

---

## The skill contract

Every step's skill follows one shape, so they are interchangeable and a
pipeline is only an ordering:

```
skills/production/<step>.md

  triggers    the words that start it, and the dashboard action
  needs       artifacts in, and which must be approved first
  does        the work, in numbered moves
  produces    artifact(s) + a checkpoint + decision_log entries
  presents    what the human sees, and the questions asked
  send-back   what a rejection re-runs, and what it keeps
```

A skill must be usable **on its own** — "cast a character for me" with no film
in progress — and inside the pipeline. A cast record outlives the film it was
made for.

---

## What actually works today

**Every step now has a skill** under `skills/production/`, and a contract test
asserts the manifest never names one nobody wrote. What varies is how much
machinery sits behind each.

| Step | Skill | Machinery behind it |
|---|---|---|
| 1 Brief | written | conversational; nothing else needed |
| 2 Casting | written | instrument built + calibrated; **the loop has not been run through the skill yet** |
| 3 Score | written | **tools built and proven live** — generate, measure, align; loop not yet run |
| 4 Scene plan | written | schema-validated; **`retime_plan.py` built and run live** — sections mapped onto the measured track, both length gates reporting |
| 5 Scene look | written | **the loop itself is not built** — same instrument as casting, not yet pointed at scenes |
| 6 Export | written | **built, verified live** — cast, references, stills, prompts, audio, lyrics |
| 7 Render | written | the Builder; nothing for us to build |
| 8 Import | written | **built, verified live** — round trip closed 2026-08-24 |
| 9 Dailies | written | **not built** — the parts exist (`visual_qa`, ArcFace, CLIP), wired to nothing |
| 10 Post | written | compose works; VRGDG's grade/grain/face-fix routes not wired |

The plumbing is proven end to end and every step is now *described*. What
remains is the interactive machinery behind steps 2, 3, 5 and 9 — the four
loops, which is where the quality comes from. `PLAN.md` sequences that work.

---

## Reference modes — how the video learns what things look like

VRGDG can feed the video step in five ways. Everything so far has used the
first, which is the weakest for continuity.

| Mode | The video render receives | Status here |
|---|---|---|
| I2V / T2V text mapping | words + the start frame | **in use** |
| Flux / Nano image references | character + location images condition the still | Klein installed; measured 4× a description on matched framing |
| LTX Reference-to-Video | reference images condition the video itself (MSR LoRA) | LoRA **now installed** (V1 + V2) |
| Ingredients-to-Video | a sheet of character/prop/location tiles per scene | LoRA installed |
| ID-LoRA | identity LoRA + voice, dialogue, auto duration | LoRAs installed |

These are the channels through which casting and scene look pay off: the cast
references and hero stills reach the render as *images* rather than
descriptions. Wiring them is `PLAN.md` WP2c.
