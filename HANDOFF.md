# HANDOFF

Everything a new session needs to continue the VRGDG integration without
rediscovering it. Read this first, then `PROGRESS.md` for state and
`DECISIONS.md` for why things are shaped the way they are.

Last updated: 2026-08-23.

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

Verified live: a Z-Image render through `build_zimage_prompt` completed in 162 s
with correct seed, output node and provenance.

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

**`screen_test` has never generated an image.** Its logic is covered by 41 tests
and the VRGDG plumbing under it is proven, but the tool itself has not completed
a live run. `scripts/quick_screen_test.py` was reported failing and the error was
not captured. Treat the first live run as debugging, not production.

**The bridge shell cannot reach ComfyUI.** It is an isolated Linux VM with folders
mounted, so `localhost:8188` is *its* localhost, not the Windows host's. Anything
needing a real render has to be run by the human in a host terminal. The same
isolation blocks model downloads (no network egress).

**The session has no version field.** ~95 top-level keys, ~110 per segment. Never
construct one. See DECISIONS.md #2.

---

## 7. Immediate next steps

1. **Finish the models.** Re-run `Install-VRGDGModels.ps1` once after the current
   run; it verifies the two large files fetched before the completeness fix.
2. **Restart ComfyUI**, open the VRGDG Builder once and select the LTX models.
   They save to `VRGDG_Model_Defaults`, which is what the client reads.
3. **Commit Layer 2** (see PROGRESS.md for the exact file list).
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
