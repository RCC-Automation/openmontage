# PROGRESS

State of the VRGDG integration. Update this when something lands.

**Last updated:** 2026-08-31
**Branch:** `integration/comfyui-local` (fork `RCC-Automation/openmontage`, upstream `calesthio/OpenMontage`)
**HEAD:** tip of `integration/comfyui-local`, **8 commits ahead of
`origin/integration/comfyui-local`** — push when convenient. Deliberately not
naming the tip SHA: a docs commit invalidates its own HEAD line, and chasing it
is how this file drifts.

---

## The plan, in six layers

| | Layer | Direction | Status |
|---|---|---|---|
| **L0** | Custom workflows via node-ID binding profiles | OM → ComfyUI | ✅ shipped (pre-existing); SDXL checkpoint now swappable |
| **L1** | VRGDG as the graph builder | OM → VRGDG | ✅ **committed** `cd915f0`, verified live |
| **L2** | `scene_plan` ⇄ builder session | both | ✅ **committed** `1e78f71`, not yet run live |
| **L3** | Audio-first timing (beats → scene boundaries) | VRGDG → OM | ◧ half-open: real audio + beats land on export (#34); beat-snapped read-back not started |
| **L4** | Local post tier (LUT, grain, face fix, enhance) | VRGDG → OM | ⬜ not started |
| **L5** | OpenMontage as VRGDG's prompt writer (LM Studio shim) | OM → VRGDG | ⬜ not started |
| **L6** | One character bible + commissioned LoRA | both | ⬜ design only — ROCm blocker |

Full design: `claude/openmontage-vrgdg-integration.md` in the attached Claude project.

---

## L1 — VRGDG as the graph builder ✅

Committed as `cd915f0`.

| File | Lines | |
|---|---|---|
| `tools/_comfyui/vrgdg.py` | 677 | `VRGDGClient`, `VRGDGGraph`, 17-route registry, output-node resolution, pruning, missing-node preflight |
| `tools/graphics/comfyui_image.py` | +230 | `vrgdg_build` graph source |
| `tools/video/comfyui_video.py` | +214 | same, plus project-bound output fallback |
| `tools/_comfyui/metadata.py` | +78 | `infer_model_stack()` shared by both tools |
| `tests/contracts/test_vrgdg_tools.py` | 461 | 39 tests |
| `scripts/smoke_vrgdg_builder.py` | 88 | live diagnostic |
| `.agents/skills/comfyui/SKILL.md` | +30 | "Graph Sources" section |

**Verified live** — Z-Image via `build_zimage_prompt`, 162 s, correct seed, output
node `975`, provenance complete, dead cleanup branch pruned.

Also folded in: previously uncommitted Juggernaut XL and ACE-Step 1.5 bundled
workflows, and a fix to `test_phase3_contracts` where `comfyui_tts` had added a
`comfyui` TTS provider the hard-coded set never expected.

---

## L2 — the scene_plan ⇄ session bridge ✅ committed `1e78f71`

| File | Lines | |
|---|---|---|
| `lib/vrgdg_bridge.py` | 572 | both directions |
| `tools/video/vrgdg_project_sync.py` | 512 | `VRGDGProjectSync`, `operation: import \| export` |
| `tools/_comfyui/vrgdg.py` | modified | + `save_scene_image()` |
| `tests/contracts/test_vrgdg_bridge.py` | 843 | 66 tests |

**Import** (VRGDG → OM): session → validated `asset_manifest` + `edit_decisions` +
scene map. Assets copied into the project. Overlay track excluded. Cut boundaries
read off the timeline. Missing files warn rather than fail.

**Export** (OM → VRGDG): `scene_plan` → a project that opens in the Builder as a
timeline, with `t2i_prompt` written by `build_shot_prompt`, motion notes, a silent
audio bed and an SRT. Refuses to overwrite existing work.

**Fidelity check against the real session:** exporting a 2-scene plan using the
actual `VRGDG_Project_2026-08-21_23-10-05` as template lost **0 of 108 fields** and
changed **0 project-level keys**.

**Committed** as `1e78f71`. Everything below is what remains uncommitted.

---

## Casting-aware export ✅ built, ✅ verified live, not yet rendered

The seam now carries OpenMontage's casting knowledge instead of dropping it.
`vrgdg_project_sync` export accepts `casting` inline or reads
`artifacts/cast_record.json`, resolves the engine from the model registry (by
header, never filename), and writes into the session: per-scene
`<engine>_settings` built on the session's own global group (only `unet_name`,
`seed`+`seed_mode: fixed`, loras overridden), `use_scene_*` flags, per-shot-family
reference images staged into the Builder project's `references/`, and the
project-level `image_model_mode`. DECISIONS #32; references-per-family is #30
operationalized.

Verified live against `VRGDG_Project_EndToEndTest`: darkBeast cast from
`cast_record.json` alone — engine `zimage` resolved from the registry, both
character scenes carry darkBeast at seed 7777 fixed with the user's own
clip/VAE, sc2 (close) got the staged reference with `use_vision_reference`,
sc1 (wide) correctly got none plus the #30 warning, mode flipped
`flux_klein → zimage`, global groups untouched.

Two lanes by engine: Z-Image / Flux Klein land as Builder settings; SDXL warns
and takes the approved-stills lane (`push_approved_stills`). What stays manual:
creating the project (the `new_project` route writes no session — see the
HANDOFF trap and #32); the standing goal is closing that too.

**And the export now fills the whole timeline (DECISIONS #33, revising #9):**
`i2v_prompt` is authored by `build_motion_prompt` (Video Prep opens filled in;
the scene's authored movement text beats the enum phrase), stills are rendered
on the OpenMontage side through `comfyui_image` + the cast, and the push
stages each still into `<project>/openmontage_stills/` as the scene's
`custom_image_path` and records VRGDG's approved copy separately — never the
same file, or the Builder's render prep copies it onto itself (HANDOFF trap;
it cost the first render attempt a WinError 32 that survived a reboot). Verified live: both scenes in
`VRGDG_Project_EndToEndTest` carry image, prompts, cast and reference.

**Audio too (DECISIONS #34, extends #14):** export takes `audio_path`; the
track runs through VRGDG's own `analyze_audio` and the session opens with the
waveform, 19 beat markers and the measured tempo (117.5 BPM — ACE-Step was
asked for 90; use the measured number). `comfyui_music` (local ACE-Step 1.5
Turbo, 30 s for a 9 s track) is the local source. The wrinkle that cost the
first attempt: `save_session` overrides the session's `audio_path` with a
payload-top-level field on every save, and that field is also what makes
VRGDG snapshot the track into the project. The client now sends it.

**The first automated run caught real drift.** sc2's description said "The
same clockwork heroine" — no image model can resolve that — and rendered a
different woman. Our calibrated axes measured it (face 0.34 / look 0.33),
restating the character in the description fixed it (0.55 / 0.68). #29 in
production: every scene's description must restate the character; the systemic
fix is a per-scene character block (L6 direction).

---

## Render clock + screen test ✅ committed `730facd`, ✅ **verified live**

From `IDEAS.md`. Two of the proposed pieces, built together because the second
needs the first.

| File | Lines | |
|---|---|---|
| `lib/render_clock.py` | 433 | GPU-minute budgeting. Learns from `events.jsonl`; seeded with this machine's measured baseline |
| `lib/screen_test.py` | 500 | Matrix expansion, identity stability, prompt adherence, technical score, ranking, contact sheet, cast record |
| `tools/graphics/screen_test.py` | ~430 | `ScreenTest` BaseTool, `capability="casting"`, budget-aware |
| `tests/contracts/test_render_clock.py` | 198 | 24 tests |
| `tests/contracts/test_screen_test.py` | 474 | 41 tests |
| `scripts/quick_screen_test.py` | 110 | one-command runner — **written, never executed** |

**Presets** — three rungs of one funnel, sized against the 9 installed image models:

| preset | renders | est. | question |
|---|---|---|---|
| `quick` | 13 | ~8-10 min | what does each model do with my prompt? |
| `shortlist` (default) | 39 | ~25 min | which models hold an identity worth testing? |
| `full` | 117 | ~75 min | which stack should this character be cast with? |

Counts are 13 now, not 9, because the registry (below) found the real eligible
set. Estimates fell an order of magnitude against the old guesses once measured
timings replaced the unknown-route default: Klein renders in 5 s, SDXL in 35 s.

`quick` uses one condition and **one shared seed across every model**, so only the
model varies. It is the single preset allowed to run on one seed, and it prints
its own caveat because one seed cannot measure identity stability.

**Verified live.** The reported failure did not reproduce. `quick_screen_test.py`
rendered on the first attempt and has since driven all three image graph paths.
Presets are re-costed below now that real timings exist.

**Verified against real history.** Ingested 9 measured runs from the two existing
projects. Costing round 1 of a screen test across the 9 installed image models
(9 x 3 conditions x 3 seeds = 81 renders) gives **~218 GPU-minutes**, correctly
reported as fitting a 4-hour evening with 22 minutes spare, and flagged as
low-confidence because most routes have only one sample.

Design notes worth keeping: unknown routes stay unknown rather than being given a
plausible number; an unknown route is still allowed to run, or the clock could
never learn it; the ranking reweights around metrics it could not compute instead
of assuming them; `picks_a_winner` is `False` and stays that way.

---

## Casting layer: registry, recipes, metrics, identity ✅ committed

Nine commits, `5eb0a09`…`fbef175`. The screen test went from a tool that had
never produced a trustworthy ranking to one whose every axis is calibrated
against renders from this machine.

| File | |
|---|---|
| `lib/model_registry.py` | header identification, driver mapping, name resolution, sampler recipes, run-outcome learning |
| `lib/face_identity.py` | ArcFace identity via InsightFace — detect, align, embed |
| `lib/screen_test.py` | detail gate, `look_consistency`, calibrated adherence, five-axis weights |
| `tools/_comfyui/vrgdg.py` | `VRGDGGraph.apply_sampler_recipe`, `flux_klein` reference-key docs |
| `tools/_comfyui/client.py` | `queue_depth()`, history timeout 10 s → 60 s |
| `tools/graphics/comfyui_image.py` | `checkpoint_name`, `sampler_name`, `scheduler`, provenance retarget |
| `tools/graphics/screen_test.py` | per-candidate routing, recipe modes, contention guard, declared caps |
| `scripts/quick_screen_test.py` | registry-driven pool, `--recipe`, honest reporting |
| `requirements-clip.txt` | torch, transformers, insightface, onnxruntime — all CPU |
| tests | +109 (registry 75, screen test 67 incl. new classes, vrgdg 45) |

### What the model tree actually contains

31 files, **13 eligible**, 0 unknown, 18 excluded each with a stated reason.
Identity comes from the safetensors header, never the filename — two of the five
Z-Image models (`moodyRealMix_ZIT_V7Global`, `darkBeast30BF16INT8_dbzit9DIMRclaw`)
carry nothing in their names that would identify them.

| family | n | driver |
|---|---|---|
| Z-Image | 5 | VRGDG `zimage` |
| SDXL | 7 (6 usable) | bundled `juggernaut-xl-ragnarok-txt2img` |
| FLUX.2 Klein | 1 | VRGDG `flux_klein` |
| Wan / ACE-Step / LTX / SAM / refiner / Flux.1 / Chroma / GGUF | 18 | excluded, reasons recorded |

`gonzalomoXLFluxPony_v70PhotoXLDMD` is a valid SDXL checkpoint sitting in
`diffusion_models/`; `CheckpointLoaderSimple` only lists `models/checkpoints/`,
so it is refused up front. Move it and the next scan picks it up as a 13th
candidate. `minimax_h3_…` is 127 KB — a failed download.

### The five axes, all calibrated against this machine

| axis | weight | state |
|---|---|---|
| `identity_stability` (ArcFace) | 0.30 | calibrated 0.21 → 0.70 |
| `look_consistency` (CLIP) | 0.15 | calibrated 0.58 → 0.97 |
| `prompt_adherence` (CLIP) | 0.25 | recalibrated 0.29 → 0.39 |
| `technical` | 0.20 | a gate: 1.0 usable, 0.0 broken |
| `speed` | 0.10 | relative to slowest |

### Measured findings

**Distilled checkpoints were being mis-driven.** Two models read as broken; both
state their own settings in metadata (10–11 steps, CFG 1.0, `lcm`). Driven
correctly they became the fastest good models on the machine — 35 s → 10 s, and
sharpness 0.07 → 0.45 / 0.00 → 0.39.

**Identity across seeds** (`shortlist`, 3 seeds):

| model | face | verdict |
|---|---|---|
| darkBeast30 | **0.92** | the same woman three times |
| flux-2-klein | 0.71 | |
| gonzalomoZpop_v40 | **0.42** | three different women |

The human picked darkBeast and Zpop as favourites from single frames. They sit at
opposite ends — which is the case for the axis existing.

**Seed does not hold a character** (DECISIONS #29): same prompt / different seeds
= 0.66; same seed / different prompts = **0.47**. Different people = 0.10–0.21.

**A reference image is ~4× a description on a matched shot** (DECISIONS #30):
close-up 0.213 → **0.932** with a reference, but the medium falls to 0.301 and
the wide to 0.493. Use one reference per shot family.

### Results on disk

All under `projects/screen-tests/` (gitignored):

| path | what |
|---|---|
| `casting/clean-{never,auto,always}/model_comparison.png` | 12 models, three recipe modes, comparable |
| `casting/identity/drift_strip.png` | darkBeast vs Zpop across three seeds |
| `seed_vs_prompt/seed_vs_prompt.png` | seed-fixed vs prompt-fixed |
| `klein_reference/reference_test.png` | reference vs no reference across three shots |
| `casting/*/casting_report.json` | every axis, every candidate, every shot path |
| `var/model_registry.json` | the ledger (repo root, gitignored) |

Superseded and safe to delete: `casting/mode-*` (ran while CLIP was coming
online, so their totals are not comparable), `casting/{kleinprobe,sdxlprobe,zprobe,zpoprecipe,recipetest}`,
`cfg_probe/`.


---

## The production workflow ✅ WP1 shipped, the rest planned

`PLAN.md` is the plan Raul asked for before any build: the workflow as **ten
steps**, six work packages, order, GPU needs and how each is verified live.
`WORKFLOW.md` is the manual — the overview he asked for, then a page per step
(how to start it in plain words, what lands, how to review, how to change it,
and the traps that bite at that step).

Four loops — casting, score, scene look, dailies. **Scene look was the gap
Raul found**: casting says who she is, the scene plan says what happens, and
nothing decided what each scene *looks like* before it was locked. It is now
step 5, on the same instrument as casting, producing a hero still per scene.
**Score was the second gap** (2026-08-24): nothing owned the song, the beat
grid or the lyrics, while VRGDG's Builder is built on all three. It is now
step 3, before the scene plan, so cuts land on measured beats — WP6.

```
1 Brief ─► 2 Casting ─► 3 Score ─► 4 Scene plan ─► 5 Scene look ─► 6 Export ─► 7 Render ─► 8 Import ─► 9 Dailies ─► 10 Post
  agree     LOOP         LOOP        write           LOOP            hand over    YOU         collect     LOOP          finish
```

| Shipped | |
|---|---|
| `PLAN.md` | the plan: overview, per-step inventory, WP1–WP5, order, risks |
| `WORKFLOW.md` | the manual, with the status table of what actually works |
| `pipeline_defs/vrgdg-character-film.yaml` | **ten stages, nine gated** (score added 2026-08-24), validates and loads; **not yet runnable** — the stage skills are unwritten. Backlot draws the rail from it |

Decided along the way: standalone skills a pipeline strings together (not
pipeline-only stages); Backlot grown into the Wizard-style cockpit rather than
a ComfyUI node or a new app, with a request queue the agent consumes so Python
never orchestrates; the ComfyUI Lab as the screen test generalized from *which
model* to *which graph*. DECISIONS #35.

---

## WP6 — the score: foundations shipped, the loop unwritten

`PLAN.md` WP6 holds the analysis. What landed 2026-08-24:

| File | |
|---|---|
| `schemas/artifacts/song.schema.json` | lyrics as sections then lines; a singer and a time per line |
| `schemas/artifacts/beat_map.schema.json` | measured grid; `confidence`; requested vs delivered tempo |
| `schemas/artifacts/cast_record.schema.json` | it had **none** — and an artifact absent from `ARTIFACT_NAMES` is *silently skipped* by checkpoint validation, so it went through a whole production unchecked |
| `tools/analysis/audio_beatmap.py` | one analyzer: VRGDG's own, so our grid is the Builder's grid |
| `tools/audio/lyric_align.py` | forced alignment against our own lyrics, vocal stemmed out first |
| `lib/vrgdg_bridge.py` | `session_to_beat_map`, `apply_song_to_session`, `session_to_song` |
| `QUESTIONS.md` | new — blockers parked with the assumption made, not guessed at silently |

**Proven live.** Song authored as words → generated locally (ACE-Step, 20 s,
$0) → measured → aligned → round-tripped through the real session. Asked 110
BPM, **delivered 112.347**; the tempo warning fired. Lyrics out and back
identical, 4 lines each way, singers and times intact.

`lyric_align` is the find of the session. VRGDG's `timestamped_transcribe`
runs stem separation and then **forced alignment against lyrics we supply** —
it is told the words rather than guessing them, so it cannot get them wrong,
and it works over a full mix because the vocal is isolated first. That covers
what `transcriber` cannot do here (`faster_whisper` absent).

**The beat grid now comes home.** Export had been writing 19 markers into the
session and import reading back one scalar, so the grid that timed the film
existed nowhere in our record.

Two design bugs the POC found that fixture tests had not: a line spanning a
cut came back duplicated, and a shot holding 4.16 s of chorus was labelled
`verse` because a verse line touched it first. Both fixed and regression-tested.

---

## WP3 — the pipeline is runnable in shape

All ten stage skills written to the `WORKFLOW.md` contract
(`triggers / needs / does / produces / presents / send-back`), plus the shared
loop state the three picking loops need.

| File | |
|---|---|
| `skills/production/*.md` | ten skills: brief, casting, score, scene-plan, scene-look, export, render, import, dailies, post |
| `lib/loop_session.py` | round history, reactions kept verbatim beside what was made of them, favourites, verdicts, reopening |
| `tests/contracts/test_loop_session.py` | 22 tests |
| `tests/contracts/test_vrgdg_character_film_pipeline.py` | 12 tests — the manifest cannot name a skill nobody wrote, produce an artifact with no schema, need an input nothing made, or reorder score after scene plan |

Each skill carries the traps that actually cost time here, at the step where
they bite — the approved-slot self-copy at export, mis-driven distilled
checkpoints at casting, the two meanings of "beat" at scene plan, the
un-resolved `audio.music.asset_id` at post.

The loops themselves — the conversation that turns "warmer, keep the collar"
into the next round — are still unwritten. That is what WP2, WP2b and the score
loop are.

**The gate machinery was walked live** on `projects/score-poc`, brief → casting
→ score, and it holds: a gated stage written `completed` without approval is
refused as a GATE VIOLATION, a stage that jumps the order is refused as a
PREREQUISITE VIOLATION, `awaiting_human` does not advance `get_next_stage` and
approval does, and a deliberately invalid artifact is refused at write time.

One gap found doing it: **`required_artifacts_in` is enforced by nothing.** A
`scene_plan` completes with no `beat_map` in the project — the exact failure
that moving Score earlier was meant to prevent. It is declared in the manifest
schema and used by all 14 pipelines and read by no code. QUESTIONS Q5, with a
recommendation.

---

## WP2 — the casting loop, run live for the first time

The instrument was built and calibrated weeks ago. What landed 2026-08-25 is the
*conversation*, and running it for real found five bugs that fixture tests had not.

| File | |
|---|---|
| `lib/casting_loop.py` | reaction → matrix. `interpret`, `next_matrix`, `next_brief`, `phone_sheet`, `drift_sheet` |
| `scripts/casting_round.py` | the turn-taking; adopts a round it did not start |
| `tests/contracts/test_casting_loop.py` | 41 tests |

**Two rounds run live with Raul.**

Round 1 — 12 models, one shared seed, 10.3 min. Round 2 — his four picks across
three seeds, split in two after the first attempt killed the backend.

| Model | face | look | brief |
|---|---|---|---|
| zImageUltimateNSFW_v20 | **1.00** | 1.00 | 0.25 |
| darkBeast30 | 0.78 | 0.95 | 0.38 |
| juggernautXL_ragnarok | 0.31 | 0.88 | **0.87** |
| gonzalomoZpop_v40 | 0.28 | 0.91 | 0.47 |

**The two properties you want live in different models.** The one that renders
actual clockwork cannot hold a face; the one that holds a face perfectly renders
generic. The research says take juggernautXL — its weakness is the addable one.

**Bugs found by running it, all regression-tested:** bare numbers were not
parsed as picks at all, so "I like 4, 6, 7 and 8" selected nothing; a
half-understood reaction dropped the rest silently; contractions became
questions; a word-boundary regex contained a literal backspace character; and
the runner could not react to a round it had not started.

**The backend died mid-round.** Four models × three seeds OOM'd, and the OOM
*handler* aborted the process. See `wiki/comfyui/failure-modes.md`.

---

## WP7 — one character across engines: the swap wins, the LoRA does not

Two days on the character pipeline, end to end, on a second character
(`projects/burningman`, "Burning Man girl") built from scratch to test it.

| File | |
|---|---|
| `scripts/anchor_select.py` | cast sweep, N seeds, arithmetic or scattered, cluster, medoid |
| `scripts/anchor_chooser.py` | numbered sheet; `--pick` promotes, `decided_by: human` |
| `scripts/masters.py` | the two body masters from the face crop, on Klein multi-reference |
| `scripts/dataset_klein.py` / `dataset_swap.py` | dataset candidates; the second adds the face swap |
| `scripts/caption_dataset.py` | captions what varies, stages for the native trainer |
| `scripts/train_lora.py` / `test_lora.py` | segmented training with checkpoints; held-out test |
| `scripts/recast_vrgdg_project.py` / `commit_recast.py` | recast an existing VRGDG project |
| `scripts/export_i2v_workflow.py` | the Builder's i2v graph as a standalone ComfyUI file |
| `tools/_comfyui/faceid.py`, `faceswap.py`, `lora_train.py` | the three graphs |
| `lib/character_anchor.py`, `character_dataset.py`, `rejection_dataset.py`, `sheets.py`, `render_realism.py` | |
| tests | +45 (`test_character_anchor` 24, `test_character_dataset` 23, `test_lora_train` 9) |

**LoRA training runs on ROCm** — proven, `QUESTIONS.md` Q7 answered. Native
`TrainLoraNode`, 2.1-2.7 s/step for SDXL, checkpoints via `existing_lora`.

**And the LoRA is not the answer.** Four trainings, best identity **0.37** on
held-out prompts. A **face swap reaches 0.80** with no training. The trainer
takes a `MODEL` input only — 3268 UNet keys, **zero text-encoder keys** — so a
trigger token cannot learn to mean her. `DECISIONS.md` #39.

Four faults were found and fixed inside the LoRA route before that conclusion,
each real and none sufficient: dataset consistency 0.53 → 0.83; **rank is the
scale dial in this trainer** (`alpha` hardcoded 1.0, `scale = alpha/rank`, so
rank 32 was 16× too weak); 62 epochs was double the sane range; the accept band
had been calibrated against a different mechanism.

**Identity mechanisms, all measured against the same anchor:**

| | identity | note |
|---|---|---|
| ReActor face swap | **0.80 – 0.88** | the one in use |
| IP-Adapter FaceID | 0.75 – 0.84 | consistent, and renders her ~10 years younger |
| Klein multi-reference | 0.53 – 0.68 | a family resemblance |
| LoRA, native trainer | 0.12 – 0.46 | UNet-only |

`wiki/character/face-swap.md` carries the settings and the two rules that decide
whether it works.

---

## BurningManGirl — recast, and rendering

The VRGDG project was recast to the new character, and this is the first time
the fork has changed a *finished* project rather than built one.

- **15 scene images** regenerated with her and installed (`openmontage_recast/`),
  appended to each scene's `image_history` with the index moved.
- **575 prompt edits** across seven fields per scene, plus 445 in `storyboard.json`,
  `wizard_draft.json` and both prompt exports. Verified: zero old-character
  mentions anywhere.
- Backups beside the session and every side file.
- Face swap applied only where the face is visible; twelve scenes at 0.68-0.83,
  three left as plain renders because she is turned away or too distant.

**Video: 3 of 15 clips rendered.** The blocker is measured and not subtle — the
LTX upscale refine costs **610 s/step against the base pass's 26 s/step**. It
hung scene 2 for 2.5 hours and crashed the process on scene 4.
`wiki/vrgdg/video-render.md`.

---

## The wiki

`wiki/` — 34 pages on the Karpathy LLM-wiki pattern, lints clean.
`scripts/wiki_lint.py` checks frontmatter, index membership, links and
staleness. AGENTS.md, CLAUDE.md, clock-in and clock-out all route through it.

**Two corrections to our own documentation came out of the research**, and the
difference between them is the lesson:

- **`bitsandbytes` works.** Verified by running it — ROCm backend, `AdamW8bit`
  stepping with real uint8 state. HANDOFF said otherwise and was wrong. **Holds.**
- **`TORCH_ROCM_AOTRITON_ENABLE_EXPERIMENTAL=1` does NOT speed up rendering.**
  8.2× on isolated SDPA, but 75 s vs a 76 s baseline on a real render. I
  extrapolated from a microbenchmark and the extrapolation broke. Kept set for
  training, where it is still untested.

---

## Character consistency research

A 10-family adversarially-verified survey, compiled into `wiki/character/`.
Three runs were needed — connection errors and a session limit killed the
synthesis twice, so `techniques.md` is hand-written and says so.

**The finding that explains a number we could not account for:** there are two
reference mechanisms and they fail oppositely. Latent/pixel reference (Klein,
Kontext) attends to real image tokens and collapses when framing changes;
embedding identity (FaceID, InstantID, PuLID) uses a pose-normalised ArcFace
vector and should survive it — but holds only the face. **Our 0.932 → 0.301
collapse was through the latent path.** The embedding path is untested here.

**The structural answer: reference-THEN-LoRA.** Use reference conditioning to
manufacture a consistent 20–40 image dataset, then train on it.

`wiki/character/runbook-first-lora.md` is the executable path.
**Phases 0 and 1 are done**; Phase 0's gate failed and is recorded as such.

---

## Tests

| Suite | |
|---|---|
| `test_model_registry.py` | 75 passed |
| `test_screen_test.py` | 73 passed |
| `test_vrgdg_tools.py` + `test_vrgdg_bridge.py` | 159 passed (clock-in baseline) |
| `test_character_anchor.py` + `test_character_dataset.py` + `test_lora_train.py` | 56 passed (WP7) |
| `test_vrgdg_tools.py` | 45 passed |
| `test_vrgdg_bridge.py` | 114 passed |
| `test_render_clock.py` + `test_screen_test.py` | 94 passed |
| full `tests/contracts` | **1350 passed, 8 skipped** — no failures |

Artifacts are validated against the real `schemas/artifacts/*.schema.json`, not
spot-checked — a manifest that does not validate fails much later, at
checkpoint-write time, with a far worse error.

Full `tests/contracts` now runs clean on this machine — **1350 passed, 8 skipped
in 75 s**, re-verified 2026-08-28 after WP7. The ~13 `google.genai` / mermaid-CLI failures
noted previously do not appear here; expect them again on a bare environment
without those installed.

---

## Models

Required by VRGDG's LTX templates. Installer:
`…\Comfy-Desktop\_vrgdg_setup\Install-VRGDGModels.ps1` (re-running is always safe).

**All 14 are downloaded.** Verified 2026-08-24 by comparing each local file
against the server's `Content-Length`, not by trusting the installer's report:

| File | Destination | Bytes, local = remote |
|---|---|---|
| `LTX-2.3-22B-distilled-1.1-Q6_K.gguf` | `diffusion_models\` | 21,006,400,160 ✅ |
| `ltx-2.3-22b-dev_transformer_only_int8_convrot.safetensors` | `diffusion_models\LTX_8bit\` | 21,505,993,064 ✅ |
| `gemma-3-12b-it-abliterated…safetensors` | `text_encoders\` | 14,123,240,650 ✅ |
| `ltx-2.3_text_projection_bf16.safetensors` | `text_encoders\` | 2,312,149,072 ✅ |
| `LTX23_video_vae_bf16` / `LTX23_audio_vae_bf16` | `vae\` | 1,452,258,578 / 364,855,188 ✅ |
| `ltx-2.3-spatial-upscaler-x2-1.1.safetensors` | `latent_upscale_models\` | 995,743,560 ✅ |
| `4x-UltraSharp.pth` | `upscale_models\` | 66,961,958 ✅ |
| 4 LTX LoRAs | `loras\`, `loras\LTX\` | all **exact match** |
| `LTX-2.3-Licon-MSR-V1.safetensors` | `loras\licon\` | 654,443,424 ✅ **fetched this session** |
| `LTX-2.3-Licon-MSR-V2.safetensors` | `loras\licon\` | 654,443,392 ✅ **fetched this session** |

**The five that read `[part]` were never partial.** Their `.complete` marker
files had been deleted by hand; they were restored on 2026-08-24 and the
installer now reports all twelve `[have]` — "Everything in these groups is
already present". For a manifest entry with `size = 0` the
installer's only completeness test is that marker, so a finished file reports as
partial — see the trap in `HANDOFF.md`. The earlier note here, that the Q6_K GGUF
"may be truncated" at an unchanged size, was that trap being read as evidence.
Re-running the installer is still safe and is one way to restore the markers:
`curl -C -` asks for bytes past the end, the server answers 416, curl exits 33,
and the script has a branch that rewrites the marker rather than re-downloading.

**ComfyUI already lists all of them**, in the loader dropdowns the VRGDG LTX
templates actually use: `UnetLoaderGGUF.unet_name` has the Q6_K GGUF,
`DiffusionModelLoaderKJ.model_name` has the int8 convrot transformer,
`DualCLIPLoaderGGUF.clip_name1` has gemma and the text projection, and both VAEs
resolve.

**The MSR LoRA was named but never shipped.** VRGDG's own settings default
`msr_lora_name` to `licon\LTX-2.3-Licon-MSR-V1.safetensors`, and the pack
carries no download for it — so LTX Reference-to-Video was dark and nothing
said why. MSR is *Multiple Subject Reference*; the source is
`LiconStudio/LTX-2.3-Multiple-Subject-Reference`. Both V1 (VRGDG's default)
and V2 are now on disk, byte-verified, and **added to the installer manifest**
so the gap cannot reappear. The installer now tracks 14 files, all `[have]`.

Opt-in groups: `krea2` and `ernie` **fetched and rendered 2026-08-29** (~42 GB).
`minimax` still not fetched, and one of its two weight files was a failed download.

**Build routes verified rendering:** `zimage`, `flux_klein`, `krea2`,
`krea2_2pass`, `ernie_image`, plus the bundled SDXL workflow (not a VRGDG
route). Timings and the verdict on the last three: `wiki/vrgdg/routes.md`.
**Unblocked, not yet run:** every LTX route (`i2v`, `t2v`, `flf`, `rtv`,
`ingredients`, `id_lora`) and `z_upscale_enhance`. The weights are present; what
remains is selecting them once in the Builder so they land in
`VRGDG_Model_Defaults`, which is what the client reads.
**Blocked on opt-in groups:** `minimax_h3` only.

---

## General VRGDG I2V workflow generator ✅

`workflows/vrgdg-i2v-generator/` is a self-contained offline/batch exporter for
the Builder's GGUF LTX 2.3 image-to-video route. It selects one, several or all
scenes from any compatible `vrgdg_builder_session.json`, clones VRGDG's complete
installed API workflow, and carries project plus scene-level model, sampler,
LoRA, prompt, image, audio and timing settings into standalone ComfyUI JSON.

The machine fix is built in: final video decode uses `VAEDecodeTiled` at tile
256 instead of the embedded prompt's plain decoder (the visual subgraph's tile
1280 is also unsafe here). `-DisableUpscale` independently drops the measured
610 s/step second pass. The package includes an interactive launcher,
compatibility/design notes and a generated-workflow verifier. A two-scene smoke
test (scenes 2 and 4) passed, including decoder, VAE, saver, scene-index, FPS,
LoRA block and no-upscale assertions. DECISIONS #41.

Generated workflow filenames and the downstream video `base_name` now include
both the zero-padded scene number and a filesystem-safe description derived
from the scene label/story beat, so queued outputs remain identifiable outside
the Builder.

The interactive report prints every generated scene workflow under an explicit
`Generated scene workflow file(s)` heading. The base template and timing SRT are
labelled as supporting files, removing the earlier misleading report that
showed those paths but only a count for the actual deliverable.

Both scene workflows and the supporting template are pruned to the dependency
closure of the real video output before writing. This removes six unreachable
`RAMCleanup` / `VRAMCleanup` nodes that made ComfyUI reject every generated file
when the optional cleanup pack was absent. The verifier now rejects those nodes
and any dangling node reference.

---

## The image bench — every model, driven right and measured

`workflows/image-bench/` — committed 2026-08-28/29, pushed. A standalone API
graph per family, each loadable in the ComfyUI UI *and* drivable by
`comfyui_image` through a binding profile, from the same file.

| File | |
|---|---|
| `graphs.py` | six family builders + the 19-model pool, each with the recipe it wants **and where that recipe came from** |
| `run_bench.py` | resume, heavy-model flushing, per-cell seed variation |
| `run_character.py` | scores every render by ArcFace against an anchor, gated on face fraction; `--framing closeup / fullbody` |
| `enhance.py`, `faceid.py`, `controlnet_test.py`, `pose_test.py`, `sheets.py`, `character_sheets.py` | |
| `lib/shot_size.py`, `lib/text_render.py` | new measurement axes |

**Flux.1, Chroma and the FluxDAIO now run** — nothing was missing but a graph.
Both Z-Image GGUFs do not load at all. Qwen-Image 2512 added as a sixth family.

**What it measured** (full detail in `wiki/comfyui/image-recipes.md` and
`wiki/character/choosing-a-mechanism.md`):

- Klein distilled 10.6 s, Z-Image standalone 14.1 s, Qwen 24.2 s at 1664×928,
  flux1-dev 52.6 s, Chroma 226 s.
- **No model renders a character from its description** — best 0.418 against a
  ~0.70 threshold, and Qwen came eighth. The ceiling is text-to-image, not this
  pool.
- Identity hierarchy: face swap 0.77-0.79 → Klein reference 0.72 → FaceID
  0.62-0.70 → trained LoRA 0.36-0.39.
- **The bystander problem is a prompting failure.** Crowd terms in the negative
  fix it 3-for-3, free; ControlNet and pose control do not. `DECISIONS.md` #42.
- Ten of nineteen models run at cfg 1.0 and have no working negative prompt.

Downloaded and wired this session: both ControlNets, SDPose + RT-DETR, a Klein
LoRA, Qwen-Image, Krea-2, ERNIE. `controlnet/`, `model_patches/` and
`loras/flux2-klein/` are no longer empty.

**Two corrections to this session's own claims are recorded** rather than
quietly dropped: the CLIP-skip finding (ComfyUI's SDXL default already equals
-2; the "black frame" bug was mine) and the ControlNet recommendation.

**One defect to know about:** commit `95fa1c6` used `git add -A` and swept ~540
lines of a parallel session's work into a message that does not describe it —
`scripts/ui_to_api.py`, `scripts/fetch_wan_t2v.py`,
`wiki/vrgdg/scene-generation.md`, `wiki/comfyui/graph-sources.md`. Already
pushed, so left alone; the content is correct, only the attribution is wrong.

---

## Session discipline

Two skills keep this document honest. Use them.

- **`/clock-in`** (`.agents/skills/clock-in/SKILL.md`) — first action of a
  session. Reads the continuity docs, reconciles `PROGRESS.md` against git,
  checks ComfyUI, models and the baseline suite, then proposes the next step.
- **`/clock-out`** (`.agents/skills/clock-out/SKILL.md`) — last action. Runs
  tests, updates this file, `DECISIONS.md` and `HANDOFF.md`, commits, cleans up
  and names the next concrete action.

The invariant they enforce: **`PROGRESS.md` never disagrees with `git status`.**
If it does, the last session ended without clocking out and nothing here can be
trusted until reconciled.

---

## The way of working: checkpoints and one status page per film ✅ 2026-08-30

The rule is now enforced rather than intended: **a stage is finished when a
checkpoint says so, not when the files exist.** `DECISIONS.md` #43,
`wiki/practice/checkpoints.md`, WORKFLOW.md *How every step ends*.

| Built | What it does |
|---|---|
| `scripts/checkpoint.py` | write and read stage checkpoints. Loads the stage's `produces:` list from the manifest, embeds those artifacts, records what the stage left unresolved (`--open`), regenerates the status page. **Needs the repo venv** — checkpoint writing validates artifacts against their schemas. |
| `scripts/project_page.py` | generates `projects/<id>/status.html` from the project on disk. Dependency-free on purpose; runs on either Python. |
| `scripts/retime_plan.py` | maps the shot list onto the song's measured section boundaries and writes `artifacts/scene_plan.json`. Two gates, both reporting rather than editing: nothing under 1.5 s, nothing longer than the 5.06 s longest clip rendered here. |
| `lib/shot_list.py` | one parser for the markdown shot table, shared by the page and the retime. |

**Both enforcement paths verified live**, not read off the source: a gated stage
refuses `completed` without `human_approved`, and a stage refuses to advance
past incomplete predecessors.

### `the-man-watches` retrofitted

Four checkpoints written where there were none. `brief`, `casting` and `score`
are `completed --approved`, each carrying `--approved-on` naming when Raul
actually decided, because the approvals predate the record. `scene_plan` is
**`awaiting_human`** — the retime is done and waiting on him.

New canonical artifacts on disk and schema-valid: `brief.json`,
`cast_record.json`, `scene_plan.json`, plus `picks.json` (not canonical — the
machine-readable form of `plan/04-picks.md`).

**Carried forward by the checkpoints themselves**, so it travels with the film:
identity stability across seeds is not measured (findability at 60 px was);
seven shots are longer than anything this machine has rendered; the intro
doubled and verse 1 halved against the plan's clock; the production plan's
pale-coat brief is overturned by the cast and the shot list has been corrected
to match.

---

## The film reached the Builder with clips in it ✅ 2026-08-31

`The Man Watches` is **6 of 10 stages approved** and three shots are rendered,
attached and playing at the right length. The stage that took the session was
scene_look, and most of the work was finding out what the pipeline was silently
getting wrong.

### Where the film stands

| stage | |
|---|---|
| brief, casting, score, scene_plan, scene_look, export | **completed, approved** |
| render | 3 of 34 clips |
| import, dailies, post | not started |

- **34 hero stills** at 2.39:1, one per scene, in `scene_look/heroes/`.
- **Identity locked by face swap.** ArcFace against the cast reference went from
  **0.057 to 0.587** (best 0.855). Before the swap the film was 28 unrelated
  women in one costume.
- **Cuts snapped to beats**: 12 of 33 → **29 of 33**, median offset 0.00 s.
- **Clips render at their own length.** sc01 13.06 s, sc02 13.06 s, sc03 2.56 s,
  each covering its slot.
- Exported to the **Windows** Builder project `TheManWatches`: 34 segments with
  prompts, stills, cast settings, audio with 212 beat markers, lyrics and SRT.

### Built this session

| | lines | |
|---|---|---|
| `scripts/checkpoint.py` | 220 | write/read stage checkpoints; enforces the gate |
| `scripts/project_page.py` | 835 | `projects/<id>/status.html`, generated from disk |
| `scripts/heroes_page.py` | 235 | the reel: 34 stills, flagged |
| `scripts/retime_plan.py` | 449 | shot list → scene_plan, beat-snapped, camera designed |
| `scripts/hero_stills.py` | 260 | one still per scene from the plan |
| `scripts/lock_identity.py` | 188 | ReActor face swap onto the cast reference |
| `scripts/identity_check.py` | 127 | ArcFace drift measurement |
| `scripts/render_shots.py` | 339 | Wan renders, per scene, isolated, resumable |
| `scripts/audit_timing.py` | 150 | checks beat_map → song → plan → session |
| `scripts/place_character.py` | 566 | the ten-render study that found the negative-prompt fix |
| `scripts/attach_clips.py`, `sync_timing.py`, `push_stills.py`, `build_manifest.py`, `finish_shots.py`, `shoot_batch.py` | 616 | the Builder bridge in practice |
| `lib/shot_list.py` | 103 | one parser for the markdown shot table |

`lib/comfy_routing.py` gained `upload_image` and `assert_headroom`;
`assert_exclusive` is gone — see DECISIONS #43-#47.

### The machine

`.wslconfig` had `memory=96GB` on a 63.6 GiB machine. Fixed: Windows available
went from **1.7 GiB to 45.5**. `wsl --shutdown` reclaimed 26.5 GiB on the spot.

### Measured render cost, Wan 2.2 i2v at 832x352 (WSL)

| frames | clip | wall clock |
|---|---|---|
| 41 | 2.56 s | 5 min |
| 81 | 5.06 s | ~14.5 min |
| 209 | 13.06 s | 42-48 min |

Remaining 31 shots: **2,446 frames, ~6.5 h**.

---

## Next

1. **Add the duplicate-submit guard to `render_shots.py`.** Before submitting,
   check the server's queue for a prompt whose `filename_prefix` is already this
   scene. sc01 was rendered three times on 2026-08-31 - a killed runner and the
   batch both submitted it - costing ~80 min of GPU. With 31 shots left and
   runners that keep dying, this recurs. ~10 minutes of work.

2. **Then render the remaining 31 shots**, isolated per scene:
   `.venv/Scripts/python.exe scripts/render_shots.py --project the-man-watches
   --isolate --builder "C:\Users\Barrul\AppData\Local\Comfy-Desktop\ComfyUI-Shared\output\TheManWatches"`
   ~6.5 h. Resumable - re-running skips what exists. Launch it detached
   (`scripts/shoot_batch.py` via `Start-Process`), because every long runner in
   this session outlived its shell.

3. **Judge sc01/sc02 at 209 frames before committing the other five long shots.**
   Wan is trained around 81 and nothing has been checked for drift or looping at
   2.6x that. Shots 08, 09, 25, 33, 34 are the ones affected.

4. **Then step 8, Import**, and step 9, Dailies.

### Open, and needing Raul

- **Push.** 6 commits sit ahead of origin after this session.
- **sc02 renders the truck arriving**, when the shot's entire point is that it
  never does. Needs a re-render with the truck held distant.
- **sc07's face swap landed on a bystander.** ReActor takes the largest face and
  in a crowd that is often not her; `input_faces_index` is not wired.
- **No `medium` reference exists** for the cast. Those scenes render from the
  description alone, and DECISIONS #30 measured that a mismatched-framing
  reference scores worse than none.
- **The LTX upscale setting** is project-wide and lives in the Builder UI. It
  needs turning off there, or every future render hits the same wall.
- **`QUESTIONS.md` Q1–Q6 and Q8** — seven open, each with a stated assumption.
  Q7 (does LoRA training run on ROCm) is answered: yes.
- **Six of ten research families** were surveyed on the third attempt; the
  synthesis agent never completed. `wiki/character/techniques.md` is ours.

### Still true from before

- WP4 Backlot cockpit and WP5 the Lab are untouched.
- The three loop skills are written; only casting has been run.
