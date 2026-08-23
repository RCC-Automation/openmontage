# PROGRESS

State of the VRGDG integration. Update this when something lands.

**Last updated:** 2026-08-23
**Branch:** `integration/comfyui-local` (fork `RCC-Automation/openmontage`, upstream `calesthio/OpenMontage`)
**HEAD:** `730facd` — in sync with origin

---

## The plan, in six layers

| | Layer | Direction | Status |
|---|---|---|---|
| **L0** | Custom workflows via node-ID binding profiles | OM → ComfyUI | ✅ shipped (pre-existing); SDXL checkpoint now swappable |
| **L1** | VRGDG as the graph builder | OM → VRGDG | ✅ **committed** `cd915f0`, verified live |
| **L2** | `scene_plan` ⇄ builder session | both | ✅ **committed** `1e78f71`, not yet run live |
| **L3** | Audio-first timing (beats → scene boundaries) | VRGDG → OM | ⬜ not started |
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

## Model registry + SDXL binding ✅ built + tested + verified live, ⬜ uncommitted

The screen test picked candidates with a substring blacklist over filenames. It
missed `ace_step_*` (the rule said `acestep`), so two audio models, a
segmentation network and an SDXL refiner were queued as image candidates — and
19 of the 20 would have failed anyway, because only the `zimage` route can be
pointed at an arbitrary model.

| File | |
|---|---|
| `lib/model_registry.py` | header-based identification, driver mapping, name resolution, run-outcome learning |
| `tests/contracts/test_model_registry.py` | 52 tests, fixtures built from real tensor signatures |
| `tools/_comfyui/profiles/juggernaut-xl-ragnarok-txt2img.json` | + `checkpoint_name` binding |
| `tools/graphics/comfyui_image.py` | `checkpoint_name` input, provenance retargeted to the checkpoint that ran |
| `tools/graphics/screen_test.py` | per-candidate routing, per-family encoder/VAE, unmeasured renders declared |
| `tools/_comfyui/client.py` | `_history_entry` timeout 10 s → 60 s |
| `scripts/quick_screen_test.py` | registry-driven candidate list, no global encoder/VAE |

**What it does.** Reads each file's safetensors header (a few hundred KB, no GPU,
works with ComfyUI down) and GGUF `general.architecture`. Records what the file
is, the evidence, which graph source can drive it, and what happened when it ran.
Persisted to `var/model_registry.json` (gitignored), keyed by a header
fingerprint so a swapped file is re-judged. Failures demote a model with the
error kept; successes confirm and time it.

**The tree, as classified — 31 files, 13 eligible, 0 unknown, 18 excluded:**

| family | n | driver |
|---|---|---|
| Z-Image | 5 | VRGDG `zimage` |
| SDXL | 7 | bundled `juggernaut-xl-ragnarok-txt2img` |
| FLUX.2 Klein | 1 | VRGDG `flux_klein` |
| Wan / ACE-Step / LTX / SAM / refiner | 14 | excluded, each with a stated reason |
| Flux.1 + Chroma | 3 | excluded — need a dual-CLIP graph no template has |
| GGUF (Z-Image, LTX) | 3 | excluded — need `*LoaderGGUF`, templates use `UNETLoader` |
| `minimax_h3_…` | 1 | excluded — **127 KB, a failed download** |

Two of the five Z-Image models (`moodyRealMix_ZIT_V7Global`,
`darkBeast30BF16INT8_dbzit9DIMRclaw`) carry nothing in their names that would
identify them. No name-based rule finds those.

**All three image paths verified live**, same brief:

| path | model | |
|---|---|---|
| VRGDG `zimage` | zImageTurbo_turbo | 41 s |
| bundled workflow | juggernautXL_ragnarok | 35 s |
| VRGDG `flux_klein` | flux-2-klein-4b-fp8 | 5 s |

**Bugs the live runs surfaced**, all fixed: ACE-Step read as video (bundle
unwrapping discarded the vocoder); unmeasured routes costed at zero without
saying so; a 10 s `/history` timeout killing any slow first load; transient
failures permanently demoting models; one global VAE forced on every family
(16-channel decoder, 128-channel latent, dying inside `VAEDecode`); template
filenames not matching installed ones. See DECISIONS.md #18-21.

---

## Tests

| Suite | |
|---|---|
| `test_model_registry.py` | 52 passed |
| `test_vrgdg_tools.py` | 39 passed |
| `test_vrgdg_bridge.py` | 66 passed |
| `test_render_clock.py` + `test_screen_test.py` | 65 passed |
| full `tests/contracts` | **1118 passed, 7 skipped** — no failures |

Artifacts are validated against the real `schemas/artifacts/*.schema.json`, not
spot-checked — a manifest that does not validate fails much later, at
checkpoint-write time, with a far worse error.

Full `tests/contracts` now runs clean on this machine (7 skips). The ~13
`google.genai` / mermaid-CLI failures noted previously do not appear here; expect
them again on a bare environment without those installed.

---

## Models

Required by VRGDG's LTX templates. Installer:
`…\Comfy-Desktop\_vrgdg_setup\Install-VRGDGModels.ps1` (re-running is always safe).

| File | Destination | Status |
|---|---|---|
| `LTX-2.3-22B-distilled-1.1-Q6_K.gguf` | `diffusion_models\` | 19.56 GB — **complete** |
| `ltx-2.3-22b-dev_transformer_only_int8_convrot.safetensors` | `diffusion_models\LTX_8bit\` | 19.5 GB so far — **partial, resumes** |
| `gemma-3-12b-it-abliterated…safetensors` | `text_encoders\` | 13.15 GB — **partial, resumes** |
| `ltx-2.3_text_projection_bf16.safetensors` | `text_encoders\` | 2.15 GB — **exact match, complete** |
| `LTX23_video_vae_bf16` / `LTX23_audio_vae_bf16` | `vae\` | 1.35 / 0.33 GB — **exact match, complete** |
| `ltx-2.3-spatial-upscaler-x2-1.1.safetensors` | `latent_upscale_models\` | 0.93 GB — **partial, resumes** |
| `4x-UltraSharp.pth` | `upscale_models\` | 0.06 GB — **partial, resumes** |
| 4 LTX LoRAs | `loras\`, `loras\LTX\` | all **exact match, complete** |

Verified by `Install-VRGDGModels.ps1 -Preview` on 2026-08-23: 8 of 12 complete,
**4 still partial** (both 22B LTX weights, the spatial upscaler, 4x-UltraSharp).
The int8 transformer grew 15.53 → 19.5 GB since the previous session, so a
download did run after that clock-out. Re-run the installer to resume; 911 GB
free, so space is not the constraint.

Opt-in groups not fetched: `krea2`, `ernie`, `minimax` (~40 GB).

**Build routes verified rendering today:** `zimage`, `flux_klein`, plus the
bundled SDXL workflow (not a VRGDG route).
**Blocked on the download:** every LTX route (`i2v`, `t2v`, `flf`, `rtv`,
`ingredients`, `id_lora`), `z_upscale_enhance`.
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

1. **Run the 13-model `quick` screen test** (~8-10 min). Every render teaches
   both the registry and the render clock, and this is the first sweep that can
   actually compare across families.
2. Re-run `Install-VRGDGModels.ps1` to finish the four partial files. Until the
   two 22B weights land, every LTX route stays dark.
3. Restart ComfyUI; select the LTX models in the Builder once (they save to
   `VRGDG_Model_Defaults`, which the client reads).
4. **Live round trip** — plan a 2-scene film → export → render in the Builder →
   import → confirm the same scene ids come back. This is the test that proves
   the system, and nothing after it should start before it passes.
5. Then L3 (beat timing) or L4 (local post tier) — both are self-contained and can
   land in either order.

### Known gaps in the screen test

Two axes of the ranking cannot be computed on this machine: `identity_stability`
(weight 0.45) and `prompt_adherence` (0.25) both need CLIP, and `torch` /
`transformers` are absent from the repo's Python (ComfyUI's ROCm torch lives in
its own embedded interpreter). The ranking correctly reweights around them, but
`shortlist` and `full` exist *for* identity stability — until CLIP is installed
they measure only sharpness and speed.

The `technical` axis is also mis-calibrated: its band assumes a Laplacian
variance of 0.020-0.060 and a real render measures **0.0029**, so every genuine
image scores in the bottom few percent and the axis cannot discriminate. Worth
recalibrating against the renders now on disk.

## Known gaps unrelated to the bridge

`models/controlnet`, `ipadapter`, `animatediff_models` and `frame_interpolation`
are empty while the corresponding node packs are installed. Not blocking; see
`claude/system-profile.md`.
