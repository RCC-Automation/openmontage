---
title: Graph sources — the three ways a graph reaches ComfyUI
status: measured
updated: 2026-08-26
sources: [../../.agents/skills/comfyui/SKILL.md, ../../DECISIONS.md, models.md]
---

A ComfyUI render is a JSON graph submitted to `POST /prompt`. In this fork a
graph can come from three places, and they are mutually exclusive per call.
The authoritative contract is `.agents/skills/comfyui/SKILL.md` — this page
is what we learned *using* each, so it can be chosen without re-reading that
file.

| source | you pass | who owns the node ids | verified here |
|---|---|---|---|
| **bundled** | `workflow_variant` (`juggernaut_xl_ragnarok`, `flux2_dev`, `auto`) | the repo — a tracked JSON + a profile in `tools/_comfyui/profiles/` | SDXL: every casting sweep, ~25 s at 832×1216 |
| **custom** | `workflow_json` / `workflow_path` + `output_node`, optionally a profile | you — a re-export from ComfyUI can change the ids and break the profile | FaceID graph (`tools/_comfyui/faceid.py`), the LoRA trainer (`lora_train.py`) |
| **VRGDG builder** | `vrgdg_build: {kind, payload}` | nobody — VRGDG patches its own template by `class_type`, so template edits do not break callers | `zimage` (162 s, darkBeast), `flux_klein` (5 s small / ~60 s portrait+reference), both live |

---

## What we know

**Bundled is the shape the SDXL recipes were authored in.** One loader, one
`KSampler`. A checkpoint's embedded sampler recipe transplants into it and into
nothing else (`DECISIONS.md` #25) — forcing one into VRGDG's two-pass zimage
schedule produced speckled artefacts.

**Custom graphs are cheap when the profile binds by name.** Profile binding
names are unrestricted (validation only checks non-empty strings), so a new
graph exposes `lora_name`, `face_reference`, `faceid_start_at` to the tools
with zero code — it is how WP7's Juggernaut workflow binds. The cost is the
ids: an API-format re-export from ComfyUI renumbers, and the profile is silently
wrong until the next `value_not_in_list`.

**VRGDG routes carry model names from the payload, not the template.** The
shipped templates name the pack author's files. Pass `unet_name` /
`clip_name` / `vae_name` every time; `GET /vrgdg/music_builder/model_defaults`
is what actually works on this machine ([models](models.md)).

**VRGDG's `flux_klein` is the strongest identity mechanism measured here** —
0.932 ArcFace on a matched-framing reference (`DECISIONS.md` #30) — and the
one route whose reference silently drops on a wrong key. The key is `images`
(or `image_ingredients`), a path, a newline list, or `[{"path": ...}]`.
`image_paths` is the *node's* input name and is ignored: VRGDG deletes the
conditioning node and returns a plain text-to-image graph with no error.
**Guard by building twice, with and without the reference, and asserting the
class types that differ** — on this machine the reference adds
`VRGDG_MultiReferenceConditioningFromPaths` and `GetImageSize`
(`scripts/masters.py` does exactly this before it renders).

**Output-node resolution is by saver class.** `VRGDG_CreateFinalVideo`,
`VHS_VideoCombine`, `SaveVideo`, `SaveAudioMP3`, `SaveImage` — preview and
comparison nodes are skipped, and a preview is accepted only as a last resort
because VRGDG's image templates end in `PreviewImage` (`DECISIONS.md` #6).
Training graphs have **no** artifact-producing output node: submit and poll
rather than `generate()`, and look for the file on disk.

**Every submitted graph is pruned to its output.** VRGDG templates hang
`RAMCleanup → VRAMCleanup` off the decode feeding nothing, and ComfyUI validates
the whole prompt — an uninstalled node on a dead branch blocks the render
(`DECISIONS.md` #5). `VRGDGGraph.prune(output_node)` removes it; `missing_node_types`
is checked before and after.

## What it costs

Timed from submission, so a busy machine corrupts the number: check
`ComfyUIClient.queue_depth()` first and decline to record when it is non-zero.
Measured, idle: SDXL bundled ~25 s at 832×1216; SDXL + FaceID ~35 s (+110 s cold
for the adapter, CLIP-vision and insightface); Z-Image ~162 s first load;
**Klein depends on the frame**: ~5 s at the Builder's 1024×576 default, but
**55–77 s at 832×1216 with a reference image** (body masters, 2026-08-26).
Quote the size with the number or the number is wrong.

## Traps

**The bridge shell cannot reach ComfyUI.** `localhost:8188` inside a Cowork
device-bridge VM is *its* localhost. Anything that renders runs from a host
terminal.

**A route that opens a native dialog hangs forever.** `pick_path`,
`browser_image/*`, `lora_dataset/pick_folder` are refused by the client up
front (`HOST_BOUND_ROUTES`).

**`list_models()` returns empty dicts when the server is down**, not an error.
`is_available()` first.

**Video routes are project-bound.** `i2v`, `t2v`, `flf`, `rtv`, `ingredients`,
`id_lora`, `minimax_h3` read a VRGDG project folder and cannot be driven from
parameters alone. Image routes are standalone.

## Open questions

- Should the tools inject a `LoraLoader` into arbitrary graphs? Today they do
  not (SKILL: "provide a workflow that already contains the LoRA loader
  chain"). WP7 binds `lora_name` through a profile instead, which is enough for
  a graph we own and nothing for a community one.

---

## ComfyUI's own blueprints are drivable from a script

`ComfyUI/blueprints/` holds ~100 official workflows — one per model family,
including `Image to Video (LTX-2.3)`, `First-Last-Frame to Video (LTX-2.3)`,
`Image Edit (Flux.2 Klein 4B)` and `Image Edit (Qwen 2511)`. They are the
authority on how each family wants to be driven.

They ship in **UI format**, which `/prompt` rejects. Normally you open one in the
browser and use Workflow → Export (API). `scripts/ui_to_api.py` does the same
headlessly, so a blueprint can be used without a human at the machine.

Two things the conversion has to get right:

**Widget names come from the server.** UI format stores widget values as a
positional list; the names live in `/object_info`. A `control_after_generate`
widget — every seed — serialises as *two* entries, so everything after a seed
shifts by one if the extra slot is not skipped.

**Newer blueprints are subgraphs.** The file contains one node whose `type` is a
UUID, with the real 40-odd node graph parked in `definitions.subgraphs`.
Converting the outer file yields an empty graph and a complaint that a UUID
class is not installed; the flattener replaces the instance with its definition.

Verified 2026-08-29: `Image to Video (LTX-2.3)` converts to 44 nodes, its
first/last-frame sibling to 32, and `Image Edit (Flux.2 Klein 4B)` to 14.

**Check the model names before running one.** A blueprint names the files its
author had. `Image to Video (LTX-2.3)` wants an all-in-one
`ltx-2.3-22b-dev-fp8.safetensors` checkpoint; this machine has the
transformer-only int8 and a GGUF, which are loaded differently — so that
blueprint needs its loader section rebuilt, not just its filenames swapped.
