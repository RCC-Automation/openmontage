# OpenMontage v2: executive spec

**Status:** DRAFT 0.1, for alignment. No code is written against it yet.
**Branch:** `v2`, cut from `integration/comfyui-local` at `27508e5`.
**Date:** 2026-10-21.
**Owner:** Raul.
**Purpose:** agree what v2 is *for* and how it is *shaped* before any detailed
spec or code. Sections 9 and 10 list the decisions this draft needs from you.

---

## 1. Why there is a v2

v1 (the `integration/comfyui-local` line, 24 Aug to 2 Sep 2026) reached its
goal. *The Man Watches* got through brief, casting, score, scene plan, scene
look and export. It has 34 hero stills, identity locked, cuts on the beat, and
clips rendered at their true length. The knowledge behind that is real:
48 decisions, a 34-page wiki, and calibrated measurements from this machine.

The code that produced it is not a system. It is a set of experiments that
happened to work once, in this order, on this machine. Measured from the tree:

| Symptom | Evidence |
|---|---|
| **The production path lives in `scripts/`, outside the architecture** | 58 fork scripts, ~15k lines. The film loop (`hero_stills` → `render_shots` → `swap_clip_faces` → `attach_clips` → `assemble_film`) is a chain of scripts. None of it is a registered tool, none of it is called by a skill, and none of it has a test. |
| **One job (submitting a graph) is done 15 ways** | `ComfyUIClient` exists. Even so, 14 files POST to `/prompt` themselves. Uploads are written 6 ways, history polling 3 ways. Every script from 30 Aug onward bypasses the client. |
| **Routing is defined 4 times** | Capability env vars, `VRGDGClient`'s fallback chain, `comfy_routing.is_wan` (a regex on the workflow name), and `shoot.py`'s `ENGINE_PLATFORM`. On top of those, 8 scripts hard-code a port. `comfyui_video` reroutes Wan jobs to WSL but never translates their paths. |
| **5 overlapping "shoot" orchestrators** | `shoot.py`, `shoot_batch.py`→`render_shots.py`, `finish_shots.py`, the PowerShell `vrgdg-i2v-generator`, and `comfyui_video` + export. |
| **Writes bypass the contracts** | `sync_timing` and `attach_clips` write the Builder session file directly, which DECISIONS #2 forbids. `retime_plan` and `build_manifest` rewrite `artifacts/*.json` with no schema check. `required_artifacts_in` is declared in 14 manifests and read by no code. |
| **Production imports from a bench folder** | `hero_stills` and `place_character` use `sys.path.insert` to reach `workflows/image-bench/graphs.py`, which in practice is the production image-graph library. |
| **One machine and one film are baked in** | `C:\Users\Barrul\…`, `/home/barrul`, `--project the-man-watches` in ~18 usage strings, and memory peaks pinned as constants. Film-specific scripts (`song_takes`, `look_round`, …) are referenced but not in git. |
| **Research and production are mixed** | #39 (face swap over LoRA) and #48 (identity on the footage) made the LoRA/FaceID/dataset stack research-only (~4k lines). It still sits beside production code with the same status. 2 lib modules are imported nowhere, and ~28 scripts are referenced by nothing. |
| **The docs contradict each other** | 7 root docs (~4.9k lines) plus a 5.7k-line wiki, with ~12 contradictions between them: identity thresholds 0.35/0.45/0.70, "9 steps" vs "10", stale traps in HANDOFF, `--disable-mmap` both on and off. |
| **Behind upstream** | The fork carries an old snapshot of upstream. `lib/checkpoint.py`, `base_tool.py` and the selectors have since received fixes upstream. |

**The diagnosis in one sentence.** The *plan* (PLAN.md: ten gated steps,
skills, a cockpit) and the *practice* (scripts run by hand on two servers)
diverged after 30 Aug. Every hard lesson since then was learned in the
practice, and none of it reached the plan.

**What is NOT garbage, and carries forward** (≈400 tests between them):
- `lib/vrgdg_bridge.py` and `tools/_comfyui/vrgdg.py` (pure session↔artifact converters, a stable scene map, normalised errors)
- `tools/video/vrgdg_project_sync.py`
- `lib/model_registry.py`
- `lib/screen_test.py`, `lib/render_clock.py`, `lib/casting_loop.py`, `lib/loop_session.py`
- `lib/face_identity.py`
- `tools/_comfyui/faceswap.py`
- `ComfyUIClient` and workflow profiles
- the `song`, `beat_map` and `cast_record` schemas
- DECISIONS and the wiki, as *knowledge*

v2 is a **consolidation, not a rewrite from zero**.

---

## 2. The goal: what you have been asking for

These are taken from your own words across the docs.

> "I need a real workflow where I can identify the steps that are executed
> with OpenMontage, and I can influence them, with reviews and the
> possibility for modifications. And a more interactive workflow with the
> Agent: the Agent does the required work — defining the perfect character,
> trying multiple seeds, multiple prompts, multiple LoRAs, multiple models."
> (PLAN.md)

> "The human stops being a courier between two apps." (HANDOFF §1)

> "Where are you using OpenMontage for all this?" (DECISIONS #33)

> "She is not she." (DECISIONS #48)

**v2 north star:**

> You describe a music video. The agent takes it through ten visible, gated
> steps. At the four loops (casting, score, scene look, dailies) it does the
> exploring, and you pick by eye and ear. Every render is submitted once,
> survives a crash, lands in the film's record with its provenance, and is
> measured against the cast. The film can be resumed, re-shot one scene at a
> time, and replayed, by you or by a fresh agent session, without anyone
> reading a chat transcript.

**Done for v2.0:** one complete short film made end to end on v2, with:
- no script outside the registered tools
- no hand edits to JSON
- no duplicate GPU submits
- every stage closed by a checkpoint
- a re-shoot of one scene from dailies that touches nothing else

---

## 3. Principles

The first six are inherited and still valid. The last four are new, and each
is the lesson of a v1 failure.

1. **The agent decides; Python executes.** Skills hold the judgement, and
   tools are registered `BaseTool`s. Artifacts are schema-validated.
   Checkpoints are the only save points. (Constitution, #10, #43)
2. **The machine narrows, the human picks.** Every score is input to your
   decision, never the decision. (#15, #40)
3. **Calibrated on this machine, or marked NOT CALIBRATED.** Four guessed
   constants were checked here, and all four were wrong. (#27, #37)
4. **Measure the thing you claim, on the artifact that ships.** Stills passed
   identity while the footage failed. (#37, #48)
5. **VRGDG's session is opaque.** Load it, mutate known keys, save it, and
   only through the client. (#2)
6. **Model identity comes from the file header, and the recipe comes with
   the model.** (#18, #24, #25)
7. **One way to do each thing.** One transport, one router, one graph
   library, one path resolver, one job runner. Every new duplicate gets
   rejected in review.
8. **The machine is configuration, not code.** Servers, platforms, ports,
   paths, memory budgets and measured peaks live in one machine profile.
   No user names or film names appear in code.
9. **A GPU job is a durable record, not a process.** A job is submitted once
   under an idempotency key and reattached after a crash. Its result is
   recorded whether or not the shell that launched it is still alive. (The
   sc01 triple render cost ~80 GPU-minutes.)
10. **Production and research are separate.** The lab may be messy. The
    production path may import nothing from it. A lab result becomes
    production by promotion: a recipe in the registry, or a decision.

---

## 4. Target architecture: seven layers

Each layer may call only the layer below it.

```
 L6  Surfaces      status page / Backlot cockpit · VRGDG Builder (optional view & edit)
 L5  Workflow      pipeline manifest (10 steps) · production skills · the 4 loops
 L4  Operations    BaseTools: render_still, render_shot, swap_identity, retime_clip,
                   beatmap, lyric_align, vrgdg_export/import, assemble, measure_*
 L3  Film record   project store: artifacts (validated), checkpoints, shot ledger
                   (takes), loop sessions, provenance; the ONLY writer to disk
 L2  Instruments   model registry, recipes, graph library, measurements
                   (ArcFace, CLIP, technical, beat adherence), render clock
 L1  Execution     one ComfyUI transport · one router · one durable job runner
 L0  Machine       machine profile: servers, platforms, paths, memory, measured peaks
```

**L0 Machine profile.** One file per machine, with nothing in code. It holds:
- the servers (Windows :8188 for LTX, stills, VRGDG and face swap; WSL :8189 for Wan)
- which engine runs on which server, and why (measured)
- path translation rules between the two platforms
- the RAM budget (63.6 GiB is the real one; reported VRAM is not)
- per-job measured peaks

It replaces `machine_paths`, `paths`, the models-root settings, `ENGINE_PLATFORM`,
`PEAK_GIB` and the hard-coded ports.

**L1 Execution.**
- **The transport** is `ComfyUIClient`. It owns submit, wait, upload,
  download and `/free`, and it is the only code that talks HTTP to ComfyUI.
  `VRGDGClient` sits on top of it.
- **The router** chooses the server from the engine (registry), not from a
  regex on a file name. It translates paths and checks memory headroom
  before admitting a job.
- **The job runner** is the one genuinely new component. It keeps a
  persistent ledger of jobs with these fields:
  - key = film + scene + take + graph hash
  - state, prompt id, server
  - outputs and timing

  It submits only if the key is not already queued or done, and it reattaches
  after a crash. It honours a stop request. It scales timeouts with the work
  and runs detached from any shell. It replaces the five shoot orchestrators.
  It decides nothing about the film: it executes jobs the agent enqueued.

**L2 Instruments.**
- **One graph library** with three graph sources: template + profile,
  Python builder, and VRGDG build route. It replaces `workflows/image-bench/graphs.py`, the inline graphs in
  scripts, and the duplicate FaceID builders.
- **The model registry and recipes** carry over as they are.
- **The measurements** become one `measure` package with each axis's
  calibration status attached.

**L3 Film record.** One project store, and the only thing that writes under
`projects/<id>/`. Every write is validated against its schema. It adds what
v1 lacked:
- a **shot ledger**: scene → takes → the chosen take, with each take's job,
  graph hash, measurements and verdict (IDEAS 2.2)
- enforcement of `required_artifacts_in` (Q5)

The Builder session is written only through the VRGDG client.

**L4 Operations.** Every step of the film that v1 did with a script becomes
a registered tool with a contract and a test. The mapping is in §6. A tool
enqueues jobs on L1 and records results in L3. It does not loop, does not
wait for hours, and does not decide.

**L5 Workflow.** The ten-step manifest and skills from PLAN/WORKFLOW,
corrected to match what practice taught:
- the render step is agent-driven (Wan/LTX through the runner), not "you
  press render in the Builder"
- **7b Identity** (face swap on the footage, strength by shot size) is a
  first-class step
- long shots are rendered as one native pass and then stretched

**L6 Surfaces.**
- The status page (exists) grows into the Backlot cockpit (PLAN WP4).
  Actions are written as request files that the agent consumes.
- The VRGDG Builder becomes *one* surface, used where it is the best tool,
  not the hub everything must pass through (see decision D1).

---

## 5. The ten steps, as v2 runs them

| # | Step | Kind | Operation(s) in v2 | Gate |
|---|---|---|---|---|
| 1 | Brief | conversation | — | approve |
| 2 | Casting | **loop** | `screen_test`, measure | pick → `cast_record` |
| 3 | Score | **loop** | music gen, `beatmap`, `lyric_align` | listen → `song` + `beat_map` |
| 4 | Scene plan | agent | retime to beats (#44, #45) | approve |
| 5 | Scene look | **loop** | `render_still` (cast + reference per shot family), measure | pick → hero still per scene |
| 6 | Render | agent + runner | `render_shot` per scene, engine from the plan | auto, with clips visible |
| 7 | Identity | agent, measured | `swap_identity` on footage; keep only if the score improves (#48) | auto |
| 8 | Dailies | **loop** | measure every take against plan and cast; flag | keep / re-shoot scene N |
| 9 | Assemble | agent | `retime_clip`, `assemble` to the song | approve the cut |
| 10 | Post | agent | grade, grain, finish | approve |

VRGDG export and import are not steps. They are optional operations that run
when you want to review or edit in the Builder (D1).

---

## 6. What happens to v1's code

| v1 | v2 |
|---|---|
| bridge, vrgdg client, project sync, registry, screen test, render clock, casting loop, loop session, face identity, faceswap, schemas | **port** with their tests; split the god-files (`comfyui_video` 1273, `vrgdg_bridge` 1155 lines) along the layers |
| `hero_stills`, `render_shots`, `shoot*`, `finish_shots`, `collect_render`, `lock_identity`, `swap_clip_faces`, `stretch_clip`, `attach_clips`, `sync_timing`, `push_stills`, `retime_plan`, `audit_timing`, `assemble_film`, `build_manifest`, `checkpoint`, `project_page` | **re-specify as operations** (L4) or record-store functions (L3); the knowledge in them is kept and the code is not |
| `workflows/image-bench/`, `bench_*`, `ltx_*`, `test_wan_capabilities`, `place_character`, `seed_probe`, `compare_seed_modes` | **lab/**: research, runnable, outside the production import graph |
| LoRA/FaceID/dataset stack (`train_lora*`, `build_dataset*`, `dataset_*`, `caption_dataset`, `calibrate_faceid`, `rejection_dataset`, `lora_train`) | **lab/**, frozen (#39); revisit only if Q8 reopens |
| `render_realism`, `text_render`, unreferenced scripts | **drop** (they stay in git history on `integration/comfyui-local`) |
| `vrgdg-i2v-generator` PowerShell | **drop** once `render_shot` covers it, or keep as a lab export tool (D1) |
| clock-in/out duplicated in 3 places | one copy |

---

## 7. Documentation in v2

v1 has seven continuity docs that overlap and drift. v2 has four, each with
one job:

| Doc | Job | Rule |
|---|---|---|
| `specs/v2/` | what we are building | changed by decision, not by session |
| `DECISIONS.md` | why, one entry per choice | v1's 48 are condensed to the ~30 that still hold; superseded ones are marked |
| `wiki/` | what we measured and know | contradictions fixed on migration; one canonical number per fact |
| `STATUS.md` | where we are | short; anything that can be generated from git and the project store is generated |

PLAN, PROGRESS, HANDOFF, WORKFLOW, IDEAS and QUESTIONS are folded into these.
Open questions become a section of STATUS.

---

## 8. Out of scope for v2.0

- Lip sync (decided 2026-08-24).
- LoRA training in the production path (#39). It stays in the lab.
- The ComfyUI Lab as a product (PLAN WP5). v2 makes it *possible* (one graph
  library and one runner) but does not build it.
- Ingredients, reference-to-video and ID-LoRA video modes (WP2c). They wait
  until the base path is solid.
- Multi-user use, cloud GPUs, CUDA portability. v2 targets this machine
  through its profile, without hard-coding it.

---

## 9. Decisions needed from you

Each has a recommendation. These decide the shape of the detailed specs.

**D1. What is the VRGDG Builder's role?**
In practice it moved from *the render hub* to *a place clips get attached
to*. The LTX upscale pass (610 s/step) and the faster Wan path in WSL took
rendering out of it.
*Recommendation:* OpenMontage owns the record and the render. VRGDG is used
for what is uniquely its own:
- its build routes
- `analyze_audio`
- lyric alignment
- the Builder as an optional review and edit surface, kept in sync by
  export and import

**D2. What is v2 based on?**
The fork lags upstream.
*Recommendation:* start v2 from current upstream `main`, then port the
keepers listed in §6 onto it. The alternative is to keep consolidating
inside this branch. That is cheaper now, but it keeps the old upstream
snapshot.

**D3. Is a durable job runner acceptable?**
It is a long-lived Python process. That bends the "no Python orchestrator"
rule. *Recommendation:* yes, on one condition: it runs jobs and never
decides stages. v1 proved that a 6.5-hour shoot cannot depend on a shell
staying alive.

**D4. Which video engines are first-class in v2.0?**
*Recommendation:* Wan 2.2 i2v (WSL) as the default, and LTX (Windows) as
the second engine. Both go behind `render_shot` and are chosen per scene in
the plan.

**D5. What is the proving film?**
*Recommendation:* finish *The Man Watches* on v2. It has 31 shots left, and
its artifacts already exist. That makes it a migration test as well as a
production. The alternative is a new 60–90 s short, which is cleaner but
proves less.

**D6. What happens to research code?**
*Recommendation:* move it to `lab/`, outside the production import graph.
Promote results only as recipes or decisions.

**D7. Is the cockpit in v2.0?**
*Recommendation:* no. v2.0 ships the generated status page plus the request
queue. Backlot as the full cockpit is v2.1, once the record (L3) is
trustworthy.

---

## 10. Next specs, once this one is agreed

1. `01-machine-and-execution.md`: the machine profile, transport, router and job runner (L0–L1), including the job ledger format.
2. `02-film-record.md`: the project store, shot ledger, schemas and checkpoint enforcement (L3).
3. `03-instruments.md`: the graph library, registry, recipes and measurement axes with their calibration status (L2).
4. `04-operations.md`: one contract per operation tool (L4), derived from the v1 scripts.
5. `05-workflow.md`: the ten steps, the skills, the four loops, the gates and the re-shoot path (L5).
6. `06-migration.md`: what is ported, in what order, and how v1 artifacts are carried over.
7. `07-knowledge.md`: the doc consolidation and the wiki contradiction list.

No code before 01–05 are agreed.
