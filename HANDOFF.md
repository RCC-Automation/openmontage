# HANDOFF

Everything a new session needs to continue the VRGDG integration without
rediscovering it. Read this first, then `PROGRESS.md` for state and
`DECISIONS.md` for why things are shaped the way they are.

Last updated: 2026-08-24.

---

## 1. What this is

Two systems that each solve half of AI film production, joined at a seam.

**OpenMontage** (this repo) is a governance engine that happens to make video:
gated pipeline stages, checkpoints, decision logs, provenance, cost tracking,
multi-provider fallback. The agent *is* the orchestrator — there is no runtime
Python orchestrator. It cannot render a frame by itself.

**VRGDG** (`comfyui-vrgamedevgirl`, 210 nodes, 241 HTTP routes) is a production
cockpit living inside ComfyUI: beat and tempo analysis, a scene timeline, graph
construction, face repair, colour, stitching, LoRA training. It has no opinion
about story and keeps no reproducibility record.

Read down the capability columns and they barely overlap. That is why the
integration is worth building rather than extending one tool.

**The goal:** you describe a film; OpenMontage plans it; the plan opens in VRGDG's
Builder as a timeline with prompts already written; you make the creative
judgements by eye; everything you approve flows back as a tracked, reproducible
record. The human stops being a courier between two apps.

---

## 2. The machine

| | |
|---|---|
| Host | Windows, device `desktop-gfe43h0` |
| GPU | **AMD Radeon 8060S** (`gfx1151`, Strix Halo iGPU) |
| VRAM | ~90 GB reported — unified memory, not dedicated |
| RAM | 64 GB |
| Stack | **ROCm 7.14**, PyTorch 2.12.0+rocm7.14.0, Python 3.13.12 |
| Attention | pytorch attention. `comfy_kitchen` HIP backend available (fp8/int8/w4a4/AWQ kernels). **Triton and SageAttention are not available** |

**This is not a CUDA box.** Anything needing Triton, SageAttention, xformers,
bitsandbytes or CUDA-only kernels will fail or silently fall back. Capacity is
not the constraint; memory bandwidth is. Prefer fp8, GGUF and int8-convrot
weights — the last of these matches the HIP kernels directly.

---

## 3. Paths

```
Repo             C:\Users\Barrul\Documents\Github\openmontage
ComfyUI root     C:\Users\Barrul\AppData\Local\Comfy-Desktop
  install        …\ComfyUI-Installs\ComfyUI\ComfyUI          (ComfyUI 0.32.0)
  node pack      …\custom_nodes\comfyui-vrgamedevgirl        (v9.1.1)
  API templates  …\comfyui-vrgamedevgirl\Workflows\UsedForUIDoNotTouch\  (30 files)
  models         …\ComfyUI-Shared\models                     (~310 GB, SHARED tree)
  VRGDG projects …\ComfyUI-Shared\output\VRGDG_Project_<timestamp>\
  model defaults …\ComfyUI-Shared\output\VRGDG_Model_Defaults\model_defaults.json
Installer        …\Comfy-Desktop\_vrgdg_setup\Install-VRGDGModels.ps1
```

Models are in the **shared** tree, not under the ComfyUI install. There is no
`extra_model_paths.yaml`; ComfyUI Desktop handles it natively.

`.env` must contain `COMFYUI_SERVER_URL=http://localhost:8188`. Generation works
without it on the default, but `make preflight` reports the provider as
unconfigured.

---

## 4. Running things

```powershell
cd $env:USERPROFILE\Documents\Github\openmontage

# tests
python -m pytest tests/contracts -q                       # full contract suite
python -m pytest tests/contracts/test_vrgdg_tools.py -q   # VRGDG client + graph mode
python -m pytest tests/contracts/test_vrgdg_bridge.py -q  # scene_plan <-> session bridge

# live smoke: build a graph through VRGDG and render it
python scripts\smoke_vrgdg_builder.py
```

`make test` and `make preflight` exist but assume the venv layout; the direct
`python -m pytest` calls above are what has actually been run here.

**Models:** re-running `Install-VRGDGModels.ps1` is always safe. It resumes
partial files, skips completed ones, and self-heals files fetched before the
completeness fix. `-Preview` lists without downloading. `-Groups all` adds
Krea-2, ERNIE and MiniMax-H3.

---

## 5. What is built

Three things, all additive — no existing behaviour changed.

**`tools/_comfyui/vrgdg.py` (677 lines)** — `VRGDGClient`, `VRGDGGraph`, a
registry of VRGDG's 17 `build_*_prompt` routes, output-node resolution, dead-branch
pruning, and a missing-node preflight.

**`vrgdg_build` on `comfyui_image` / `comfyui_video`** — a third graph source
beside bundled workflows and `workflow_json`. VRGDG patches its own template and
returns a ready-to-queue graph, so there are no node-ID maps to maintain.

**`lib/vrgdg_bridge.py` (572) + `tools/video/vrgdg_project_sync.py` (512)** — the
two-way bridge between a `scene_plan` and a VRGDG builder session.

**`lib/model_registry.py`** — what every model file on the machine actually is,
read from its header, and which graph source can drive it. Persisted to
`var/model_registry.json` (gitignored) and corrected by what happens when a model
runs. This is what the screen test uses to pick candidates.

**`lib/face_identity.py`** — ArcFace identity via InsightFace `buffalo_l`: detect,
align to canonical landmarks, embed. Answers "is this the same person", which CLIP
cannot. CPU through onnxruntime, ~0.3 s per image. Calibrated against measured
populations, see DECISIONS.md #28.

Verified live: a Z-Image render through `build_zimage_prompt` completed in 162 s
with correct seed, output node and provenance. All three image graph paths have
since rendered from `screen_test`: VRGDG `zimage` (41 s), the bundled SDXL
workflow (35 s) and VRGDG `flux_klein` (5 s).

---

## 6. Traps

Each of these cost real time. None are obvious from the code.

**Git through the Cowork device bridge.** That shell cannot delete files, so
every `git` call leaves `.git/index.lock` and blocks the next one. `git add` and
`git commit` also strand ref locks and `tmp_obj_*` files. **Run git in a real
terminal on the host.**

**No network egress from the device bridge shell.** Outbound CONNECT returns 403.
Model downloads must run on the host. It also cannot reach ComfyUI on
`localhost:8188` — the bridge shell is an isolated Linux VM with folders mounted,
not the Windows host.

**VRGDG image templates end in `PreviewImage`, not a save node.** The Builder UI
persists the result separately through `/vrgdg/workflow_runner/save_image`.
Output-node resolution therefore accepts a preview node as a last resort. See
DECISIONS.md #6.

**VRGDG templates carry dead branches.** The Z-Image template hangs
`RAMCleanup -> VRAMCleanup` off the VAE decode feeding nothing, and ComfyUI
validates the *whole* submitted prompt — so an uninstalled node pack on a branch
that cannot affect the output still blocks the render. See DECISIONS.md #5.

**Template model names are not yours.** Shipped templates reference the pack
author's filenames (`qwen_3_4b.safetensors`, `flux\flux-2-klein-4b-fp8.safetensors`).
The build routes override them **from the payload**, so always pass
`unet_name` / `clip_name` / `vae_name`. `GET /vrgdg/music_builder/model_defaults`
returns the user's real choices — use it as the base payload.

**Video build routes are project-bound.** `i2v`, `t2v`, `flf`, `rtv`,
`ingredients`, `id_lora`, `minimax_h3` read a VRGDG project folder and need
`project_folder`, `audio_path`, `srt_path` (and `image_folder` for i2v). They
cannot be driven from parameters alone. Image routes are standalone.

**Some routes need a human at the machine.** `/vrgdg/music_builder/pick_path`
opens a native OS dialog and blocks forever; `browser_image/*` launches Chrome.
`HOST_BOUND_ROUTES` in `vrgdg.py` refuses them up front.

**VRGDG has four error conventions.** `{ok:false}`+400, storyboard 500, unwrapped
bodies, and `{ok:false}` with HTTP **200** on `/update/v10/status`.
`VRGDGClient._request` normalises all of them; read the body before trusting the
status code.

**Slash commands only exist in Claude Code.** `/clock-in` and `/clock-out` are
`.claude/commands/*.md` in this repo, so they work when Claude Code runs *in this
folder*. In a Cowork session there is no slash command — say "clock out" and the
agent follows `.agents/skills/clock-out/SKILL.md` directly.

**A checkpoint that looks broken may just be mis-driven.** Distilled checkpoints
(names carrying DMD, LCM, Turbo, Lightning) are trained for CFG ~1 and ~10 steps.
Run one at CFG 4.5 for 35 steps and it returns saturated, posterised garbage that
reads as a corrupt model. Two of the installed checkpoints were written off that
way for a whole session. Many merges embed the graph they were made with in
`__metadata__.prompt`; `lib/model_registry.infer_sampler_recipe` reads it. Six of
the installed checkpoints carry one. See DECISIONS.md #24.

**A recipe only transplants into a graph of the same shape.** The bundled SDXL
workflow is CheckpointLoader into one KSampler, which is what those settings were
authored in, so they apply. VRGDG's zimage route is a two-pass flow-match
schedule and they do not — forcing `gonzalomoZpop_v40`'s own settings into it
produced speckled artefacts. `DRIVERS[...]["accepts_recipe"]` gates this;
`use_embedded_recipe` takes `auto` / `always` / `never`. DECISIONS.md #25.

**`flux_klein` reference images go in `images`, not `image_paths`.** The key is
`images` or `image_ingredients` — a path, a newline-separated list, or
`[{"path": ...}]`. `image_paths` is the *node's* input name and is silently
ignored. Worse, when the key is missing VRGDG deletes the conditioning node
(`prompt.pop("1072")`) rather than erroring, so a wrong key yields a normal
text-to-image render with no hint the reference was dropped. Symptom: the built
graph has 14 nodes instead of 16.

**Never store anything derived from code in the ledger.** The registry cached
each family's driver alongside the model. After `DRIVERS` changed from fixed
encoder names to resolved candidates, every scan reported the files unchanged and
so never refreshed the snapshots — and a filename this machine has never had went
to ComfyUI for three consecutive sweeps. Testing the resolver in isolation passed
the whole time, because that reads from code. DECISIONS.md #22.

**Timings are measured from submission, so a busy machine corrupts them.** Start
a sweep while the Builder is rendering and the first image is recorded as taking
as long as the video. `ComfyUIClient.queue_depth()` is checked before each render;
a non-zero depth keeps the image and discards the timing. Unknown depth is
treated as busy — losing a clean sample only slows learning, keeping a dirty one
corrupts it silently.

**`test_image_selector_no_provider` used to render for real.** It asserts the
*no provider* path degrades gracefully, but with a provider configured it
performed a real 26-second render, littered the repo root, and — because ComfyUI
runs one job at a time — blocked the whole contract suite behind whatever else
was queued. Now skipped when a provider is available. If another contract test
starts hanging, suspect the same shape.

**A guessed rescaling band has been wrong every time it was checked.** Four of
them now, all measured against real renders, all wrong — one by an order of
magnitude, and the last one (`look_consistency`) in the quieter way: it scored
every real candidate 0.80-0.90, which reads as agreement rather than as a broken
axis. If you add a metric, calibrate it against output from this machine or mark
it NOT CALIBRATED with the population it needs. DECISIONS.md #27 and #31.

**A fixed seed is reproducibility, not character consistency.** Same model +
prompt + seed reproduces byte-identically, which is why sweeps pin 7777. But hold
the seed and change the prompt and the face drifts *more* (0.47) than holding the
prompt and changing the seed (0.66). The description carries the identity, not the
noise. DECISIONS.md #29.

**Never trust a model's filename.** `moodyRealMix_ZIT_V7Global` and
`darkBeast30BF16INT8_dbzit9DIMRclaw` are Z-Image UNets; `gonzalomoXLFluxPony_v30FluxDAIO`
is a Flux.1 bundle; `ace_step_1.5_turbo_aio` is audio. Use `lib/model_registry.py`,
which reads the safetensors header, rather than matching on names. See
DECISIONS.md #18.

**There is no single encoder or VAE for a mixed sweep.** Z-Image decodes a
16-channel latent through `ae.safetensors`; Flux.2 decodes 128 channels through
`flux2-vae.safetensors`. Forcing one on the other fails inside `VAEDecode`
*minutes into the render*, with a channel-count error that names neither model.
The registry carries per-family candidates and resolves them against the server.
See DECISIONS.md #20.

**ComfyUI's HTTP server stalls while loading weights.** It serves HTTP from the
process reading the model off disk, so a large first load can block a request for
tens of seconds. `_history_entry` used a 10-second timeout and turned any slow
first load into a failed render; it is now 60. If you add a request on the
generation path, budget for the stall.

**`list_models()` returns empty dicts when the server is down**, not an error.
A caller that treats "no models" as "nothing installed" will be wrong and quiet.
Check `is_available()` first.

**`VRGDGClient.unavailable_reason()` always returns text**, whether or not the
client is available — it is only meaningful once `is_available()` is `False`.
Printing both makes a healthy server look broken.

**The bridge shell cannot reach ComfyUI.** It is an isolated Linux VM with folders
mounted, so `localhost:8188` is *its* localhost, not the Windows host's. Anything
needing a real render has to be run by the human in a host terminal. The same
isolation blocks model downloads (no network egress).

**The session has no version field.** ~95 top-level keys, ~110 per segment. Never
construct one. See DECISIONS.md #2.

---

## 7. Immediate next steps

1. **Re-run `Install-VRGDGModels.ps1`** — **five** files are still partial,
   including both 22B LTX weights and the gemma text encoder. Every LTX route
   stays dark until they complete. (The branch is pushed and in sync with origin.)
2. **Restart ComfyUI**, open the VRGDG Builder once and select the LTX models.
   They save to `VRGDG_Model_Defaults`, which is what the client reads.
3. **Calibrate `look_consistency`** — the last uncalibrated band. The data is
   already on disk: `projects/screen-tests/casting/identity/` (one character
   across seeds) and `casting/negative/` (a different character).
4. **The live round trip** — the test that proves the whole thing:
   plan a 2-scene film → `operation: "export"` → open in the Builder → render both
   scenes by hand → `operation: "import"` → confirm the manifest and cut come back
   with the same scene ids.

---

## 8. Where the rest of the context lives

The full analysis — VRGDG's route inventory, the session schema, the six-layer
integration design, and the system profile of this machine — is in the attached
Claude project **ComfyUI-OpenMontage-VRGDG**:

- `claude/system-profile.md` — hardware, install layout, every model, the gaps
- `claude/openmontage-vrgdg-integration.md` — the six-layer design and risks
- `claude/vrgdg-builder-implementation.md` — Layer 1 as built
- `claude/vrgdg-bridge-layer2.md` — Layer 2 as built

Published summary: https://claude.ai/code/artifact/176435e7-5ad5-4bdc-8d57-5eb6c2beb668
