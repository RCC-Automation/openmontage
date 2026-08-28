# QUESTIONS

Open questions raised while building, parked here rather than guessed at.

Each one records what was blocked, what was assumed to keep going, and what
changes if the assumption is wrong. **Nothing here stopped the work** — every
entry has a working assumption behind it. The point of the file is that the
assumptions are visible and reversible instead of buried in code.

Answer them in a Q&A pass; each answered question either confirms the
assumption (delete the entry, note it in `DECISIONS.md` if it was interesting)
or names the change.

**Status key:** `open` — needs Raul. `assumed` — building on a stated guess.
`answered` — resolved, kept here until the change lands.

---

<!-- Add entries at the top. Newest first. -->

### Q8. Is a Kohya-trained LoRA worth the toolchain, now that the swap works?

**Status:** open
**Raised:** 2026-08-28, after four LoRA attempts topped out at 0.37 identity
**Blocks:** nothing today. The face swap delivers 0.80 and is in production use.

**The situation.** ComfyUI's native trainer takes a `MODEL` input only - the
saved LoRA has 3268 UNet keys and zero text-encoder keys - so the trigger token
can never learn to mean her (`DECISIONS.md` #39). Kohya trains both, which is
the one concrete reason to expect a materially better result.

Against it: Kohya is not installed, assumes CUDA, and this is an AMD gfx1151
box with no Triton or xformers. `bitsandbytes` and `AdamW8bit` do work here
(HANDOFF), which unblocks the kohya *family*, but nothing has been run.

**What I assumed to keep going.** That the swap is sufficient. It is, for
stills and for the shots in `BurningManGirl`.

**What changes if the answer is different.** A working LoRA removes the swap
step, survives small faces and profiles where the swap needs a detectable face,
and makes the character portable to any prompt without a reference image. That
is a real convenience upgrade, not a capability the project currently lacks.

**Recommendation:** leave it until a shot actually needs it - a close profile,
or a scene where the face is too small to swap but must still read as her.
Then the cost is justified by a specific failure rather than by tidiness.

---


### Q7. Does LoRA training run on this ROCm machine at all?

**Status:** answered — **yes.** 2026-08-26, `scripts/train_lora_smoke.py`:
200 steps, rank 16, LR 5e-4, bf16, AdamW, 10 images at 832×1216, native
`TrainLoraNode` against `juggernautXL_ragnarok` — **498.7 s (2.49 s/step)**,
a 102.5 MB `.safetensors` that `LoraLoader` accepts, and a same-seed gate
render at **0.428** ArcFace to the anchor against **0.219** without it.
Kept here until WP7 7.1 lands; the measurement is on
`wiki/character/lora-training.md`.
**Raised:** 2026-08-26, planning WP7 (three engines, three LoRAs)
**Blocks:** every LoRA in WP7, and therefore the whole point of building a
character dataset. Nothing in the plan is worth a GPU-hour until this is known.

**The situation.** A full day went into dataset construction - anchor sweeps,
FaceID calibration, a rejection-sampling variant, a ladder - and not one
LoRA has ever been trained here. The wiki page saying training works
(`character/lora-training.md`) is `researched`, not `measured`. This is an
AMD gfx1151 box with no Triton, no xformers, no SageAttention; every training
recipe in circulation assumes CUDA.

What is known: `TrainLoraNode` and `LoraSave` are present; `bitsandbytes`
0.50.1 loads with a ROCm backend and `AdamW8bit` steps with real uint8 state
(HANDOFF section 2, verified 2026-08-25); `juggernautXL_ragnarok` is on disk in
trainable precision. So an SDXL LoRA *can be attempted* with no downloads.
Whether it completes, how long a step takes, and whether the saved file loads
back into `LoraLoader` are all unmeasured.

**What I assumed to keep going.** That it works. WP7 is written on that
assumption, with 7.0 - a throwaway LoRA on ~10 images already on disk - as
the first step precisely so the assumption is checked before anything else.

**What changes if the answer is different.** WP7 collapses to its 7.1 and 7.2
halves: the three workflows still exist and are still agent-callable, but
identity comes from reference conditioning at generation time (FaceID for
SDXL, multi-reference for Klein, prompt only for Z-Image) instead of from a
LoRA. That path works today and is measured in
`wiki/character/faceid-on-this-machine.md`; its cost is the plastic skin at
the strengths that hold identity, and no adapter at all for Z-Image.

**Recommendation:** run 7.0 next session, first thing, with
`TORCH_ROCM_AOTRITON_ENABLE_EXPERIMENTAL=1` set in the training process's own
environment (it is untested for training and this is where it might matter).
Gate: the file loads, and a same-seed render with the LoRA measures closer to
the anchor than one without.

---

### Q6. Should a casting round free VRAM between models?

**Status:** open
**Raised:** 2026-08-25, running casting round 2
**Blocks:** rounds with more than a handful of models. Round 2 took the backend
down and had to be split.

**The situation.** Round 2 asked for four models across three seeds - twelve
renders, four full model loads, three of them Z-Image UNets. ComfyUI ran out of
memory, and then **the OOM recovery crashed the process**:

```
[ERROR] Got an OOM, unloading all loaded models.
Fatal Python error: Aborted
  comfy/model_patcher.py:1156 in unpatch_model
  comfy/model_management.py:2048 in unload_all_models
```

Freeing memory tried to move tensors off the device, that allocation failed
too, and Python aborted. So the failure mode is not a failed render - it is a
dead backend, mid-round, with every result lost. On this machine that costs
about twenty minutes and a restart the agent cannot perform.

VRGDG ships a route for exactly this: `build_clear_memory_prompt`, described in
its own registry as "graph that unloads models and frees VRAM". `screen_test`
does not call it between candidates.

**What I assumed to keep going.** Nothing automatic. The runner now warns above
nine renders in one round, and reports a dead backend honestly instead of
"no candidate produced a single image" - which said nothing about the real
cause. Rounds get split by hand.

**What changes if the answer is different.** Queue `clear_memory` between
candidates in `screen_test`, probably behind a flag defaulted on for
mixed-family matrices. Two costs to weigh: it adds a graph submission per
candidate, and - more importantly - **it may corrupt the render clock's
learning**, since timings are measured from submission and an unload between
models changes what a "typical" load costs. That interacts with the existing
trap about busy-machine timings, so it needs measuring rather than assuming.

**Recommendation:** add it, on by default when a round spans more than one
model *family*, and record in the run outcome that a cleanup ran so the render
clock can keep those samples separate.

---


### Q5. Should `required_artifacts_in` be enforced, or is it documentation?

**Status:** open
**Raised:** 2026-08-24, walking `score-poc` through the checkpoint gates
**Blocks:** nothing today. It makes one guarantee weaker than it reads.

**The situation.** `write_checkpoint` enforces two things and they both work -
verified live this session:

- **the gate**: a stage with `human_approval_default: true` cannot be written
  `completed` without `human_approved=True`. Refused correctly.
- **stage order**: `score` could not advance while `brief` and `casting` were
  incomplete. Refused correctly.

It does **not** enforce `required_artifacts_in`. A `scene_plan` checkpoint
completes happily with no `beat_map` anywhere in the project - which is exactly
the failure that moving Score before the scene plan was meant to make
impossible. The declaration reads like a guarantee and is a comment.

This is not specific to this pipeline. `required_artifacts_in` appears in the
manifest schema and in **all 14 manifests**, and is read by no code anywhere -
only by a test written today. Every pipeline in the repo has the same gap.

**What I assumed to keep going.** Left the behaviour alone. Enforcing it
touches shared machinery under 13 other pipelines that have been running
against the looser contract, and a change that silently starts refusing
checkpoints mid-production is worse than the gap it closes.
`test_vrgdg_character_film_pipeline` covers the safe half - that no stage
*declares* an input no earlier stage produces - so the manifest at least cannot
be internally inconsistent.

**What changes if the answer is different.** `_enforce_stage_prerequisites`
already walks prior checkpoints for stage completeness; it would additionally
collect the artifacts they carry and check the required set against them.
Maybe 25 lines. The risk is entirely in the other 13 pipelines: any of them
that produces an artifact in one stage and does not carry it forward into
later checkpoints would start failing. Worth a dry-run pass over every
manifest before switching it on.

**Recommendation:** enforce it, but behind a per-manifest opt-in
(`enforce_artifact_prerequisites: true`) so `vrgdg-character-film` gets the
guarantee now and the others move over one at a time.

---


### Q4. Does a lyric cue map work in the Builder without `singer_id`?

**Status:** open
**Raised:** 2026-08-24, building `apply_song_to_session` in `lib/vrgdg_bridge.py`
**Blocks:** whether a named singer actually reaches the Builder's UI. The lyrics
themselves land either way.

**The situation.** VRGDG's cue map identifies a singer two ways -
`singer_name` (a string) and `singer_id` (a reference into
`flux_reference_builder`, the same subject records the casting export writes
for reference images). The Builder's own normalizer resolves a performer by
`singer_id` first, falls back to matching `singer_name` case-insensitively,
and finally falls back to position.

Two further conditions it imposes: cue-map mode only takes effect when the
segment has **two or more performer subjects selected**, and the subjects come
from `selectedPerformerSubjectsForSegment`. We write neither the subjects nor
the ids - only names.

So the name fallback *should* find a performer whose subject name matches the
cast character. Whether it does in practice, and whether a segment with no
selected performers silently discards the cue map, needs someone looking at
the Builder with a two-singer song loaded.

**What I assumed to keep going.** Write `singer_name` and leave `singer_id`
empty. The names come straight from the song's `singer` field, which the
schema already requires to match a cast character. `lyric_text` and
`lyric_section` do not depend on any of this and land regardless, so the
worst case is that per-line singer attribution is ignored rather than lost.

**What changes if the answer is different.** If ids are required: the export
has to write `flux_reference_builder` subjects for each cast character and
select them per segment before writing cues. That is the same subject
machinery casting already uses (DECISIONS #32), so it is wiring rather than
new mechanism - perhaps 60 lines in `apply_casting_to_session`, plus deciding
what happens when a song names a singer the cast record does not have.

---

### Q3. How does a score-stage export get a Builder session to write into?

**Status:** open
**Raised:** 2026-08-24, running the lyric export POC
**Blocks:** the live lyric export. The mapping itself is proven against the
real session in memory.

**The situation.** The known bootstrap trap (DECISIONS #32, HANDOFF): VRGDG's
`new_project` route makes folders and names a `session_path` it never writes -
the Builder UI writes the first session itself. So a project created through
the route alone cannot be loaded, and any export that creates its own target
fails with "Builder session was not found".

For the round trip this was worked around by hand: a human clicked New Project
once and the export targeted it. That is fine for one film. It is not fine for
a score loop that wants to try three songs against the same timeline, and it
is not fine for the cockpit (WP4), where a button cannot ask a human to click
a different button first.

**What I assumed to keep going.** The lyric export was verified against the
**real 86 KB session loaded from disk and mutated in memory, never saved** - 4
lines out, 4 back, identical, and only `segments` and
`show_timeline_lyric_notes` touched at project level. That proves the mapping
without needing a new project. The live write still needs a human-created
project.

**What changes if the answer is different.** Three candidates, in increasing
order of how much they depend on VRGDG: (a) copy an existing session as a
template and rewrite its identity fields - works today, but constructs a
session, which DECISIONS #2 forbids for good reasons; (b) drive
`save_project_as` from a loaded project, which makes VRGDG author the new
session; (c) ask upstream for a route that writes the first session. (b) looks
closest to the existing rules and is worth probing first.

---


### Q2. Should a cast record's reference paths be project-relative?

**Status:** assumed
**Raised:** 2026-08-24, writing `schemas/artifacts/cast_record.schema.json`
**Blocks:** nothing

**The situation.** The real cast record on disk carries an absolute Windows
path for its reference image, pointing into `projects/screen-tests/`. Every
other artifact in the system is project-relative by contract - the
`asset_manifest` schema says so in as many words. `cast_record` had no schema
at all until today, so nothing ever checked it, and the export happily
consumes the absolute path.

It also has two shapes: `screen_test.cast_record()` writes `reference` (one
string, no shot family), while the record actually in use has `references` (a
dict keyed close_up / medium / wide). DECISIONS #30 measured that one
reference per shot family is what holds identity, so the plural is right and
the singular is legacy.

**What I assumed to keep going.** The schema accepts both shapes and both path
kinds, documents `reference` as legacy, and does not enforce relative paths.
Tightening it would have broken the one working export on the machine.

**What changes if the answer is different.** If references should be
project-relative: the casting stage has to copy the chosen reference into
`projects/<id>/assets/references/`, `screen_test.cast_record()` changes to
write the relative path and the plural key, and the export's resolution drops
its absolute-path branch. Perhaps 40 lines across three files, plus the
question of what happens to `projects/screen-tests/` as a shared pool.

---

### Q1. What are the real bands for beat-grid confidence?

**Status:** assumed
**Raised:** 2026-08-24, writing `tools/analysis/audio_beatmap.py`
**Blocks:** nothing - the axis ships marked NOT CALIBRATED

**The situation.** `beat_map.confidence` says whether a grid can be hard-cut
to. A beat tracker always returns *something*; on calm music that something is
a metronome it imposed, and cutting to it looks wrong with nothing reporting
why. So the grid is judged on whether its own intervals are steady.

Two constants decide it: how far an interval may sit from the median
(`_INTERVAL_TOLERANCE = 0.15`) and what share must be within it
(`_ON_GRID_SHARE = 0.85`). Both are guesses. DECISIONS #27 and #31: four
guessed bands have been checked against real output on this machine and all
four were wrong - one by an order of magnitude, one in the quiet way where it
scored everything 0.80-0.90 and read as agreement.

The one real track measured so far lands at **0.833 - just under the 0.85
threshold**, so it is called weak by a margin of one interval. A verdict that
close to the line is not a measurement.

**What I assumed to keep going.** Both constants as above, set so the failure
is a wrong "weak" rather than a wrong "strong" - a weak verdict costs pacing
by phrase, a wrong strong verdict costs every cut in the film. Marked NOT
CALIBRATED in the source.

**What changes if the answer is different.** Only the two constants, but the
population needed to set them does not exist yet: a handful of tracks that are
genuinely rhythmic and a handful that genuinely are not, both measured here.
Generating them is a Lab job (WP5) and cheap - ACE-Step makes a 9-second track
in 30 s. Until then any film cut to a "strong" grid should be spot-checked by
ear at one cut.

---


## Template

```
### Q<n>. <the question in one line>

**Status:** open | assumed | answered
**Raised:** <date>, building <WP / file>
**Blocks:** <what cannot be finished until this is answered, or "nothing">

**The situation.** What was found, in plain words.

**What I assumed to keep going.** The choice made, and why it is the safest
default rather than the best one.

**What changes if the answer is different.** Concretely — which files, how big.
```
