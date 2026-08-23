# PROGRESS

State of the VRGDG integration. Update this when something lands.

**Last updated:** 2026-08-23 (clock-out)
**Branch:** `integration/comfyui-local` (fork `RCC-Automation/openmontage`, upstream `calesthio/OpenMontage`)
**HEAD:** `1e78f71` — 2 ahead of origin, **not pushed**

---

## The plan, in six layers

| | Layer | Direction | Status |
|---|---|---|---|
| **L0** | Custom workflows via node-ID binding profiles | OM → ComfyUI | ✅ shipped (pre-existing) |
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

## Render clock + screen test ✅ built + tested, ⬜ uncommitted, ⬜ **never run live**

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
| `quick` | 9 | ~24 min | what does each model do with my prompt? |
| `shortlist` (default) | 27 | ~73 min | which models hold an identity worth testing? |
| `full` | 81 | ~218 min | which stack should this character be cast with? |

`quick` uses one condition and **one shared seed across every model**, so only the
model varies. It is the single preset allowed to run on one seed, and it prints
its own caveat because one seed cannot measure identity stability.

**Not yet verified live.** `scripts/quick_screen_test.py` was reported as failing by
the user; the error was not captured before the session ended. **Getting that error
is the first thing to do next session.**

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

## Tests

| Suite | |
|---|---|
| `test_vrgdg_tools.py` | 39 passed |
| `test_vrgdg_bridge.py` | 66 passed |
| `test_render_clock.py` + `test_screen_test.py` | 65 passed |
| combined with ComfyUI + phase0 suites | **305 passed**, no regressions |
| grand total across all VRGDG-related suites | **370 passed** |

Artifacts are validated against the real `schemas/artifacts/*.schema.json`, not
spot-checked — a manifest that does not validate fails much later, at
checkpoint-write time, with a far worse error.

Full `tests/contracts` shows ~13 unrelated failures in a bare environment, all
from `google.genai` and the mermaid CLI being absent.

---

## Models

Required by VRGDG's LTX templates. Installer:
`…\Comfy-Desktop\_vrgdg_setup\Install-VRGDGModels.ps1` (re-running is always safe).

| File | Destination | Status |
|---|---|---|
| `LTX-2.3-22B-distilled-1.1-Q6_K.gguf` | `diffusion_models\` | 19.56 GB — present, size unverified |
| `ltx-2.3-22b-dev_transformer_only_int8_convrot.safetensors` | `diffusion_models\LTX_8bit\` | 15.53 GB — present, size unverified |
| `gemma-3-12b-it-abliterated…safetensors` | `text_encoders\` | 13.15 GB — present, size unverified |
| `ltx-2.3_text_projection_bf16.safetensors` | `text_encoders\` | 2.15 GB — **exact match, complete** |
| `LTX23_video_vae_bf16` / `LTX23_audio_vae_bf16` | `vae\` | 1.35 / 0.33 GB — **exact match, complete** |
| `ltx-2.3-spatial-upscaler-x2-1.1.safetensors` | `latent_upscale_models\` | 0.92 GB — present |
| `4x-UltraSharp.pth` | `upscale_models\` | 0.06 GB — present |
| 4 LTX LoRAs | `loras\`, `loras\LTX\` | all **exact match, complete** |

Nothing was downloading at clock-out. **No `.complete` markers exist**, so the run
that fetched these predates the completeness fix. Re-run the installer once: it
asks the server whether each unverified file is whole, marks it, and resumes
anything partial. Cheap, and the only way to be sure about the five large files.

Opt-in groups not fetched: `krea2`, `ernie`, `minimax` (~40 GB).

**Build routes that run today:** `zimage`, `i2v`, `t2v`, `flf`, `flux_klein`.
**Blocked on the download:** every LTX route, `z_upscale_enhance`.
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

1. **Get the error from `python scripts\quick_screen_test.py`.** It was reported
   failing and never captured. Nothing else in the screen test is trustworthy
   until it has generated one image.
2. Re-run `Install-VRGDGModels.ps1` once to verify the five unmarked files.
3. Restart ComfyUI; select the LTX models in the Builder once (they save to
   `VRGDG_Model_Defaults`, which the client reads).
4. Commit the clock, the screen test and the continuity docs (list below).
5. **Live round trip** — plan a 2-scene film → export → render in the Builder →
   import → confirm the same scene ids come back. This is the test that proves
   the system, and nothing after it should start before it passes.
6. Then L3 (beat timing) or L4 (local post tier) — both are self-contained and can
   land in either order.

### Uncommitted at clock-out

```powershell
git add CLAUDE.md AGENTS.md PROGRESS.md DECISIONS.md HANDOFF.md IDEAS.md `
        lib/render_clock.py lib/screen_test.py tools/graphics/screen_test.py `
        tests/contracts/test_render_clock.py tests/contracts/test_screen_test.py `
        scripts/quick_screen_test.py `
        .agents/skills/clock-in .agents/skills/clock-out `
        .claude/skills/clock-in .claude/skills/clock-out `
        .claude/commands/clock-in.md .claude/commands/clock-out.md
git commit -m "feat: render clock and screen test, plus session continuity docs"
```

Explicit paths — `_to_delete/` must not enter the repo.

## Known gaps unrelated to the bridge

`models/controlnet`, `ipadapter`, `animatediff_models` and `frame_interpolation`
are empty while the corresponding node packs are installed. Not blocking; see
`claude/system-profile.md`.
