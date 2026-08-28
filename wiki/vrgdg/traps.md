---
title: VRGDG traps
status: measured
updated: 2026-08-28
sources: [../../HANDOFF.md, ../../DECISIONS.md]
---

Each of these cost real time on this project, and none is obvious from the
code. They are grouped by what they do to you, because the recovery differs.

---

## It silently does the wrong thing

**The visible decoder and submitted decoder can disagree.** The LTX 2.3 Music
Video Creator workflow's visual subgraph contains `VAEDecodeTiled` with a
spatial tile of 1280, but the embedded API prompt contains plain `VAEDecode`.
Changing what is visible on the canvas therefore may not change what a custom
Builder UI submits. Inspect the API prompt or the graph returned by the build
route. On this AMD host the safe final decoder is tiled at 256.

**A partial API prompt is not a reusable workflow.** An extracted scene graph
that looked complete was missing its VAE, model, CLIP, source image, audio and
saver connections. Clone the complete installed workflow or use VRGDG's build
route, then change explicit inputs. Do not rebuild it from the nodes shown in a
crash trace.

**`flux_klein` reference images go in `images`, not `image_paths`.** The key is
`images` or `image_ingredients` — a path, a newline-separated list, or
`[{"path": ...}]`. `image_paths` is the *node's* input name and is silently
ignored.

Worse: when the key is missing, VRGDG **deletes the conditioning node**
(`prompt.pop("1072")`) rather than erroring. A wrong key yields a normal
text-to-image render with no hint the reference was dropped. The tell is the
node count — 14 instead of 16.

**Template model names are not yours.** Shipped templates reference the pack
author's filenames (`qwen_3_4b.safetensors`,
`flux\flux-2-klein-4b-fp8.safetensors`). Build routes override them **from the
payload**, so always pass `unet_name` / `clip_name` / `vae_name`.
`GET /vrgdg/music_builder/model_defaults` returns the user's real choices — use
it as the base payload.

**VRGDG names models it does not ship.** The Builder's defaults set
`msr_lora_name` to a Licon MSR LoRA no VRGDG download provides, so LTX
Reference-to-Video was dark with nothing explaining why. If a mode refuses to
run, check the model its settings name exists before debugging anything else.

---

## It destroys work

**Never make the approved slot a scene's only image source.** The Builder's
render prep copies the scene's image *source* into the approved slot
(`zimage_approved/image_NNNN.png`) on every render, reading
`image_history → custom_image_path → custom_image_data → approved_image_path`
in that order — and `save_scene_image` has **no same-file guard** (the audio
copy path has one; the image path does not).

A scene whose only source is the approved slot copies the file onto itself and
dies with `[WinError 32] The process cannot access the file because it is being
used by another process` — **which survives a reboot**, because nothing external
holds the file. The export stages each still into `openmontage_stills/` and
records it as `custom_image_path` for exactly this reason; the approved slot is
VRGDG's separate copy.

**The Builder does not watch the session file.** It loads a project into memory
and shows that until the project is reopened. Export while a project is open and
the user sees a stale blank timeline — and any save from that stale UI silently
overwrites the export. **Reload after every export, before touching anything.**

---

## It cannot do what it looks like it can

**`new_project` creates folders, never a session.** The route makes the
directory skeleton and names a `session_path` it does not write; the Builder UI
writes the first session itself from its own in-memory defaults immediately
after (`newProject()` ends in `saveSession()`).

So a project created only through the route cannot be `load_session`'d, and an
export's create-then-load path fails with "Builder session was not found".
Interim: a human clicks New Project once and the export targets it via
`project_folder`. (`DECISIONS.md` #32, `QUESTIONS.md` Q3.)

**Video build routes are project-bound.** `i2v`, `t2v`, `flf`, `rtv`,
`ingredients`, `id_lora`, `minimax_h3` read a project folder from disk and need
`project_folder`, `audio_path`, `srt_path` (and `image_folder` for i2v). They
cannot be driven from parameters alone. Image routes are standalone.

**But `analyze_audio` is *not* project-bound**, despite living under
`/vrgdg/music_builder/`. It takes any folder as scratch, copies nothing, and
leaves nothing behind — which is what makes it usable as a plain beat analyzer.

**Some routes need a human at the machine.** `/vrgdg/music_builder/pick_path`
opens a native OS dialog and blocks forever; `browser_image/*` launches Chrome.
`HOST_BOUND_ROUTES` refuses them up front.

---

## It reports success wrongly

**Four error conventions.** `{ok:false}` + 400, storyboard 500, unwrapped
bodies, and `{ok:false}` with **HTTP 200** on `/update/v10/status`.
`VRGDGClient._request` normalises all of them — read the body before trusting
the status code.

**`save_session` overrides the session's `audio_path`** with a payload
top-level field on every save, and that field is also what makes VRGDG snapshot
the track into the project. Send it, or the audio silently does not land.

**Image templates end in `PreviewImage`, not a save node.** The Builder UI
persists the result separately through
`/vrgdg/workflow_runner/save_image`. Output-node resolution accepts a preview
node as a last resort for this reason. (`DECISIONS.md` #6.)

**Utility routes end in `VRGDG_ShowText`**, where the *text* is the
deliverable. Output-node resolution correctly refuses display nodes, so those
routes read the history entry directly instead — see
[lyrics-and-beats](lyrics-and-beats.md).

---

## The session itself

**~95 top-level keys, ~110 per segment, and no version field.** Never construct
one: load it, change the few keys you understand, save it back. (`DECISIONS.md`
#2, and [builder-session](builder-session.md).)
