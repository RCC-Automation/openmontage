# PROGRESS

State of the VRGDG integration. Update this when something lands.

**Last updated:** 2026-08-24
**Branch:** `integration/comfyui-local` (fork `RCC-Automation/openmontage`, upstream `calesthio/OpenMontage`)
**HEAD:** tip of `integration/comfyui-local` — **pushed, in sync with
`origin/integration/comfyui-local`.** Deliberately not naming the tip SHA: a docs
commit invalidates its own HEAD line, and chasing it is how this file drifts.

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

## Tests

| Suite | |
|---|---|
| `test_model_registry.py` | 75 passed |
| `test_screen_test.py` | 73 passed |
| `test_vrgdg_tools.py` + `test_vrgdg_bridge.py` | 130 passed (clock-in baseline) |
| `test_vrgdg_tools.py` | 45 passed |
| `test_vrgdg_bridge.py` | 85 passed |
| `test_render_clock.py` + `test_screen_test.py` | 94 passed |
| full `tests/contracts` | **1198 passed, 8 skipped** — no failures |

Artifacts are validated against the real `schemas/artifacts/*.schema.json`, not
spot-checked — a manifest that does not validate fails much later, at
checkpoint-write time, with a far worse error.

Full `tests/contracts` now runs clean on this machine — **1198 passed, 8 skipped
in 48 s**, re-verified 2026-08-24. The ~13 `google.genai` / mermaid-CLI failures
noted previously do not appear here; expect them again on a bare environment
without those installed.

---

## Models

Required by VRGDG's LTX templates. Installer:
`…\Comfy-Desktop\_vrgdg_setup\Install-VRGDGModels.ps1` (re-running is always safe).

**All 12 are downloaded.** Verified 2026-08-24 by comparing each local file
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

Opt-in groups not fetched: `krea2`, `ernie`, `minimax` (~40 GB).

**Build routes verified rendering:** `zimage`, `flux_klein`, plus the bundled
SDXL workflow (not a VRGDG route).
**Unblocked, not yet run:** every LTX route (`i2v`, `t2v`, `flf`, `rtv`,
`ingredients`, `id_lora`) and `z_upscale_enhance`. The weights are present; what
remains is selecting them once in the Builder so they land in
`VRGDG_Model_Defaults`, which is what the client reads.
**Blocked on opt-in groups:** `krea2`, `krea2_2pass`, `ernie_image`, `minimax_h3`.

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

## Next

1. **Open the VRGDG Builder once and select the LTX models** — they save to
   `VRGDG_Model_Defaults`, which the client reads. The files are already visible
   in ComfyUI's loader dropdowns, so no restart is needed unless the Builder was
   open before they appeared. This is the only remaining prerequisite, and it
   needs a human at the machine.
2. **Live round trip** — the export half is done and cast-aware:
   `VRGDG_Project_EndToEndTest` holds the 2-scene clockwork-heroine timeline
   (sc2 is a 360° orbit) with darkBeast cast per scene at seed 7777 and a close
   reference staged. What remains: render both scenes in the Builder (GPU-hours;
   deliberately deferred) → `operation: "import"` → confirm the same scene ids
   come back. Nothing blocks it but the render time.
3. **Then `PLAN.md`**, in its order: ~~WP1 `WORKFLOW.md`~~ **done 2026-08-24**
   (plus `pipeline_defs/vrgdg-character-film.yaml`, nine stages, eight gated), WP2 the interactive casting skill, WP3 production skills and the
   `vrgdg-character-film` pipeline, WP4 Backlot as the cockpit, WP5 the ComfyUI
   Lab. L3's second half and L4 fold into WP3/WP5.

### Open work on the casting layer, in priority order

- **Every axis is now calibrated against output from this machine.**
  `look_consistency` was the last one (DECISIONS #31): band 0.58 → 0.97, measured
  from `casting/identity/` and `casting/negative/`. Four guessed bands checked,
  four found wrong. What remains unmeasured is its *sensitivity*: both
  populations differ in face and look together, so the axis has never been shown
  a render that keeps the face and drops the collar — the failure it is named
  for. That needs a population nothing on disk currently is.
- **A reference per shot family.** DECISIONS #30 shows a reference is worth ~4×
  a description on a matched shot but collapses when the framing changes. The
  screen test has no concept of an approved reference yet; adding one would let
  `full` measure identity across shot sizes, which is the real production
  question (DECISIONS #29).
- **ArcFace measures faces, nothing else.** A render can hold the face and lose
  the pink hair and brass collar. `look_consistency` is the guard for that, which
  is another reason to calibrate it rather than leave it inherited.
- **The screen test cannot use a LoRA-trained character yet.** L6 remains the
  only mechanism that holds identity independently of framing.

---

## Known gaps unrelated to the bridge

`models/controlnet`, `ipadapter`, `animatediff_models` and `frame_interpolation`
are empty while the corresponding node packs are installed. Not blocking; see
`claude/system-profile.md`.
