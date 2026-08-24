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

## 9. Export writes motion *notes*, not a video prompt — **revised by #33**

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

## 18. Model identity is read from the file, never from its name

*accepted — 2026-08-23*

**Context.** The screen test filtered candidates with a substring blacklist over
filenames. It skipped `"acestep"` while the files are named `ace_step_*`, so two
audio models were queued as image candidates alongside a segmentation network
and an SDXL refiner.

**Decision.** Identity comes from the `.safetensors` header — a JSON map of every
tensor name, readable in a few hundred KB with no GPU and with ComfyUI down.
GGUF files are read through their `general.architecture` key. Filenames are
never consulted.

**Reasoning.** A blacklist is wrong in both directions and silent about it.
`moodyRealMix_ZIT_V7Global` and `darkBeast30BF16INT8_dbzit9DIMRclaw` are
Z-Image UNets that no name rule would have found; `gonzalomoXLFluxPony_v30FluxDAIO`
is a Flux.1 bundle despite naming two other architectures. Tensor prefixes are
unambiguous: `cap_embedder` is Z-Image, `double_stream_modulation` is Flux.2,
`vector_in` + `double_blocks` is Flux.1, `detokenizer` is audio.

**Consequence worth knowing:** modality must be judged on the *whole* file before
an all-in-one bundle is unwrapped. ACE-Step keeps its vocoder under `vae.`, so
stripping to the diffusion model first discards the only proof it is audio and
its inner attention blocks then read as video. That bug shipped and was caught by
a live scan.

---

## 19. The registry records why a model is unusable, and asks when it cannot tell

*accepted — 2026-08-23*

**Context.** A filter that drops a model leaves no trace. The next person sees
eleven candidates where there are twenty-nine files and cannot tell whether the
rest are broken, unsupported, or simply missed.

**Decision.** Eligibility is three-state — eligible, excluded, unknown. Excluded
entries carry the specific reason ("Flux.1 needs a dual-CLIP graph; no VRGDG
template has one"), not a bare `false`. Unknown means the header did not settle
it; those are surfaced once, and a human verdict is sticky until the file itself
changes.

**Reasoning.** This mirrors what the render clock already does with unmeasured
routes (#15, and the clock's refusal to invent a number). The machine narrows and
explains; it does not decide quietly.

---

## 20. Encoder and VAE are resolved against the server, not copied from the template

*accepted — 2026-08-23*

**Context.** The first mixed-family sweep died inside `VAEDecode`:
`expected input[1, 128, 36, 64] to have 16 channels`. The screen test passed one
global VAE (`ae.safetensors`, Z-Image's 16-channel) and Flux.2 produces a
128-channel latent. Fixing that surfaced the next layer — the driver named
`qwen_3_4b.safetensors` and `flux\flux2-vae.safetensors`, straight from VRGDG's
templates, and this machine has `qwen3_4b_fp8_scaled.safetensors` and a flat
`flux2-vae.safetensors`.

**Decision.** Each family declares *candidate lists* for its encoder and VAE,
resolved against `list_models()` before a graph is built. Matching widens in
three steps: exact, then ignoring punctuation and case, then allowing the
candidate to be a prefix of a longer installed name. No match resolves to `""`
and the candidate is refused up front.

**Reasoning.** HANDOFF has warned since Layer 1 that template model names are the
pack author's, not yours — this is that trap reaching the screen test. There is
no single right encoder once a sweep mixes families, so a global default is
wrong by construction. Failing at submission beats failing inside `VAEDecode`
several minutes into a render.

---

## 21. A render failure demotes a model only when it is about the model

*accepted — 2026-08-23*

**Context.** Flux.2 Klein was marked permanently ineligible by its first run. The
error was a 10-second read timeout while ComfyUI loaded 3.8 GB of weights — the
model was fine, the HTTP call was not.

**Decision.** Failures matching transient markers (timeout, connection refused,
reset by peer) are recorded but never demote. Only a real load or execution
failure moves a model to ineligible.

**Reasoning.** The learning loop is what keeps the registry honest, so it has to
be right about *what* it learned. Demoting on infrastructure noise would shrink
the usable set every time the machine was busy, and the shrinkage would look like
knowledge. The underlying timeout was raised to 60 s: ComfyUI serves HTTP from
the same process that loads weights, so a tight timeout turns a slow first load
into a failed render for any large model.

---

## 22. Cached derived state is a second source of truth, and it rots

*accepted — 2026-08-24*

**Context.** Three attempts at a 12-model sweep failed identically: every
Z-Image model rejected with `clip_name: 'qwen_3_4b.safetensors' not in [...]`, a
filename this machine has never had. The registry was caching a snapshot of each
family's driver in its ledger. Those snapshots were written while `DRIVERS` still
carried a hardcoded encoder name; after the switch to candidates resolved against
the server, every scan reported the files unchanged and so never refreshed them.
Testing the resolver in isolation passed, because that reads `DRIVERS` from code.

**Decision.** Derive the driver from code at read time. Never store it.

**Reasoning.** A persisted copy of something computed from code cannot signal
that it is stale. This is the same mistake twice in one change — a run-outcome
demotion also outlived the driver that produced it. The driver-signature
mechanism added for that (#23) could not help here, because the cached driver
*was* the stale thing. Not caching is the stronger fix and should have been the
first reach.

---

## 23. A verdict earned under one driver expires when the driver changes

*accepted — 2026-08-24*

**Context.** A sweep that ran before encoder names were resolved failed every
Z-Image model on validation and demoted all five permanently. Fixing the driver
left the verdicts behind: the registry could not distinguish "this model is
broken" from "we asked for it wrongly, once".

**Decision.** A run-outcome demotion stamps a hash of the family's driver plus a
resolver version. On scan, a demotion whose signature no longer matches is
discarded and eligibility re-derived from the header. Human verdicts are exempt —
they are about intent, not mechanism.

**Also:** transient failures never demote at all. A read timeout while ComfyUI
loads 4 GB of weights is a fact about the machine, and demoting on it would
shrink the usable set every time the box was busy — shrinkage that would look
like knowledge.

---

## 24. Drive each checkpoint at the settings it was built with

*accepted — 2026-08-24*

**Context.** Two checkpoints came out of the sweep as saturated, posterised
garbage and read as broken models. They were not. Both are distilled, and both
say so in their own metadata: `gonzalomoXLFluxPony_v60PhotoXLDMD` was merged at
10 steps / CFG 1.0 / lcm / karras, `mopMixtureOfPerverts_v71` at 11 / 1.0 / lcm.
The bundled workflow imposed 35 steps / CFG 4.5 / dpmpp_2m_sde on every SDXL
checkpoint alike.

**Decision.** Read the ComfyUI graph many merges embed in `__metadata__.prompt`,
take the base pass, and use it. Six of the installed checkpoints carry one.

**Result.** Sharpness 0.07 → 0.45 and 0.00 → 0.39, and 35 s → 10 s per render,
since 10 steps is what they were built for. The two "broken" models are now the
fastest good models on the machine.

**Cost.** Honouring per-model settings breaks the sweep's premise that only the
model varies, so the run reports `sampler_recipes_used` and the runner prints
which candidates were driven at their own settings. Holding *wrong* settings
constant only measures our ability to mis-drive a model.

---

## 25. A recipe describes the graph it came from

*accepted — 2026-08-24*

**Context.** Having made #24 work for the bundled SDXL path, the obvious next
step was to apply recipes to the VRGDG routes too. `gonzalomoZpop_v40` states 9
steps / res_multistep / beta. Driving VRGDG's zimage template that way produced
speckled artefacts through the hair and blotchy skin — visibly worse than the
template's own dpmpp_sde at 10 steps.

**Decision.** Recipes travel only into a graph of the shape they came from. The
bundled SDXL workflow is that shape — CheckpointLoader into one KSampler — so
`DRIVERS["sdxl"]` carries `accepts_recipe`. VRGDG's zimage route is a two-pass
flow-match schedule and does not. `use_embedded_recipe` takes `auto` (trust the
driver), `always` (force it, for experiments) or `never`.

**The second lesson, and the sharper one.** That artefacted render scored
**0.428** against the same model's 0.066 when clean — its best score of the
session — because speckle is high-frequency and the sharpness axis rewarded it.
Which led directly to #26.

---

## 26. Detail is a gate on broken renders, not a measure of quality

*accepted — 2026-08-24*

**Context.** The sharpness score twice ranked exactly opposite to the person
looking at the images. It placed the two renders the human chose 11th and 12th of
twelve, because both have large deliberately out-of-focus backgrounds and the
metric averaged the whole frame — so bokeh, a virtue in portraiture, read as
blur. Then it gave an artefacted render the top score of the day.

**Decision.** Two changes. Measure the sharpest tiles (8×8 grid, 90th percentile)
rather than the whole frame, so the reading comes from whatever is in focus. Then
stop ranking: anything inside the band real renders occupy scores 1.0, and the
axis only speaks up for output that is blank, blurred or noise-blasted.

**Calibrated, not guessed.** Eleven real renders from this machine: eight good
ones, soft and crisp alike, fall between 0.0040 and 0.0137; two colour-blown and
one artefacted sit between 0.0436 and 0.0612. An order of magnitude clear, no
overlap. All eight good renders now score 1.00 and all three broken ones 0.00.

**Reasoning.** A soft filmic portrait and a crisp editorial one are both correct,
and which you want is a casting decision, not a measurement (#15). Scoring them
against each other put a machine's opinion above the human's on precisely the
question reserved for the human.

---

## 27. Guessed constants have been wrong every time they were checked

*accepted — 2026-08-24*

**Context.** Three rescaling bands in this codebase were written without data
behind them. All three were checked this session against real renders. All three
were wrong.

| band | assumed | measured | effect |
|---|---|---|---|
| sharpness | 0.020–0.060 whole-frame | 0.0040–0.0137 on subject tiles | buried the chosen renders |
| prompt adherence | 0.15–0.35 cosine | 0.293–0.388 | 13 of 15 saturated at 1.00 |
| face identity | 0.20–0.65 (guessed) | 0.21–0.70 (measured) | nearly right, by luck |

**Decision.** A band ships either calibrated against real output, or explicitly
marked NOT CALIBRATED with the population it still needs. No silent constants.

**Cost.** Calibration is cheap — a handful of renders and a percentile — and the
alternative is a metric that looks like it works. The prompt-adherence band was
so far off that it returned 1.00 for a colour-blown failure and for the best
render alike, while appearing perfectly healthy.

---

## 28. Two identity measures, because they see different things

*accepted — 2026-08-24*

**Context.** The headline axis asked "does this stack hold one character" and
answered with whole-image CLIP similarity, which cannot separate two different
women in matching pink hair under matching light — exactly the population a
casting sweep is full of.

**Decision.** Add ArcFace (InsightFace `buffalo_l`) as `identity_stability`, and
keep the CLIP measure under a name that says what it sees, `look_consistency`.
The 0.45 the identity question was worth splits 0.30 face / 0.15 look.

    ArcFace   the face.        Ignores hair colour, wardrobe, grade.
    CLIP      everything else. Cannot tell two similar faces apart.

A brief like "pink hair and a brass filigree collar" needs both: a render can
keep the face and lose the character.

**A render with no detectable face scores None, not zero.** A wide shot or a back
view is missing data, not a drifting character, and zero would punish a stack for
a framing the sweep itself asked for.

**Calibration, and the mistake in it.** The first negative population was twelve
models rendering the same brief. They looked like different people and appeared
to overlap the positives — median 0.293, max 0.606. But twelve renderings of one
description are not twelve different people; they are twelve attempts at the same
one, and using them would have put the floor near 0.3 and scored a perfectly
consistent model as drifting. A real negative needs a different character:
rendering a lighthouse keeper gave 0.100–0.210, against 0.359–0.667 for one
character across seeds. No overlap.

---

## 29. The seed is not the character; the description is

*accepted — 2026-08-24*

**Context.** A reasonable intuition, and worth recording because it is wrong:
hold the seed fixed and vary the prompt to keep one character across shots.

**Measured on darkBeast30, face cosine:**

| held fixed | varied | result |
|---|---|---|
| prompt | seed (×3) | **0.66** — one person |
| seed 7777 | prompt (close-up/medium/wide) | **0.47** — drifts |
| — | — | 0.10–0.21 = different people |

**Reasoning.** The seed is only the starting noise. Change the prompt and that
noise is steered somewhere else entirely, so a fixed seed anchors nothing. What
the model reads the face from is the description. A fixed seed does guarantee
byte-identical reproduction for the same model+prompt, which is why sweeps pin
7777 — that is reproducibility, not identity.

**Consequence.** The number that matters for a film is the 0.47, not the 0.66:
identity across *shots* is the real problem, and it is harder than across seeds.

---

## 30. A reference image is the strongest identity tool, until the framing changes

*accepted — 2026-08-24*

**Context.** Following #29 the obvious lever is a reference image, and the
`flux_klein` route is exactly that — FLUX.2 Klein multi-image reference.

**Measured, each shot against the reference face:**

| shot | no reference | with reference |
|---|---|---|
| close-up | 0.213 | **0.932** |
| medium, low-key, three-quarter | 0.133 | 0.301 |
| wide | 0.097 | 0.493 |

**Decision.** Use a reference per shot family — an approved close-up to condition
close-ups, an approved medium for mediums — rather than one reference for a whole
film. A character LoRA (L6) is the thing that holds identity independently of
framing.

**Reasoning.** On a matched shot the reference is worth roughly 4× a description,
and 0.932 is not consistency but near-reproduction: far above the 0.667 ceiling
that one character across seeds ever reached. It collapses when the framing
changes because the conditioning is resized to about a megapixel, and a full
figure in a wide shot has too few face pixels left to carry identity.

**A trap in the measurement.** Averaging consistency *across* the three shots
gives 0.371 with the reference against 0.481 without, which reads as "the
reference made it worse". It did not — that average is dominated by how far a
0.93 close-up sits from a 0.30 medium. When one output is nearly a copy of the
target, similarity-among-outputs is the wrong question; each shot must be
measured against the reference.

---

## 31. The look band, measured — and the last guessed constant closed out

*accepted — 2026-08-24*

**Context.** `look_consistency` was the one axis still carrying a band nobody had
measured. It rescaled CLIP cosine over 0.6 → 1.0, a range inherited from when
this function *was* `identity_stability` and worked on whole images, before
ArcFace took that name (#28). Decision #27 said a band ships calibrated or
marked; this one was marked, and this closes it.

**Decision.** Band set to 0.58 → 0.97 from two populations already on disk, both
at one shot (`close_up-key-front`) and one seed set, so the only variable is who
is in the picture:

| population | cosine |
|---|---|
| a different character (heroine vs lighthouse keeper, **same model**) | 0.497–0.580 |
| one character, one model, across three seeds (3 models × 3 seeds) | 0.919–0.959 |

Gap +0.339, no overlap. Floor at the highest true negative, ceiling above the
best observed hold so a steadier stack stays rankable — the same shape as the
face band. Scored end to end on the real renders: darkbeast 0.957, klein 0.917,
zpop 0.884; the two characters mixed together score 0.203.

**Four for four.** Every guessed band in this codebase has now been checked and
every one was wrong. This one was wrong in the quiet way rather than the loud
way: under 0.6 → 1.0 the three real candidates scored 0.80, 0.86 and 0.90, a
0.10 spread on an axis weighted 0.15 — contributing 0.015 to a final score, which
cannot move a ranking. It did not look broken. It looked like agreement.

**The finding worth more than the band.** `gonzalomozpop-v40` scores 0.884 on
look and 0.416 on face. It held the pink hair, the palette and the collar across
all three seeds while rendering three different women. That is decision #28's
premise — that these two axes see different things — observed rather than
argued, and it is the case for keeping both.

**What is still not measured.** "Same person, wardrobe or palette changed" — the
failure this axis is *named* for. Both populations above differ in face and look
together, so what is calibrated is the axis's floor and ceiling, not its
sensitivity to the specific drift it guards. Measuring that needs a population
that holds the face and drops the collar, which nothing on disk currently is.
Recorded in the code rather than left to be rediscovered.

**Cost.** Twelve images, CPU CLIP, minutes. No renders, no GPU.

---

## 32. The cast crosses the seam as data, and the engine is a project-level choice

*accepted — 2026-08-24*

**Context.** The user set the direction: the export should carry OpenMontage's
knowledge — which model holds this character, which reference anchors which
framing — instead of leaving every setting for hands on the Builder. Full
automation is the stated goal, explicitly including revisiting #2's
load-mutate-save boundary if that is what it eventually takes.

**What the Builder turned out to allow.** `image_model_mode` is global UI
state, not a segment field: one image engine per project. Per scene, the
Builder honours a `use_scene_<engine>_settings` flag plus a settings block.
So a cast writes: the flag, a per-scene block, the reference fields, and the
project-level mode — all known keys on a session VRGDG authored, fully inside
#2.

**The per-scene block starts as a copy of the session's own global group.**
Encoder, VAE and resolutions stay whatever the user runs; a cast overrides
only `unet_name`, `seed` (+ `seed_mode: fixed`) and loras. The alternative —
composing the block from the registry — would be a second source of truth for
settings the Builder already owns (#22).

**References attach per shot family, never globally.** #30 measured a close-up
reference at 0.93 on a matched shot and 0.30 on a medium. `references:
{close_up|medium|wide: path}` maps `shot_size` onto a family; a family without
a reference renders from the description alone, with a warning naming the gap.
Reference files are copied into the Builder project's `references/` folder —
the mirror of import copying assets into the OpenMontage project (#4).

**Engines split into two lanes.** Z-Image and Flux Klein are Builder engines:
the cast lands as settings. SDXL is not — it is driven by our bundled
workflow — so its lane is stills rendered on the OpenMontage side and pushed
across as approved scene images (`push_approved_stills`, which already
existed). The engine is resolved from the model registry by file header,
never from the filename (#18): `darkBeast…DIMRclaw` resolving to `zimage` is
the live proof.

**What stays manual, for now.** `new_project` creates folders but never writes
a session; the Builder UI writes the first session from its own in-memory
defaults — the ~95-key object #2 forbids us to construct. So a human creates
the project once and the export targets it via `project_folder`. Closing that
last step is the standing goal; candidate paths are seeding through VRGDG's
`save_project_as` (VRGDG constructs, we copy) or an upstream fix to
`new_project`, both of which keep VRGDG the author of the session.

**Cost.** A cast is only as good as the cast record; a stale record silently
pins every scene to an old model. The record carries `chosen_by: human` (#15)
and the export reports `casting_applied` so the choice is visible at the
moment it lands.

---

## 33. OpenMontage authors the prompts and renders the stills — and the drift it caught

*accepted — 2026-08-24 · revises #9*

**Context.** The user opened the Builder and asked the right question: no
images, no prompt in Image Prep, no prompt in Video Prep — "where are you using
OpenMontage for all this?" #9 had left `i2v_prompt` empty on purpose, and the
stills lane existed but nothing was driving it.

**Decision, in three parts.**

1. **Export authors `i2v_prompt`** via `build_motion_prompt` — description, the
   scene's authored `movement` text (which beats the enum phrase: "the camera
   orbits a full 360 degrees … she does not turn" IS the shot), lighting
   continuity, style. #9's reasoning was "don't guess at video-model phrasing";
   the user's direction is that OpenMontage is the prompt writer — which is L5
   of the plan. The notes stay: they are the brief the prompt was written from,
   and the Builder's Gemma step can still regenerate over an authored prompt.
   Editorial fields (transitions) stay out of the prompt — they belong to the
   cut, not the clip.

2. **OpenMontage renders the scene stills itself** — `comfyui_image` with
   `vrgdg_build`/`zimage`, the cast model, the cast seed, exactly the payload
   shape the screen test measured the model with. The manifest feeds the
   existing stills push.

3. **The push now completes the handshake.** `save_scene_image` copies the file
   and reports where it landed; recording that in the session is the caller's
   job — the Builder UI sets `approved_image_path` after every call, and the
   export now does the same (`image` + `approved_image_path`), in the same
   session write. Same lesson as `new_project`: VRGDG routes do file work and
   leave state to the caller.

**What the first run caught.** sc2's description read "The same clockwork
heroine…" — a cross-scene reference no image model can resolve. The render came
back a different woman: auburn hair, different face. Our own calibrated axes
measured it — face 0.34, look 0.33 — and after restating the character in the
description, 0.55 / 0.68. That is #29 observed in production on the first
automated run: **the description carries the identity, so every scene's
description must restate the character.** The systemic fix is a character block
injected per scene (the L6 direction); until then it is an authoring rule.

**Cost.** Authored prompts can drift from what the Builder's own prompt step
would write; `i2v_prompt_origin` stays `"manual"` so regeneration is always one
click. And a stale UI is now dangerous in a new way: the Builder holds the
session in memory, so an export under an open project is invisible until
reload — and a save from the stale UI overwrites it. Reload before touching.

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
