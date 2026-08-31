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

## 34. Real audio replaces the scaffold, analyzed by VRGDG, recorded by us

*accepted — 2026-08-24 · extends #14*

**Context.** The timeline carried a silent bed (#14's scaffold) and the user
asked the obvious: what about the audio? OpenMontage can already make music
locally — `comfyui_music` drives ACE-Step 1.5 Turbo through the bundled
workflow — and VRGDG is a *music video* builder whose whole editing model
hangs off beats. The two had never been connected.

**Decision.** Export takes `audio_path`. The track goes through VRGDG's own
`analyze_audio` — its beat detection, its waveform, its tempo estimate — and
the results are written into the session (`audio_path`, `audio_duration`,
`audio_peaks`, `beat_markers`, `detected_tempo_bpm`, `show_beat_markers`),
because the route, like every VRGDG route, does the work and leaves the
recording to the caller. Silence remains the fallback when no track is given,
and is now recorded in the session too, which it never was.

**The protocol wrinkle that cost the first attempt.** `save_session` takes an
`audio_path` at the *payload top level* and overrides the session's own key
with it on every save — blanking it when absent. The first live run had
beats and tempo land while `audio_path` came back empty, because our client
never sent the payload field. It is also what triggers
`_snapshot_project_assets`, VRGDG's copy of the track into the project
folder — so sending it buys self-containment for free. The client's
`save_session` now carries it; the docstring warns the next caller.

**What this unlocks.** L3 (audio-first timing) is half-open: the Builder now
opens with real beat markers, and `snap_to_beats` is already true in every
session. The remaining half — reading a beat-snapped timeline back and
proposing new scene boundaries through a checkpoint — is the part #Open
questions already flags as gate-sensitive.

**Cost.** ACE-Step interprets tempo loosely (asked for 90 BPM, measured
117.5) — anything beat-critical must use the *measured* tempo from the
session, never the prompt's request.

---

## 35. Nine steps, standalone skills, and Backlot as the cockpit

*accepted — 2026-08-24 · the plan itself lives in `PLAN.md`*

**Context.** After the first end-to-end test Raul said the work so far was not
enough: *"I need a real workflow where I can identify the steps that are
executed with OpenMontage, and I can influence them, with reviews and the
possibility for modifications"*, plus an interactive agent that tries models,
seeds, prompts and LoRAs in conversation. He was right, and the diagnosis is
uncomfortable: everything in that test ran **outside** OpenMontage's own
production system — no pipeline, no checkpoints, no gates, no decision log, no
board. Exactly what Rule Zero forbids. The machinery existed; nothing
VRGDG-shaped ran inside it.

**Decisions.**

1. **Nine steps, three of them loops** — brief, casting, scene plan, scene
   look, export, render, import, dailies, post. Scene look was the gap Raul
   found on reading the draft: casting answers *who is she*, the scene plan
   says *what happens*, and nothing answered *what does this scene look like*
   before it was locked. It is a loop on the casting instrument, producing a
   hero still per scene — which is exactly what export already pushes.
2. **Standalone skills a pipeline strings together**, not pipeline-only
   stages. A cast record outlives the film it was made for; "cast a character
   for me" must work with no production in progress.
3. **Backlot becomes the cockpit** — rejected: a ComfyUI node (it could not
   show a screenplay, a contact sheet or an approval, and it lives inside a
   canvas the workflow does not) and a new standalone app (Backlot is that
   app, already serving state over SSE). A dashboard action cannot *run* a
   step, because the agent orchestrates and Python may not: an action writes a
   **request** the agent consumes. That keeps the constitution and works in
   Claude Code today, with the Agent SDK as the headless path later.
4. **The ComfyUI Lab is the screen test generalized** from *which model* to
   *which graph* — sampler, scheduler, steps, CFG, LoRA stack, node
   substitutions — funnelled, costed by the render clock, scored on the
   calibrated axes, recorded as a recipe keyed by graph shape (#25). The
   boundary from #15 holds: it proposes and measures; the human picks.
5. **The reference modes are the payoff channel** (#33's sequel). VRGDG can
   feed the video step five ways; everything to date used the weakest —
   words plus a start frame. Flux/Nano references, Reference-to-Video,
   Ingredients and ID-LoRA are how the cast references and hero stills reach
   the render as *images*. WP2c, and it ends in a measurement rather than an
   assumption: the reference-mode film must beat the text-mapped one.

**Cost.** A manifest now exists whose stage skills do not
(`vrgdg-character-film.yaml` says so in its own metadata). That is deliberate —
Backlot draws the rail from the manifest, so the steps become visible before
they are runnable — but a reader who trusts the file without reading its status
line will be misled. `WORKFLOW.md`'s status table is the antidote.

---

## 36. A reaction the parser half-understands is a reaction it must ask about

Round 2 of the first live casting session was steered by "I like 4, u, 7 and 8".
The `u` was a typo. `interpret()` understood three picks, discarded the fourth
fragment, and reported nothing — because it only populated its `unknown` list
when it understood *nothing at all*.

That is the wrong threshold. A reaction nobody understood fails loudly and
costs a sentence. A reaction *mostly* understood **runs** — on three models when
four were meant — and the loss is invisible until someone compares the sheet to
what they typed.

`_leftovers()` now reports fragments a partly-understood reaction left behind.
Contractions are stripped before tokenising rather than filtered by length,
because dropping every one-character token to kill the `s` in "that's" also
kills the `u` that needed asking about.

Found the same day: the parser could not read a bare number at all, so
"I like 4, 6, 7 and 8" — how a person actually types it — selected **nothing**.
That reads as being ignored rather than as an error, which is the worse failure
in a conversation.

**The rule:** the unknown list exists so that nothing said is silently dropped.
Reporting it only on total incomprehension inverts its purpose.

---

## 37. Measure the thing you are claiming, not a proxy for it

`TORCH_ROCM_AOTRITON_ENABLE_EXPERIMENTAL=1` was measured at **8.2× faster and
24× less peak memory** on isolated `scaled_dot_product_attention`. That
measurement is real and reproduces.

The claim written from it — that it "applies to rendering, not just training"
and that its memory saving "bears directly on the OOM that killed the backend" —
was an extrapolation, and it was wrong. A real render measured **75 s against a
76 s baseline**. A render is dominated by an 11.7 GB model load, convolutions,
and a VAE that uses split attention regardless; the benchmark isolated the one
part that was not the bottleneck.

The check proposed alongside it also failed: ComfyUI has never emitted the
`still experimental` warning in any log, including logs written before the flag
existed, so its absence is not evidence of anything.

**Contrast with `bitsandbytes` on the same day.** That correction was made by
installing it and stepping an optimiser — and it holds. The difference between
the two is not care or wording; it is that one measured the claim and the other
measured a proxy and reasoned across the gap.

DECISIONS #27 said guessed constants have been wrong every time they were
checked. This extends it: **a measured constant can still support a wrong claim
if the thing measured is not the thing asserted.** The flag stays set — training
is where attention backward is a larger share, and that remains untested — but
nothing counts on it for rendering.

---

## 38. Cast for the property that cannot be added

The first live casting session produced a clean split. `juggernautXL_ragnarok`
renders the brief at **0.87** and holds a face at **0.31** — three different
women across three seeds. `zImageUltimateNSFW_v20` holds a face at **1.00** and
renders the brief at **0.25** — the same woman every time, in generic armour
with no clockwork anywhere.

The instinct is to weigh these against each other. That is the wrong frame,
because the two weaknesses are not equally fixable.

**Identity is addable.** A LoRA puts it in the weights, a reference adapter puts
it in the conditioning, a face repass puts it in post — and all three run on
this machine.

**"Renders brass" is not addable.** No tool teaches a model a look it does not
have.

So the model to cast is the one whose *look* is right, and the drift is the
problem to solve. This inverts what the scores appear to say, and it is why the
LoRA runbook targets juggernautXL rather than the model with the perfect
identity score.

**The corollary for the harness:** a ranking that weights `identity_stability`
at 0.30 and `prompt_adherence` at 0.25 will keep recommending the wrong model
for this decision. The axes are not wrong; using their weighted sum as a casting
verdict is. The machine narrows, the human casts (#15) — and this is a case
where the narrowing itself needs reading against what is fixable.

---

## 39. Identity comes from a face swap, not a LoRA

Four LoRAs were trained on this machine before the mechanism was questioned.
The best reached **0.37** identity to the anchor on held-out prompts. A face
swap reaches **0.80**, on the same prompts, with no training at all.

The LoRA route was not badly executed - it was pushed hard. Four faults were
found and fixed along the way: the dataset was 0.53 consistent and became 0.83;
rank 32 meant a 16x-too-weak LoRA because this trainer derives scale from rank;
62 epochs was double the sane range; and the accept band had been calibrated
against a different mechanism. Each fix was real. **None of them moved identity
much**, because the binding constraint was elsewhere.

`comfy_extras/nodes_train.py` takes a `MODEL` input only. The saved LoRA has
3268 UNet keys and **zero text-encoder keys**. An invented trigger token
tokenises to meaningless fragments, and the text encoder that would learn to map
those fragments to her is frozen. A UNet-only character LoRA binds weakly by
construction.

**So: render with her non-facial features in the prompt, then transplant the
face.** It costs ~15 s per image and no training.

**The cost.** The swap changes the face and nothing else, so hair, build and
wardrobe must be described in the prompt - a market shot generated without her
hair came back a dark-haired woman with her facial geometry, scored 0.778, and
read as a stranger. It also needs a visible face: below ~0.4% of frame nothing
happens. And the swapped face is *cleaner* than the original, because the
restoration models exist to remove blemishes.

**What would change this:** Kohya trains the text encoder. Installing it and
getting it working on ROCm is real work, and the swap already delivers.

---

## 40. Judgement about a rendered image is made by looking at it

Three times this session a number was trusted over the picture, and three times
it was wrong in a way the picture would have shown immediately.

A cosine-only calibration reported that wide shots held identity as well as
close-ups - true, and meaningless, because every "wide" render had come back a
portrait. Identity was measured on full-body frames where the face is under 1%
of the frame and ArcFace returns noise, including negative cosines; those
numbers shaped a whole afternoon. And a claim that the wardrobe had drifted was
made from a glance at thumbnails, asserted as fact, and acted on - deleting 15
correct images and re-rendering for half an hour to fix a problem that did not
exist.

**The rule: a number narrows, a look decides** - the same asymmetry as #15,
applied to images rather than to casting. Concretely: score identity only where
the face is large enough to measure, report the face fraction beside every
identity number so an unmeasurable frame is visible as such, and never act on a
visual claim without opening the image.

---

## 41. Batch-export VRGDG scenes from its installed complete API workflow

A standalone scene workflow is useful precisely when the Builder hides a
machine-specific failure, but the first attempted extraction showed the risk:
copying only the nodes that look relevant dropped required VAE, model, CLIP,
image, audio and saver connections. The file looked plausible and could not run.

**Decision:** the offline/batch exporter clones VRGDG's installed
`Singlei2vForUI_API.json`, changes only named project/scene inputs, and fails if
the expected adapter node IDs are absent. It never bundles a copy of VRGDG's
workflow. The live `build_i2v` route remains preferred when ComfyUI is running;
the offline adapter is for crash recovery, inspection and preparing many scenes.

The machine correction is explicit and narrow: replace the final video
`VAEDecode` with `VAEDecodeTiled` at spatial tile 256. Disabling the second
latent-upscale/refine pass is a separate opt-in transformation because it
changes output resolution as well as cost. The generator carries the session's
model, sampler, LoRA, timing and per-scene override data instead of silently
falling back to the template author's defaults.

**Cost:** this adapter is coupled to one VRGDG route and workflow version. A
VRGDG node-ID change stops generation until the adapter is updated. That is an
intentional visible failure, preferable to a valid-looking graph wired to the
wrong inputs.

---

## 42. Reach for the negative prompt before reaching for ControlNet

*accepted — 2026-08-29*

**Context.** A character brief containing "burning man ... outdoor festival"
produced people nobody asked for in 13 of 36 renders, up to seven in one frame.
Because identity is scored on the largest face, some of those scores were
measuring a stranger. ControlNet was recommended as the fix, downloaded (4.5 GB
across two families) and tested.

**It did not work, and the reason is the decision.** Pose control was given a
control image and `max_detections: 1`, and the pose map it produced contained
**exactly one skeleton** — verified by saving the map. The renders still came
back with 3 and 4 people. ControlNet constrains the structure of the subject; it
does not stop the model painting other people elsewhere in the frame. The extra
figures were the prompt being obeyed.

Crowd terms in the **negative prompt** fixed it 3-for-3, cost nothing, and ran
faster than either ControlNet pass (22–36 s against 45–98 s).

**Decision.** For subject count, and for anything the prompt is plausibly
causing, change the prompt first and measure before adding a model patch.
ControlNet remains justified as a capability the pool otherwise lacks — pose,
depth and composition control — and it is the only lever for the ten models that
cannot use a negative prompt at all. It is not the first thing to reach for.

**Cost, and the reason this is written down.** This reverses a recommendation
made earlier the same day, in which ControlNet was called "the biggest hole, and
the shortest path across it" on the strength of this exact problem. The download
was not wasted, but the reasoning was wrong: a capability gap was diagnosed where
a prompting habit was the cause.

**The constraint that shapes it.** At `cfg` exactly 1.0 ComfyUI never evaluates
the negative branch, so this fix is unavailable — not weak, absent — on **10 of
19 installed models**: the three DMD SDXL checkpoints, all five Z-Image Turbo
merges, Klein distilled and the FluxDAIO. Measured control: darkBeast30 at cfg
1.0 with the same negative stayed at 2 people while three cfg>1 models went to 1.

Also recorded there: **always save the intermediate.** Without the pose map on
disk this would have read as "pose control does not work here" rather than "pose
control worked and the problem is elsewhere".

**Confirmed a second time, 2026-08-30.** A named character rendered as a
foreground portrait however her scale was described. Four prompt-structure and
inpainting strategies failed, including a crop-and-upscale detailer pass that
ruled out "too few pixels" as the cause. A live negative prompt on Z-Image BASE
put her at 57 px on the first attempt, untuned. Same lesson, opposite instinct:
the expensive machinery was reached for first again.

See `wiki/practice/prompting.md` and `wiki/character/placing-her.md`.

---

## 43. A stage is finished when a checkpoint says so, not when the files exist

*accepted — 2026-08-30*

**Context.** `The Man Watches` was built for two days entirely by hand scripts.
The artifacts were real and correct — song, beat map, six picked plates, a shot
list. It had **zero checkpoints**. Nothing was wrong with the work, and yet the
project could not answer three questions about itself: what stage comes next,
whether the human approved anything, and what an earlier stage left unresolved.
All three answers lived in `PROGRESS.md` and in a chat transcript.

That is not a documentation gap. `get_next_stage()` reads checkpoints, so on a
cold open it answered `brief` for a film with a locked score. Nothing prevented
an export of a half-picked film to the Builder except an agent remembering not
to — the same shape of failure as film one, where every defect had a stated
intention behind it and no mechanism.

**Decision.** Every stage of every project ends with a checkpoint, written
through `scripts/checkpoint.py`. The gate protocol is the one already in
`AGENT_GUIDE.md` and it is now actually enforced at write time:
`awaiting_human` → show the human → **stop** → `completed --approved`. Both
enforcement paths were verified live rather than assumed:

```
GATE VIOLATION: stage 'brief' requires human approval ... but status='completed'
was written without human_approved=True.

PREREQUISITE VIOLATION: stage 'score' cannot advance;
incomplete or missing: ['brief', 'casting'].
```

**`--open` is the part that is easy to skip and worth the most.** A stage records
what it did *not* settle, in the checkpoint, so it travels with the film. Casting
carries "identity_stability across seeds is NOT measured — the manifest asks for
it; findability at 60 px was measured instead". That is a success criterion the
stage did not meet, written down by the stage that missed it, surfaced on the
status page, and readable by a session that was never in the conversation. The
alternative is a clean-looking `completed` and a gap nobody finds until the
shoot.

**What it cost to adopt late.** Three stages were approved by the human days
before any record existed, so their checkpoints carry `--approved-on` naming
when and how the decision actually happened. That is an honest audit trail for a
retrofit; it is not a substitute for writing the checkpoint at the time, and it
should not be needed again.

**Consequence for the status page.** `projects/<id>/status.html` shows the
checkpoint reading and the on-disk evidence in two columns and never merges them,
because a disagreement between them is exactly the finding worth seeing. It is
regenerated on every checkpoint write.

See `wiki/practice/checkpoints.md` and WORKFLOW.md, *How every step ends*.

---

## 44. A shot's length comes from the song, never from a default

*accepted — 2026-08-31*

**Context.** 81 frames is the benchmarked configuration on this machine: every
render timing we quote refers to it. It was also left as `render_shots.py`'s
default for real renders. So 34 scenes with 34 different lengths were all
rendered at 5.06 s.

**What that produced.** 27 shots are shorter than 5.06 s, so the clip overran
its slot and the Builder cut it. 7 are longer, so the clip ran out: shot 1 needed
13.05 s and got 5.06 — **7.9 seconds of nothing** in the timeline. Raul saw it
immediately in the Builder; I had reported the gap in passing and moved on
rather than treating it as the blocker it was.

**Decision.** Frames are computed from the scene, always. `--frames` still
exists and now says in its help text that it is for benchmarking only, where
every clip must be identical to be comparable. Frames snap **up** to 4n+1 — Wan's
temporal architecture works in that shape, and rounding up means a clip is never
shorter than its slot.

**It is also cheaper.** The film is 150 s; 34 clips at 5.06 s is 172 s of video
nobody asked for. True length is 2,446 frames against 2,754 — 11% less work.

**The related fix.** A flat 45-minute per-shot timeout marked two *finished*
209-frame renders as FAILED (they take ~48 min). One was recovered by hand; the
other had been sitting on the server for an hour. The wait now scales with the
frame count. A constant that was right for the benchmark was wrong for the film
in two separate places.

See `wiki/practice/cutting-to-the-song.md`.

---

## 45. Cuts land on beats, not on fractions of a section

*accepted — 2026-08-31*

**Context.** `retime_plan.py` mapped each shot-list section onto the song's
measured section boundaries and divided the shots inside it proportionally. The
boundaries were right — they come from `lyric_align` against the vocal. The cuts
between them were arbitrary fractions.

**Measured.** Only **12 of 33** cuts fell within 0.12 s of a beat; median offset
0.18 s. For a film whose founding principle was "the song is the spine and
picture is cut to it", the picture was not cut to it.

**Decision.** Cuts are placed proportionally — that carries the rhythm the shot
list asked for — and then moved to the nearest beat that still leaves every
remaining shot above the 1.5 s floor. Result: **29 of 33**, median offset 0.00 s.

**What is deliberately left off the grid.** Four cuts are song *section*
boundaries, up to 0.37 s from a beat. A verse can legitimately begin between
beats and moving it would break sync with the lyric. Losing four cuts to the
grid is cheaper than losing the words.

**The cost of not having checked.** This was invisible for the whole scene_plan
stage and through an approved gate. `scripts/audit_timing.py` now checks all four
layers — beat_map, song, scene_plan, session — and is cheap enough to run before
every shoot. It also caught the beat-snapped timings being silently reverted by a
second tool writing the session from a stale copy.

See `wiki/practice/cutting-to-the-song.md`.

---

## 46. WSL gets a memory cap below physical RAM

*accepted — 2026-08-31*

**Context.** WSL was holding 33.7 GiB it would not return; Windows ran at 1.7 GiB
available. `/free` on the WSL server released 11 GiB inside torch and handed back
0.3 GiB, against 14.6 GiB on Windows. That asymmetry was recorded in
`wiki/comfyui/two-platforms.md` as a property of WSL.

**It was a configuration error.** `.wslconfig` said `memory=96GB` on a machine
with 63.6 GiB of RAM. WSL had been told it could use 150% of the machine, so it
never met pressure and never stopped growing. There was no `autoMemoryReclaim`
either, so ~26 GiB of page cache holding model weights was never returned.

**Decision.** `memory=48GB`, `swap=8GB`, `autoMemoryReclaim=gradual`,
`sparseVhd=true`. 48 clears the 43.7 GiB measured peak of a Wan video job and
leaves Windows the rest. **Never set `memory` above physical RAM.**

**Measured.** Windows available went from 1.7 GiB to 45.5; `wsl --shutdown`
reclaimed 26.5 GiB instantly. WSL now reports 47 GiB internally instead of 62.

**What this corrects.** The earlier reading — that WSL simply keeps its
allocation — was true of the behaviour and wrong about the cause. The wiki page
said "wsl.exe --shutdown is the only thing that truly reclaims WSL's share";
with a cap and gradual reclaim it is no longer the only thing.

See `wiki/comfyui/wsl-memory.md`.

---

## 47. A prompt describes a look, not a face

*accepted — 2026-08-31*

**Context.** 34 hero stills were rendered from text descriptions naming the
character in full — hair, fur shrug, goggles, glitter, scarf. Measured against
the cast record's own reference: **mean ArcFace 0.057**, highest 0.172, where
0.35–0.40 separates the same person from a stranger. Zero of 28 detectable faces
passed. Twenty-eight unrelated women wearing one costume.

**The mechanism.** A description fixes a *look*. Nothing in it fixes a *face*,
and holding a seed does not help — a seed fixes the ground, and the same seed
with a different prompt produces a different person. This is exactly the failure
the production plan diagnosed for film one ("text-to-video with no identity
conditioning — each clip re-invented the face"), reproduced one stage earlier.

**Decision.** Render freely for body, wardrobe, pose and scene, then transplant
the anchor's face with ReActor. Measured here: mean **0.057 → 0.587**, best
0.855, 20 of 28 above the floor — matching the 0.80–0.88 band already recorded
for ReActor against 0.53–0.68 for an SDXL reference and 0.75–0.84 for IP-Adapter
FaceID, which normalises an adult woman into a teenager.

**The floor is real.** inswapper needs roughly 0.4% of frame to work with. Four
stills were below it and correctly skipped: at that size her face is a few
pixels and the red scarf is what carries her, which the casting round measured
directly.

**What stays unfixed.** ReActor takes the *largest* face in frame. In a crowd
shot that is often a bystander — sc07 scored *worse* after its swap. Targeting
the right face needs `input_faces_index`, which is not yet wired.

See `wiki/character/placing-her.md`.

---

## Open questions

- **Does Wan hold together at 209 frames?** It is trained around 81. Shots 01
  and 02 rendered at 209 without failing, but nobody has judged them for drift
  or looping against an 81-frame equivalent. Seven shots in this film need more
  than 120 frames.
- **Should song section boundaries be nudged onto beats?** Four cuts sit up to
  0.37 s off the grid because `lyric_align` placed the section against the
  vocal. Keeping them preserves lyric sync; moving them would make every cut
  land. Untested which reads better.

- ~~**Where should beat timing win?**~~ **Answered 2026-08-30 by #43.** Proposed
  back through a checkpoint, never applied silently. `retime_plan.py` writes the
  retimed `scene_plan.json` and the stage is checkpointed `awaiting_human` with
  the compromises named — seven shots longer than anything this machine has
  rendered, a verse that halved, an intro that doubled. Which shots to split or
  hold is a creative decision, so the tool reports and the human decides. Still
  open: what happens when a beat-snap arrives *after* `scene_plan` is approved,
  which needs a send-back rather than a first write.
- **LoRA training on ROCm.** VRGDG's Krea-2 Studio installs musubi-tuner and
  ai-toolkit, both CUDA-oriented. L6 may need porting or a rented GPU.
- **Upstream contribution.** Some of this is generic enough to offer to
  `calesthio/OpenMontage` — the client, output-node resolution and pruning are
  not fork-specific. The scene-plan bridge probably is.
