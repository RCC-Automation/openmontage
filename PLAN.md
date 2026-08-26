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

A film is made in ten steps. Each step has one owner, produces one thing you
can look at, and stops for your approval before the next one starts.

```
 1. Brief ─► 2. Casting ─► 3. Score ─► 4. Scene plan ─► 5. Scene look ─► 6. Export ─► 7. Render ─► 8. Import ─► 9. Dailies ─► 10. Post
   you+agent    loop          loop        agent           loop             agent        you           agent         loop           agent
               (who is she?   (what does                 (where is she,                (Builder)                   (agent flags,
                agent renders, it sound                   how does it look?                                         you decide)
                you pick)      like?)                     agent renders, you pick)
```

| # | Step | What happens | Who | You get to see | You can |
|---|---|---|---|---|---|
| 1 | **Brief** | You say what the film is; the agent turns it into a written brief: story, character, look, length, mood. | you + agent | the brief, one page | edit any line, or rewrite it |
| 2 | **Casting** | The agent renders your character across models, seeds, prompts and LoRAs, round by round. You react to a contact sheet each round ("more like #3, warmer, keep the collar"). It ends with a **cast record** — a locked look. | agent renders, **you pick** | a contact sheet per round, with measured identity/look scores | steer every round; pick; ask for another round; stop |
| 3 | **Score** | The agent writes the song with you — what it is about, its style, its lyrics — generates it locally, and you listen. Rounds repeat until you say that is it. Ends with a locked track, and its tempo and beat positions **measured from the delivered audio**, never from what was asked for. | agent makes, **you listen** | the lyrics to read, the track to play, the measured beat grid | rewrite a line; change the style; another take; bring your own track instead |
| 4 | **Scene plan** | The agent writes the shots: what happens, framing, camera, lighting, timing, music. Every scene re-states the character. | agent | the plan, scene by scene, on the board | edit a scene, reorder, change a shot, add/remove |
| 5 | **Scene look** | For each scene the agent proposes several *directions* at once (dawn / night with brass lamps / rain at the window), renders them with the cast character in place, and shows a contact sheet. You pick a direction, then a frame. Ends with a **hero still** per scene — the frame the video starts from. | agent renders, **you pick** | a contact sheet per scene, with scores and a continuity check against the cast | pick; ask for more directions; change the prompt; hand a scene to the Lab for a better render |
| 6 | **Export** | The plan, the cast, the reference images, the prompts, the hero stills and the music land in a VRGDG Builder project, ready to render. | agent | the Builder timeline, fully filled | change anything in the Builder before rendering |
| 7 | **Render** | You press render in the Builder. This is the creative eye on each take. | **you** (Builder) | the clips | re-take a scene, tweak a prompt, try a seed |
| 8 | **Import** | Your clips and your timeline come back into the film's record with the same scene ids they left with. | agent | the manifest and the cut | — (it is a read) |
| 9 | **Dailies** | The agent checks every clip against what the scene asked for and against the cast record: wrong motion, artifacts, the character drifted. It flags; it never decides. | agent flags, **you decide** | a dailies report: which takes look wrong and why | keep, re-shoot one scene (back to step 5 or 6 for that scene), or change the plan |
| 10 | **Post** | Colour, grain, face repair, enhance, stitch, final. | agent (VRGDG's post routes) | the final cut | approve, or send back |

Two rules hold everywhere:

- **The machine narrows, the human picks.** Every ranking, flag or score is
  input to your decision, never the decision (DECISIONS #15).
- **Nothing runs unseen.** Every step writes a checkpoint you can approve or
  send back, logs what it chose and why, and appears on the board while it is
  happening (AGENT_GUIDE, Rule Zero).

Steps 2, 3, 5 and 9 are **loops** — the four places where quality actually
comes from: who she is, what the film sounds like, what each scene looks like,
and whether the footage holds. Everything else is a straight line.

**The score sits before the scene plan on purpose.** In a music video the
track decides when to cut, so the shots are written to a measured beat grid
rather than nudged onto one afterwards. Casting does not depend on the song,
which is why it stays first.

Steps 2 and 4 are the same instrument pointed at different questions. Casting
varies the model, seed, prompt and LoRA to find a *person*; scene look varies
the direction, prompt, composition and lighting to find a *place and a frame*,
with that person already in it. Both render, both show contact sheets, both
end when you pick. And when a scene is right but the *rendering* is not —
mushy, artifacts, wrong detail — that is the Lab's job, not another prompt:
scene look explores **what** the image shows; the Lab explores **how** the
graph renders it.

---

## 2. What exists today, per step

Honest inventory. "Exists" means built, tested and run live on this machine.

| Step | Exists | Missing |
|---|---|---|
| 1 Brief | `creative-intake`, `taste-direction` meta skills; `brief` artifact schema | a VRGDG-aware brief (character block, look, music intent) |
| 2 Casting | the instrument: `screen_test` tool, five calibrated axes, model registry, render clock, cast record shape | **the conversation** — a skill that turns your reaction into the next round |
| 3 Score | local generation with lyrics (`comfyui_music`/ACE-Step); VRGDG's beat analysis, already run live on export | **everything on our side**: the loop, the `song` and `beat_map` schemas, lyrics across the seam |
| 4 Scene plan | scene-director skills in every pipeline; `scene_plan` schema; shot-language vocabulary | a VRGDG-aware director: character re-stated per scene, shot families, beat-aware timing |
| 5 Scene look | the same instrument as casting (matrix, contact sheet, calibrated axes); one still per scene rendered with the cast (today: rendered once, never compared); VRGDG's location-reference slot on export | **the loop**: directions at once, pick, refine; a per-scene look record; the continuity check of the cast inside the scene; location references |
| 6 Export | the bridge, cast-aware: model, seed, references per shot family, both prompts, stills, music with beats | a skill with a checkpoint around it; session bootstrap still manual (HANDOFF trap) |
| 7 Render | the Builder | — |
| 8 Import | the bridge | a skill with a checkpoint around it |
| 9 Dailies | `visual_qa`, `composition_validator`, ArcFace + CLIP — wired to nothing | **the loop** |
| 10 Post | VRGDG's LUT / grain / face-fix / enhance / stitch routes (L4) | everything on our side |

The plumbing between 4 → 6 → 7 → 8 is proven — the round trip closed on
2026-08-24, both directions verified live. What is missing is almost entirely
*skills and gates* — the layer that makes the steps visible and steerable —
plus the whole of step 3, which nothing has ever owned.

**The score is now step 3** and nothing behind it is built. No artifact schema
has a word for a song, a beat grid or a lyric, while VRGDG's Builder is built
on all three. That is WP6.

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

### WP2b — the scene-look skill (the second look loop)

**What.** `skills/production/scene-look.md`, sharing WP2's session state
(`lib/look_session.py` serves both: brief, rounds, reactions, picks) with a
scene brief instead of a character brief.

The loop, per scene:

```
 scene + cast ─► round 1: 3–4 directions, one sheet     → you pick a direction
              ─► round 2: prompt variants × composition  → you pick a frame
              ─► round 3 (optional): seeds, or the Lab   → hero still locked
```

**Directions at once.** The agent writes several genuinely different readings
of the scene — time of day, weather, practical light, dressing, camera
height — as full prompts, renders each with the cast model, seed and the
shot-family reference, and shows them side by side. That is "different
scenarios at once, play with prompts, see the results in between."

**What is measured.** Prompt adherence and technical (the calibrated axes),
look consistency between the takes you liked, and — the new one — **the cast
character is still herself inside the scene**: ArcFace against the cast
reference, at still time, when a miss costs 80 seconds instead of two hours.
This is IDEAS 2.4's continuity ledger, started at the cheapest point.

**What it produces.** A per-scene **look record** in the scene plan (direction,
prompt, seed, model, location reference) and the hero still in the asset
manifest — which is exactly what export already pushes. VRGDG's location
reference slot (`flux_location_image_path`, location refs) is filled from the
hero still or a dedicated scout render, so the video step sees the place.

**Where the Lab plugs in.** "Right scene, wrong rendering" hands the scene's
prompt to WP5 with a stated axis (detail, skin, hands, banding); the Lab
returns graph variants on a sheet; the pick becomes a recipe and the hero
still is re-rendered with it.

**GPU.** Yes — a round is 4–12 renders per scene, ~80 s each on this machine.

**Done when.** Every scene of a film has a hero still chosen from a sheet, the
cast survives in each (measured), and export needs no hand-made still.

### WP2c — reference modes: how the Builder consumes what we made

VRGDG's Builder can generate video in five ways (its *Reference Builder
Target* dialog, `assets/references/ReferenceBuilderTarget.png`). Each is a
different answer to one question — **how does the video step know what the
character and the place look like?** Everything to date has used the first.

| Builder target | What the video step receives | Route | Needs | On this machine |
|---|---|---|---|---|
| **I2V / T2V text mapping** | words only, plus the start frame | `i2v` / `t2v` | LTX | **in use** — what the round trip runs |
| **Flux / Nano image references** | character + location *images* condition the **still** (Klein, Nano B) | `flux_klein` | Flux Klein | installed; measured 0.93 identity on a matched shot (#30) |
| **LTX Reference-to-Video** | reference images condition the **video render** itself, via the MSR LoRA | `rtv` | `licon\LTX-2.3-Licon-MSR-V1` | **LoRA not on disk** — the settings name it, the folder does not exist |
| **Ingredients-to-Video** | an *ingredients sheet* — character, props, location tiles — mapped to each scene | `ingredients` | ic-lora-ingredients | installed |
| **ID-LoRA** | an identity LoRA plus voice samples, dialogue, auto duration — short-film scenes with performance | `id_lora` | id-lora celebvhq / talkvid | both installed |

**Why this matters to the plan.** The first mode is the weakest for continuity:
the character reaches the video only through the start frame and a sentence.
The other four are exactly the channels for *the pre-generated things this
plan produces* — the cast record's references, the hero stills, a location
reference — to reach the render as images rather than as descriptions. That
is the quality opportunity, and it is why casting and scene look are worth
doing before any of it: they make the ingredients.

**Where each lands.**

- **Flux/Nano image references → WP2b (scene look).** The hero still can be
  generated *with the cast reference in the frame's own model* — Klein with
  `images` — instead of text-only Z-Image. The scene-look loop should offer
  both and measure; #30 says the reference wins on matched framing and loses
  on mismatched, so the shot-family rule applies.
- **Reference-to-Video and Ingredients → WP3 (export).** `video_model_mode` is
  project-level, like the image mode; the bridge already writes the segment
  fields these modes read (`rtv_reference_behavior`,
  `use_scene_image_as_rtv_ref`, `flux_image_ingredients`,
  `flux_subject_image_path`, `flux_location_image_path`) as blanks. Export
  gains a *video mode* input and fills them from the cast record and the
  look record: character references, the hero still, a location reference,
  an ingredients sheet built from all three. The MSR LoRA must be fetched
  first (add to the installer's manifest).
- **ID-LoRA → L6, two rungs.** Rung one is available today: VRGDG's shipped
  identity LoRAs plus the `id_lora_reference_builder` (characters, voice
  samples, locations, dialogue) — that is the talking-character short film.
  Rung two is L6 proper: train an ID-LoRA **on the cast** so identity no
  longer depends on framing (#29/#30) — the ROCm blocker stands.
- **A video screen test** (IDEAS #1's open question). Once two modes work,
  the same character in the same scene through `i2v`, `rtv` and
  `ingredients`, measured with the dailies axes, decides per film which mode
  carries the identity best. Costly — clips, not stills — so only for
  finalists, and only after the round trip closes.

**Done when.** One film exported in `rtv` or `ingredients` mode from a cast
record and look records, with no hand-placed references, and the dailies
identity score beats the same film in `i2v`.

### WP3 — production skills and the pipeline definition

**What.** One skill per remaining step, then the manifest that orders them.

| Skill | Wraps | Gate |
|---|---|---|
| `brief` | intake + taste direction, VRGDG-aware | approve |
| `scene-plan` | scene director; character block injected per scene; shot family per scene; beat-aware durations from the music | approve |
| `scene-look` | WP2b, invoked per scene or for the whole plan | approve the hero stills |
| `export` | `vrgdg_project_sync export` | approve the Builder state (screenshot + summary) |
| `render` | none — a human step with a checklist and the traps | you say "done" |
| `import` | `vrgdg_project_sync import` | auto |
| `dailies` | `visual_qa` + `composition_validator` + ArcFace/CLIP against the cast record; per-clip verdicts | approve / re-shoot scene N |
| `post` | VRGDG post routes (L4), one at a time | approve |

`pipeline_defs/vrgdg-character-film.yaml` orders them with
`checkpoint_required: true` everywhere and `human_approval_default: true` on
brief, casting, scene_plan, scene_look, export, dailies, post. Backlot reads this manifest
and shows the rail automatically — no board work needed for visibility.

**Re-shoot path.** A dailies send-back names scenes. Export then re-exports
*only those scenes* into the existing Builder project (the bridge already
matches segments by stable id; it needs a `scene_ids` filter and must refuse to
touch segments with videos unless told).

**Also in this WP** (small, each a HANDOFF trap or a #32 leftover):
`ConceptPrompts.txt` / `I2VMotionNotes.txt` synced on export; per-scene
`i2v_video_settings` (an orbit needs different settings than a static shot);
the session-bootstrap route so step 6 needs no click in the Builder.

**Done when.** A film runs all ten steps through checkpoints, every gate
stops, a send-back at dailies re-exports one scene, and the whole run replays
on the board.

### WP4 — Backlot as the cockpit

**What.** Grow the read-only board into the Wizard-style dashboard.

- **A stepper rail** (the ten steps) with state chips: waiting / running /
  awaiting you / approved / sent back. Backlot already derives these from
  checkpoints; the rail is a layout change.
- **A panel per step**: the artifact rendered readably (brief as a page, plan
  as a filmstrip, casting as contact sheets with scores, dailies as a
  verdict list), the decision_log entries for that step, and the actions.
- **Actions**: *Run this step*, *Approve*, *Send back with a note*, *Re-shoot
  scene N*, *Another casting round with: …*, *More directions for scene N*,
  *Send scene N to the Lab for: …*.

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

### WP6 — the score: audio, beats and lyrics

The one part of the film nothing in this plan owns yet. VRGDG's Builder is a
**Music Video** Builder — its timeline is a beat grid and it carries a complete
lyric system. OpenMontage can *generate* a song with lyrics locally, and can
mix, duck and burn karaoke captions. The two meet today at a single file path,
and everything that makes a track a *score* rather than a *file* is dropped in
between.

#### What each side actually has

| Concern | OpenMontage | VRGDG | Who should own it |
|---|---|---|---|
| Make the track | 5 `music_generation` tools; `comfyui_music` is local (ACE-Step 1.5 Turbo) and **takes lyrics**, structure tags, BPM, key | none — it consumes a track | **OM** (already true) |
| Write the lyrics | nothing. `lyric` appears in **no schema** | nothing — it holds them, it does not author them | **OM** — this is the taste layer |
| Measure the beat | `audio_energy` (RMS only, no beats); the `music-to-video` skill's librosa `analyze-beatgrid.py` is rich but **skill-only, not a registered tool** | `analyze_audio` gives `beat_markers`, `detected_tempo_bpm`, `audio_peaks` — already measured, already on this machine | **VRGDG measures, OM records** |
| Hold the lyrics | — | per segment: `lyric_text`, `lyric_section`, `lyric_singers`, `lyric_performance_mode` (`together` or `cue_map`), and `lyric_cue_map` — typed cues carrying `text`, `type` (vocal/instrumental), `start`, `end`, `singer_id`, `singer_name`, `action_note` | **VRGDG holds, OM authors** |
| Say who sings | `cast_record`, ArcFace-calibrated | `lyric_cue_map.singer_id` resolves against the **same `flux_reference_builder` subjects** the casting export already writes | **the match — see below** |
| Time the words | `transcriber` (whisper, word-level) — **UNAVAILABLE here**, `faster_whisper` is not installed | `build_timestamped_transcribe_prompt`, described in its own route registry as *"timestamped lyric transcription to SRT"* | **VRGDG unblocks OM** |
| Show the words | `subtitle_gen` already has `word_by_word` and `karaoke` styles | `srt_mode`, `show_timeline_lyric_notes` | **OM renders, VRGDG times** |
| Mix and duck | `audio_mixer`: `mix` / `duck` / `full_mix` / `segmented_music` | none | **OM**, after import |
| Stems | the `acestep` skill documents ACE-Step's `extract` (vocals/drums/bass/…); `comfyui_music` **does not expose it** | none | **OM** — a real gap |
| Lip sync | none | MiniMax-H3 and HuMo, both **dark on this machine** (below) | blocked, needs a decision |

**The match, in one line: VRGDG owns the clock, OpenMontage owns the meaning.**
VRGDG can say *when* — to the beat, to the word. It has no opinion about what
the song is about or who should be singing it. That is exactly the half
OpenMontage is built for, and exactly the half currently thrown away.

**The single best seam is `lyric_cue_map.singer_id`.** It resolves against
`flux_reference_builder` subjects — the same subject records the casting
export already writes for reference images (DECISIONS #30, #32). So a cast
character can be made *the singer of a line* with no new identity mechanism at
all. Everything already built for casting carries straight over.

#### What is broken or dropped today

Five concrete losses, each verified this session:

1. **The beat grid never comes home.** Export *writes* `beat_markers` into the
   session (19 of them, measured by VRGDG). Import reads back only the scalar
   `detected_tempo_bpm`. The grid — the thing L3 "audio-first timing" is
   entirely about — is dropped at the door.
2. **There is no vocabulary for a song.** No schema in `schemas/` carries
   lyrics, tempo, beats or sections. "Beat" in `scene_plan` always means
   *story* beat (`emotional_beat`, `story_beat`), never *musical* beat. Two
   different things wearing one word is how this stays confusing.
3. **`video_compose`'s FFmpeg path ignores `audio.music.asset_id`.** Only
   `hyperframes_compose` resolves it (`hyperframes_compose.py:1078`). The
   music contract is not uniform across runtimes; today the caller must
   resolve it by hand.
4. **`compose_target` cannot set fps.** Resolution is overridable; frame rate
   is hardcoded to 30 (`video_compose.py`, `fps=30` and `-r 30`). The LTX
   clips are native 24. For a beat-synced film, resampling 24 to 30 at compose
   time is a correctness bug, not a cosmetic one — it is precisely where sync
   drifts.
5. **The ask is not the measurement.** ACE-Step was asked for 90 BPM and
   VRGDG measured 117.5 in the delivered track (PROGRESS). Anything that plans
   cuts from the *requested* tempo is wrong by 30%.

#### What to build

**Tools** — registered `BaseTool`s, per the constitution:

- **`audio_beatmap`** — the one beat analyzer, producing a canonical
  `beat_map` artifact: tempo, beat times, downbeats, phrases, sections,
  energy. Backed by VRGDG's `analyze_audio` (already measured, already on this
  machine, already trusted by the Builder), with librosa as the offline
  alternative. The `music-to-video` skill's rule is the right one and should
  be inherited whole: *one analyzer, and you trust it* — never re-measure
  beats by ear or with a second tool.
- **`lyric_align`** — timestamped lyric alignment, routed through VRGDG's
  `timestamped_transcribe` build route. This unblocks a capability
  `transcriber` cannot provide here, using a graph source that already works.
- **`audio_stems`** — or an `operation` on `comfyui_music`. Isolated vocals
  are what make ducking honest and word alignment accurate.

**Schema** — the missing vocabulary:

- A **`song` artifact**: title, style, the lyrics as sections then lines, and
  per line an optional time range and singer. Authored at the brief; the thing
  you approve before a note is generated.
- A **`beat_map` artifact**: what `audio_beatmap` produces. Referenced from
  `scene_plan.metadata`, so a scene can declare `beat_snapped: true` and mean
  it.
- Rename nothing, but **say which beat you mean.** `story_beat` stays;
  musical beats live only in `beat_map`.

**Bridge** — `lib/vrgdg_bridge.py`:

- Import reads `beat_markers` back into the `beat_map` artifact — closing loss 1.
- Export writes `lyric_text`, `lyric_section`, `lyric_singers`,
  `lyric_performance_mode` and `lyric_cue_map` per segment, from the `song`
  artifact plus the `cast_record`. Singers resolve to cast subjects by id.
- Import reads those fields back, so lyric edits made by hand in the Builder
  survive the trip — the same rule the timeline already follows.

**Lab** — WP5, extended to audio:

- The Lab generalizes the screen test from *which model* to *which graph*.
  ACE-Step is a graph, and it has the same unmeasured knobs: steps, cfg,
  `cfg_scale`, temperature, and the **BPM ask-vs-measure gap** above. That gap
  is a calibration question with a number at the end of it — exactly the Lab's
  shape.
- A **beat-adherence axis**: does a cut land on a beat, and within how many
  milliseconds? Measurable, currently unmeasured. Per DECISIONS #27 it must be
  calibrated against renders from this machine or shipped marked NOT
  CALIBRATED with the population it needs — four guessed bands have been
  checked here and four were wrong.

#### Where it goes — decided 2026-08-24

The track has to exist **before the scene plan**, or scene boundaries cannot
land on beats. Casting does not depend on it. **Raul chose the new step**, and
the renumbering is done: §1 above, `WORKFLOW.md` and
`pipeline_defs/vrgdg-character-film.yaml` (ten stages, nine gated, validates
and loads) all carry ten steps as of this date. The rejected alternative was
folding the score into the Brief step — it keeps nine steps but gives the
track no gate of its own, which for a music video is the wrong trade.

**Score is the fourth loop**: agree the song and the lyrics, generate, listen,
change a line or the style, generate again — the same narrow-then-pick shape
as casting and scene look, with your ear instead of your eye. It ends with a
locked track, a `beat_map`, and a `song` artifact whose lines have times.

The manifest stage is in place and gated.

**Shipped 2026-08-24** — the whole score path, proven live end to end:

| | |
|---|---|
| `schemas/artifacts/song.schema.json` | the words: sections, lines, a singer and a time per line |
| `schemas/artifacts/beat_map.schema.json` | the measured grid, with `confidence` and requested-vs-delivered tempo both recorded |
| `schemas/artifacts/cast_record.schema.json` | written while here — it had **no schema at all**, and an unregistered artifact is *silently skipped* by checkpoint validation |
| `tools/analysis/audio_beatmap.py` | one analyzer, VRGDG's own, so our grid is the Builder's grid |
| `tools/audio/lyric_align.py` | **forced alignment**, not transcription — stems out the vocal, then finds our own words in it |
| `lib/vrgdg_bridge.py` | `session_to_beat_map`, `apply_song_to_session`, `session_to_song` — the grid comes home, lyrics cross both ways |

**Proven on a real track.** A song was authored as words, generated locally
(ACE-Step, 20 s, $0), measured, aligned, and round-tripped through the real
86 KB session. Asked for 110 BPM, delivered **112.347** — the gap this WP
exists to catch, caught. Lyrics went out with per-line singers and came back
identical: 4 lines out, 4 back.

The POC found two design bugs that tests over fixtures had not: a line
spanning a cut is written to both shots (right) and came back as two lines
(wrong); and a shot holding 4.16 s of chorus was labelled `verse` because a
verse line touched it first. Both fixed, both now regression-tested.

Still unwritten: the `production/score` skill — the conversation. Two open
questions in `QUESTIONS.md`: how a score export gets a Builder session to
write into (Q3), and whether a cue map needs `singer_id` (Q4).

#### Lip sync — out of scope, decided 2026-08-24

**Raul chose to skip it.** MiniMax-H3's weight is on disk at **0.12 MB** — a
failed download, not a model — and HuMo's nodes are installed with its models
absent entirely. Together they are the difference between *a character in a
music video* and *a character singing the song*, and restoring them means the
~40 GB opt-in group. A character will appear in the film without mouthing the
words.

This does **not** remove the lyric work. Lyrics still cross the seam, still
carry a singer per line, and still drive karaoke burn-in — they simply do not
drive a mouth. If that changes, the two models go into
`Install-VRGDGModels.ps1` next to the MSR LoRAs, and nothing else in this WP
has to move.

**GPU.** Yes for generation (ACE-Step: 30 s for a 9 s track locally) and for
the Lab sweeps. No for the bridge, schema and analysis work.

**Done when.** A song is written and generated in conversation; its beat map
lands in the scene plan; scene boundaries fall on beats; the lyrics reach the
Builder timeline with the cast character named as the singer of each line; and
after import the cut carries the same words back with times, ready for a
karaoke burn.

---

### WP7 — one character, three engines: the workflows an agent can call

**What.** Three production workflows — Juggernaut XL, FLUX.2 Klein, Z-Image —
each driving the *same* character from the *same* references and prompts, each
with its own architecture-matched LoRA, each independently triggerable by an
agent as a skill. Plus the dataset builder that feeds all three LoRAs.

The recommendation this comes from (2026-08-26, Raul's notes) is right on
every architectural point, and the one that decides everything: **a LoRA
belongs to one model family.** A FLUX LoRA cannot load into Juggernaut, a
Juggernaut LoRA cannot load into Z-Image. One curated dataset, three LoRAs.

**The starting position, measured against this machine.** The plan is only as
good as what is installed, and most of the recommendation assumes CUDA.

| The recommendation needs | Here |
|---|---|
| GPU / VRAM | **AMD Radeon 8060S** (gfx1151), ~90 GB unified, ROCm 7.14. No Triton, no xformers, no SageAttention |
| Juggernaut XL | `juggernautXL_ragnarok.safetensors`, 7.11 GB, header-verified SDXL ✅ |
| FLUX.2 Klein 4B or 9B | **4B fp8 only** (`flux-2-klein-4b-fp8`). Inference-only: 80 tensors in `float8_e4m3fn`. No 9B. **Not trainable** |
| Z-Image Base or Turbo | **neither.** Three community fine-tunes, all INT8 or GGUF. **Not trainable** |
| ComfyUI install | **Desktop**, models in the `ComfyUI-Shared` tree (HANDOFF §3) |
| SDXL Base 1.0 | absent (refiner only) |
| SDXL ControlNet (OpenPose, Depth) | absent — `models/controlnet/` is empty |
| InstantID | absent |
| Z-Image Fun Union ControlNet | node `ZImageFunControlnet` present; its `model_patch` file absent |
| Kohya_ss / AI Toolkit | neither installed |
| Native trainer | `TrainLoraNode` + `LoraSave` present; `bitsandbytes` 0.50.1 + `AdamW8bit` **verified working** (HANDOFF §2) |
| LoRA loaders | `LoraLoader`, `LoraLoaderModelOnly` present |
| Klein multi-reference | `ReferenceLatent`, `FluxKontextMultiReferenceLatentMethod` present; VRGDG `flux_klein` route drives it, **measured 0.932** on matched framing (#30) |

So: **exactly one LoRA can be trained here today** — SDXL, against Juggernaut,
with zero downloads. The other two are blocked on base weights. And whether
*any* LoRA trains on ROCm is unverified. That ordering is the plan.

**Principle: three engines behind one cast record.** The "shared interface"
the recommendation asks for — trigger word, LoRA, strength, face reference,
full-body reference, prompt, seed, size — is what `cast_record` already is:
`character`, `brief`, `candidate.model`, `candidate.loras[]`, `engine`, `seed`,
`references{close_up, medium, wide}`, `chosen_by`. It gains **one field**,
`trigger` (the invented token). Every workflow reads the record; the agent never
assembles a payload by hand. Same prompt in all three engines is then a
one-line comparison, which is the point.

**How each workflow reaches ComfyUI.** The three graph sources already exist
(`.agents/skills/comfyui/SKILL.md`); each workflow maps onto one, and two of the
three need **no new graph at all**.

| | Graph source | Identity mechanism | Exists today |
|---|---|---|---|
| **00 dataset builder** | `vrgdg_build` kind `flux_klein`, `images=[face_ref, body_ref]` per shot family | Klein multi-reference (0.932 matched) → ArcFace filter → **human curation** | route ✅, filter ✅ (`lib/character_dataset`), chooser ✅ (`scripts/anchor_chooser.py`). Builder script: rewrite `build_dataset.py` from FaceID to Klein |
| **01 Juggernaut XL** | **custom**: `tools/_comfyui/workflows/character-sdxl.json` + profile | SDXL LoRA + IP-Adapter FaceID (installed) + ControlNet (absent) | graph: `tools/_comfyui/faceid.py` builds it; needs the `LoraLoader` stage and a profile. **Profile binding names are unrestricted**, so `lora_name`, `face_reference` (an absolute path into `VHS_LoadImagePath.image` — no upload needed), `faceid_start_at` bind with **zero tool changes** |
| **02 FLUX.2 Klein** | `vrgdg_build` kind `flux_klein` | Klein LoRA (blocked) + multi-reference (works now) | route ✅ verified live. LoRA via the payload keys `screen_test` already sends (`use_custom_loras`, `lora_1`, `strength_1`) |
| **03 Z-Image** | `vrgdg_build` kind `zimage` | Z-Image LoRA (blocked) + Fun ControlNet (model absent) + prompt | route ✅ verified live (darkBeast, 162 s). **Weakest identity until a LoRA exists** — no adapter for this family |

**The skill.** One skill, `skills/production/character-shot.md`, on the WP1
contract, with the engine as the first move: *"render her on Klein"*, *"same
shot on Juggernaut"*, or no engine named → `cast_record.engine`. That is the
three independent possibilities the recommendation asks for, without three
copies of the same text — and it is what makes cross-engine comparison free.
Registered in `pipeline_defs/vrgdg-character-film.yaml` as a `preferred_tool`
of the `render` stage; Backlot action `shot.render` with an engine picker
(WP4, later).

```
triggers   "render her on <engine>", "a shot of <character> <doing>", shot.render
needs      cast_record (approved), a shot prompt; optional pose image
does       1 read engine  2 resolve graph source  3 bind the record  4 render
           5 measure: ArcFace vs cast_record.references[<family>], face_fraction
           6 present the still with both numbers
produces   the still + provenance (graph hash, model stack, LoRA + strengths)
presents   the image, cos-to-anchor, framing, and which engine ran
send-back  "closer" → adapter/LoRA strength up one notch; "more real" → down
```

**Training, honestly.** The native `TrainLoraNode` defaults to LR 5e-4 with
alpha pinned at 1.0 (`runbook-first-lora.md`); Kohya's 1e-4 assumes alpha 32.
**Use the pair that matches the trainer** or the effective rate is off by 5×.
AI Toolkit and Kohya are the better tools *on CUDA*; here the native node is
the only one with a verified optimizer. Z-Image Turbo needs a special training
adapter; Z-Image Base needs a download. Both are 7.5.

**Order and gates.** Cheapest decisive test first. Nothing below 7.5 downloads
anything.

| | Step | GPU | Gate |
|---|---|---|---|
| **7.0** | **Does LoRA training run on ROCm at all?** Throwaway SDXL LoRA on ~10 images already on disk, native node, against Juggernaut | ~1 h | a `.safetensors` that `LoraLoader` accepts **and** moves ArcFace-to-anchor vs a same-seed no-LoRA render. Fails → stop; use FaceID at generation time (works today, `faceid-on-this-machine.md`) |
| 7.1 | Workflow 01: graph + profile, `lora_name` bound, exposed through `comfyui_image` | smoke only | renders with an empty LoRA slot; provenance carries the stack |
| 7.2 | Workflow 00: rewrite the builder on Klein multi-reference, three anchors (face / body front / body three-quarter), ArcFace filter, chooser sheet | ~1 h | **24 images Raul approved**, balanced per the quota table, every one photographic *by his eye* |
| 7.3 | Train the SDXL LoRA on the curated set; test on **10 held-out prompts** | 1–2 h | identity vs anchor **up** against no-LoRA, **and skin still photographic on the sheet.** Both, or it does not ship |
| 7.4 | `character-shot.md` + manifest registration; run all three engines on one prompt | minutes | one comparison sheet, three engines, one record |
| 7.5 | Klein and Z-Image LoRAs | 2 × 1–2 h | blocked on `FLUX.2-Klein-4B-Base` bf16 and Z-Image Base downloads; same dataset, same captions |
| 7.6 | ControlNet, InstantID | — | optional; ~7 GB of downloads; **add one mechanism at a time** so a failure has one cause |

**What 7.0 protects against.** Every hour lost on 2026-08-26 came from building
on an assumption that was never checked against this machine — a band from a
different mechanism, a yield from different prompts, a ladder from a different
reference type. Training on ROCm is the largest unchecked assumption in the
entire plan, and it sits under all three workflows. One hour settles it.

**Risks.**
- ROCm training fails or is impractically slow — 7.0 answers it.
- The LoRA reproduces the dataset's skin. Untested by anyone; 7.3's gate is the
  test. This is why the dataset engine is Klein rather than FaceID: at the
  strength that holds identity FaceID idealises skin (`faceid-on-this-machine.md`).
- Z-Image identity with no adapter and no LoRA is prompt-only, which we measured
  at 0.31–0.47. Workflow 03 is real but weak until 7.5.
- Five stacked identity mechanisms cannot be debugged. 7.6 adds them one at a
  time with a measurement between each.

**Done when.** One shot prompt, three engines, one cast record, one sheet —
and Raul says which one is her.

## 5. Order, dependencies, and what each needs

```
 WP1 WORKFLOW.md ──────────────────────────────────────────────► (no GPU)
   └─► WP2 casting skill ──────────────► needs GPU, after the LTX render
         └─► WP2b scene-look skill ──────► same instrument, needs a cast
         └─► WP2c reference modes ───────► lands in WP2b (stills) and WP3 (export)
   └─► WP3 skills + pipeline ───► needs the round trip closed (import)
           └─► WP4 cockpit ─────► needs WP3's checkpoints to exist
   └─► WP5 lab ──────────────────► needs GPU; independent of WP3/WP4
   └─► WP6 score ────────────────► schema + bridge now; the loop needs GPU
         └─► feeds WP3 (a Score gate) and WP5 (audio graphs in the Lab)
   └─► WP7 three engines ────────► 7.0 first (1 h, no downloads); one LoRA trainable today
         └─► needs WP2's cast_record; feeds the render stage of WP3
```

| WP | Prerequisite | GPU | Rough size |
|---|---|---|---|
| WP1 | none | no | one sitting |
| WP2 | WP1, render finished | yes | one session, plus your reactions |
| WP2b | WP2 (a cast to put in the scene) | yes | one session, plus your picks |
| WP2c | WP2b; the MSR LoRA fetched | yes (clips) | one session per mode |
| WP3 | WP1, round trip closed | little (import, dailies analysis) | two sessions |
| WP4 | WP3 | no | two sessions |
| WP5 | WP1 | yes | two sessions |
| WP6 | WP1 (renumber done) | yes for the score loop, no for schema/bridge | two sessions |
| WP7 | WP2 (a cast record); **7.0 before anything else** | yes: 7.0 ~1 h, 7.2–7.3 ~3 h, 7.5 blocked on downloads | three sessions; 7.5–7.6 open-ended |

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
- WP2b: every scene of a short film has a hero still picked from a sheet;
  the cast measured present in each; export consumes them untouched.
- WP2c: a film exported in a reference mode from records alone; its dailies
  identity score beats the text-mapped version of the same film.
- WP3: the nine gates stop; a dailies send-back re-exports one scene; the
  board replays the run.
- WP4: a round started from the board, result on the board, no terminal.
- WP5: a measured, recorded improvement to one workflow, chosen by you.
- WP6: a song written and generated in conversation; scene boundaries land on
  measured beats, not on the requested BPM; the cast character is named as the
  singer of a line in the Builder, and those words come back on import.

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
- ~~**The step renumber** (WP6)~~ **decided 2026-08-24**: Score is step 3, the
  film has ten steps, and §1, `WORKFLOW.md` and the manifest all carry it.
- ~~**Lip sync**~~ **decided 2026-08-24**: out of scope. The models stay
  unfetched; lyrics still cross the seam, they just do not drive a mouth.

---

## 8. What this plan does not change

The constitution: pipelines in YAML, intelligence in skills, tools as
registered `BaseTool`s, artifacts validated against schemas, checkpoints as
the only save points, the decision log as the only audit trail. Every WP
above is a new skill, a new manifest, a new tool, or a new panel — none is a
second framework.
