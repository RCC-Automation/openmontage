# DECISIONS

Architectural decisions for the VRGDG integration, with the reasoning that
produced them. Read this before changing the shape of the integration — most of
these were arrived at by hitting the alternative first.

Format: context, the decision, what it costs. Numbered for reference, not
ranked. Status is `accepted` unless noted.

---

## 1. Integrate at VRGDG's build routes, not at node-ID binding profiles

*accepted — 2026-08-23*

**Context.** The first integration (branch `integration/comfyui-local`, commits
`9ba4895`…`7baad19`) drove ComfyUI by loading a graph exported from the UI and
patching it through a profile of literal node IDs:

```json
"prompt": {"node": "171", "input": "text"}
```

It worked — seven live renders proved it. But every profile is welded to one
exported file. Re-export the graph, or let the node pack update a template, and
the map silently points at the wrong nodes or fails validation.

**Decision.** Add a third graph source, `vrgdg_build`, that asks VRGDG to build
the graph. Its 17 `build_*_prompt` routes patch their own templates and return a
ready-to-queue graph. Node lookup inside VRGDG is by `class_type` with a numeric
fallback (`_api_node_id_by_class(prompt, "KSamplerSelect", fallback="123")`), so
template edits are tolerated rather than fatal.

**Cost.** A dependency on VRGDG being installed and on its route contract. Offset
by keeping the bundled and profile paths untouched, so nothing regresses if VRGDG
is absent. Thirteen model paths became reachable without writing a single new
profile.

---

## 2. The builder session is opaque: load → mutate → save, never construct

*accepted*

**Context.** `vrgdg_builder_session.json` carries ~95 top-level keys and ~110 per
segment, and has **no version field**. A future release can add, rename or
restructure any of them with no signal.

**Decision.** Only ever read a session VRGDG produced, change the small set of
keys we model, and save it back. For export, VRGDG scaffolds the project first
(`new_project`) and the bridge clones *its own* blank segment as the field
template.

**Cost.** Export cannot run without a live VRGDG to scaffold from. Worth it: a
regression test exports against the real session and asserts **zero of 108 fields
lost and zero project-level keys changed**. A hand-built segment would have
dropped whatever the installed release added, silently.

---

## 3. Identity lives outside both systems

*accepted*

**Context.** VRGDG owns `seg_<uuid>`; OpenMontage owns `scene.id`. Neither has a
field for the other's identifier.

**Decision.** Persist the pairing in `artifacts/vrgdg_scene_map.json`. An existing
pairing always wins over positional numbering.

**Cost.** One more artifact to keep in sync. It buys the property that matters:
reorder scenes in the Builder and `sc3` stays attached to the same shot instead of
becoming `sc1` and invalidating every record that points at it.

Export ids are derived rather than random — `stable_segment_id()` is a SHA-1 of
the scene id shaped like a UUID — so re-exporting the same plan produces the same
segments.

---

## 4. Assets are copied into the OpenMontage project, not referenced

*accepted*

**Context.** VRGDG writes absolute Windows paths into its session. OpenMontage
artifact paths must be project-relative.

**Decision.** On import, copy each still and clip into
`projects/<id>/assets/{images,video,audio}/` as `<scene_id>_<kind>.<ext>` and
record the relative path. Skip the copy when the target is newer than the source.

**Cost.** Disk duplication. It buys a project that stays valid when the VRGDG
project is moved or deleted, and the mtime check means a hand-edited asset is not
clobbered by a re-import.

---

## 5. Prune unreachable nodes — but only to clear a real failure

*accepted*

**Context.** The Z-Image template hangs `RAMCleanup -> VRAMCleanup` off the VAE
decode as a dead end; `PreviewImage` reads straight from the decode. ComfyUI
validates the **whole** submitted prompt, so a node pack the user lacks blocked a
render it could not possibly affect.

**Decision.** `prune_to_output()` drops branches the output does not depend on —
which is exactly how ComfyUI executes, so the artifact is unchanged. But pruning
is **conditional**: a graph that validates is submitted untouched. It runs only
after `missing_node_types()` reports a problem, and is recorded in provenance
when it does.

**Rejected alternative:** prune always. Those cleanup nodes are the template
author's deliberate intent — they free memory. Silently deleting them because it
was convenient would be a different tool than the author wrote.

---

## 6. A preview node can be the output, as a last resort

*accepted*

**Context.** The first output-node resolver excluded preview nodes on principle
and then failed on every VRGDG image template, because Z-Image, Krea-2, Flux
Klein, ERNIE and Nano Banana all terminate in `PreviewImage` — the Builder UI
persists the result afterwards through `/vrgdg/workflow_runner/save_image`.

**Decision.** Search real savers first (with a capability hint so a video graph
prefers `VHS_VideoCombine` over a stray `SaveImage`), then fall back to
`PreviewImage` / `PreviewAudio`. Comparison and display nodes
(`VRGDG_ImageCompare`, `VRGDG_VideoCompareSlider`, `VRGDG_ShowText`…) never
qualify — a side-by-side is not the deliverable. Raise rather than guess when
nothing qualifies.

Validated against all 30 shipped templates: 24 resolve. The other six are the
ClearMemory utility (no output by design), two transcribe graphs (they emit SRT),
and three UI-format files the build routes never load.

**Note.** ComfyUI reports preview artifacts under type `temp`;
`ComfyUIClient.download` already honours the per-item type, so nothing else
needed changing.

---

## 7. Provenance pins the submitted graph, not the recipe that made it

*accepted*

**Context.** The reproducibility contract was "workflow hash + model stack + seed
+ dimensions + prompt". With VRGDG building the graph, the hash of a stored
template says nothing about what ran.

**Decision.** Record the route, the template path VRGDG used, the seed it chose,
any pruned nodes and a SHA-256 of the **submitted** graph. Also infer the model
stack from the graph's loaders, since a caller-supplied stack is the exception.

**Cost.** None material. It is a strictly stronger record than a profile name.

---

## 8. Export refuses to overwrite a timeline that holds work

*accepted*

**Context.** Export replaces the segments array. A user can have hours of
hand-written prompts and approved stills in a project.

**Decision.** With no `project_folder` given, create a new VRGDG project — so a
first export can never land on existing work. When a project is named, count
segments carrying prompts, images, renders or notes and refuse if any exist.
`overwrite_timeline: true` is required to proceed, and is never the default.

---

## 9. Export writes motion *notes*, not a video prompt

*accepted*

**Context.** A segment has both `i2v_notes` (motion brief) and `i2v_prompt` (what
the video model receives). It was tempting to fill both.

**Decision.** Write `i2v_notes` from the scene's movement, camera movement, shot
intent and outgoing transition. Leave `i2v_prompt` empty for the Builder's own
prompt step, or a later OpenMontage pass, to write.

**Reasoning.** Video-model prompt phrasing is model-specific and untested here.
An empty field is honest; a fabricated one looks authoritative and is not.

The still prompt is different — `t2i_prompt` is written using the repo's existing
`lib/shot_prompt_builder.build_shot_prompt()`, with the style playbook aesthetic
as its Layer 5. That is OpenMontage's own machinery, not an invention.

---

## 10. Everything ships as registered `BaseTool` classes

*accepted*

**Context.** `AGENT_GUIDE.md` Rule Zero forbids ad-hoc scripts that call tools
directly. Separately, `BaseTool.__init_subclass__` auto-instruments `execute()`
to append events to `projects/<id>/events.jsonl` — but only when an input path
resolves under `PROJECTS_DIR`.

**Decision.** The integration is `BaseTool` subclasses in `tools/`, taking an
explicit project path. Registration is automatic — dropping the file in is the
whole act.

**Cost.** More ceremony than a script. A standalone script would be invisible to
the Backlot board and skipped by the agent, which makes it useless in practice.
`scripts/smoke_vrgdg_builder.py` and `scripts/run_comfyui_workflow.py` remain, as
diagnostics only.

---

## 11. Normalise VRGDG's error conventions in exactly one place

*accepted*

**Context.** Four conventions in one pack: `{ok:false}` with 400, storyboard
routes with 500, two `*_from_concepts/generate` routes returning the raw helper
result with no `ok` key, and `/update/v10/status` returning `{ok:false}` with HTTP
**200**.

**Decision.** `VRGDGClient._request` collapses all of them into `VRGDGError`,
reading the body before trusting the status code. A failed `/object_info` probe
counts as "node present", so a flaky check never blocks a graph that would have
run.

---

## 12. Refuse host-bound routes before calling them

*accepted*

**Context.** `/vrgdg/music_builder/pick_path` opens a native OS file dialog on
the ComfyUI host and blocks until someone clicks. `browser_image/*` launches a
debug Chrome.

**Decision.** `HOST_BOUND_ROUTES` is an explicit deny-list checked before the
request is made. An unattended run fails in milliseconds with a clear reason
instead of hanging.

---

## 13. Build the read direction before the write direction

*accepted*

**Context.** The bridge has two halves. Import cannot corrupt anything; export
replaces a timeline.

**Decision.** Ship import first. It forced path translation and the identity map
to be solved before anything could be damaged, and it is immediately useful on
its own.

---

## 14. Scaffold audio and an SRT on export

*accepted*

**Context.** VRGDG's project-bound video routes require `audio_path` and
`srt_path` even for a film with no dialogue.

**Decision.** On export, write a silent bed the length of the timeline
(`create_silent_audio`) and an SRT whose cues are the scene labels. Both are
optional via `scaffold_audio_and_srt: false`.

**Cost.** A silent WAV per project. It makes an exported project immediately
renderable instead of failing on a missing prerequisite.

---

## 15. The machine narrows, the human casts

*accepted — 2026-08-23*

**Context.** The screen test was asked for as "you decide which model we use".

**Decision.** It does not. It measures identity stability, prompt adherence,
technical quality and cost, ranks on those, and hands over a shortlist. Choosing
the look stays with the human. `ScreenTest.supports["picks_a_winner"]` is `False`
and `get_info()["decides"]` returns `"nothing"`.

**Reasoning.** Automated aesthetic judgement is weak, and a confident ranking
that pretends otherwise is worse than none — it launders a guess as a
measurement. What the machine *can* do reliably is eliminate candidates that were
never viable, which is most of the work and none of the taste.

---

## 16. Three presets, and only the quick one may run a single seed

*accepted — 2026-08-23*

**Context.** A full screen test across nine models is ~3.6 GPU-hours. Too slow
for the common question, which is just "what does each model do with my prompt?"

**Decision.** A ladder: `quick` (1 condition, 1 shared seed, ~24 min),
`shortlist` (1 condition, 3 seeds, ~73 min), `full` (3 conditions, 3 seeds).
Each preset carries the question it answers and what it cannot answer.

A single shared seed across models is the point of `quick`, not a shortcut: same
prompt, same noise, only the model differs, so the comparison is clean.

**The constraint that matters:** one seed cannot measure identity stability.
Every other preset refuses fewer than three seeds; `quick` accepts one *and*
declares the gap in its own output, so it can never hand back a ranking silently
missing its heaviest axis.

---

## 17. Sharpness is band-limited, not monotonic

*accepted — 2026-08-23*

**Context.** The first technical score rose with high-frequency energy. Testing
it against a noise image returned **1.00** — the maximum.

**Decision.** The curve peaks in the band real renders occupy and falls away
above it.

**Reasoning.** High-frequency energy keeps rising straight through the failure
modes. A garbled or noise-blasted render has *more* of it than a good one, so a
monotonic score ranks the worst output in the sweep as the crispest. Found by
looking at a rendered example rather than by reading the code — worth remembering
as an argument for actually looking at outputs.

---

## Open questions

- **Where should beat timing win?** L3 has VRGDG measure the music and snap scene
  boundaries. Unresolved: whether a beat-snapped timeline should overwrite the
  approved `scene_plan`, or be proposed back through a checkpoint. Leaning
  towards the latter — silently changing an approved artifact violates the gate
  contract.
- **LoRA training on ROCm.** VRGDG's Krea-2 Studio installs musubi-tuner and
  ai-toolkit, both CUDA-oriented. L6 may need porting or a rented GPU.
- **Upstream contribution.** Some of this is generic enough to offer to
  `calesthio/OpenMontage` — the client, output-node resolution and pruning are
  not fork-specific. The scene-plan bridge probably is.
