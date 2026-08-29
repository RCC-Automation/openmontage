# Wiki index

Everything we know about making films with this stack, compiled into pages
that outlive any one run. Read [`CONVENTIONS.md`](CONVENTIONS.md) before
adding to it.

**What lives here:** how the tools work, what we measured, what to do, and the
traps that cost time. **What does not:** run state, decisions and progress —
those stay in [`PROGRESS.md`](../PROGRESS.md), [`DECISIONS.md`](../DECISIONS.md)
and [`HANDOFF.md`](../HANDOFF.md), and the wiki links to them.

Every page carries a `status`: **measured** (we ran it here, with numbers) ·
**researched** (read and verified, not run here) · **assumed** (working belief)
· **stub** (placeholder so links resolve).

---

## The machine and the renderer

| Page | Status | |
|---|---|---|
| [comfyui/this-machine.md](comfyui/this-machine.md) | measured | AMD/ROCm, what is unavailable, and why that decides everything |
| [comfyui/graph-sources.md](comfyui/graph-sources.md) | measured | the three ways a graph reaches ComfyUI |
| [comfyui/models.md](comfyui/models.md) | measured | what is installed, what drives what, why filenames lie |
| [comfyui/image-recipes.md](comfyui/image-recipes.md) | measured | **every image family, its official recipe and what a render costs** |
| [comfyui/failure-modes.md](comfyui/failure-modes.md) | measured | OOM aborts, silent unavailability, mis-driven checkpoints |

## VRGDG — the Builder

| Page | Status | |
|---|---|---|
| [vrgdg/what-it-is.md](vrgdg/what-it-is.md) | stub | the cockpit inside ComfyUI, and what it does not do |
| [vrgdg/builder-session.md](vrgdg/builder-session.md) | stub | the opaque session, and the rule that follows from it |
| [vrgdg/routes.md](vrgdg/routes.md) | stub | build routes, project-bound vs standalone, host-bound |
| [vrgdg/lyrics-and-beats.md](vrgdg/lyrics-and-beats.md) | stub | the lyric system, the beat grid, forced alignment |
| [vrgdg/traps.md](vrgdg/traps.md) | measured | the ones that cost real time |
| [vrgdg/video-render.md](vrgdg/video-render.md) | measured | **the upscale pass is 24x the base render** — timings, hangs, the escape hatch |
| [vrgdg/video-engines.md](vrgdg/video-engines.md) | researched | Builder-native LTX/H3 routes and the Wan/Hunyuan custom-workflow boundary |

## OpenMontage — the governance engine

| Page | Status | |
|---|---|---|
| [openmontage/what-it-is.md](openmontage/what-it-is.md) | stub | why a governance engine, and what it cannot do |
| [openmontage/artifacts.md](openmontage/artifacts.md) | measured | the contracts between stages, and the silent-skip trap |
| [openmontage/gates.md](openmontage/gates.md) | stub | what the checkpoint machinery actually enforces |
| [openmontage/the-seam.md](openmontage/the-seam.md) | stub | how the two systems join, and who owns what |

## Character — holding one person across scenes

| Page | Status | |
|---|---|---|
| [character/the-problem.md](character/the-problem.md) | stub | why this is the hard part, stated precisely |
| [character/what-we-measured.md](character/what-we-measured.md) | measured | seed vs description, reference per shot family, the numbers |
| [character/measuring-identity.md](character/measuring-identity.md) | measured | ArcFace and CLIP, what each sees, calibrated bands |
| [character/techniques.md](character/techniques.md) | researched | the ranked survey — what to do, in order |
| [character/lora-training.md](character/lora-training.md) | measured | **it trains: 2.49 s/step, gate 0.22 → 0.43** — trainers, dataset, hyperparameters |
| [character/reference-conditioning.md](character/reference-conditioning.md) | researched | **the two mechanisms that fail oppositely** — and why ours collapsed |
| [character/faceid-on-this-machine.md](character/faceid-on-this-machine.md) | measured | **what the embedding path buys and what it costs** — settings, the framing override, the plastic skin |
| [character/face-swap.md](character/face-swap.md) | measured | **the mechanism that actually holds a face here** — 0.80-0.88, and its two rules |
| [character/choosing-a-mechanism.md](character/choosing-a-mechanism.md) | measured | **all four ranked in one run** — swap, reference, FaceID, LoRA, at two shot sizes |
| [character/dataset-bootstrap.md](character/dataset-bootstrap.md) | researched | 20–40 consistent images from one render |
| [character/runbook-first-lora.md](character/runbook-first-lora.md) | assumed | **the steps** — phase by phase, with a gate on each |
| [character/video-identity.md](character/video-identity.md) | stub | what drifts across a clip and what stops it |

## Practice — how we work

| Page | Status | |
|---|---|---|
| [practice/the-loops.md](practice/the-loops.md) | stub | the four places quality comes from |
| [practice/casting.md](practice/casting.md) | stub | narrowing to one character, round by round |
| [practice/prompting.md](practice/prompting.md) | measured | **the bystander problem was a prompting failure** — and half the pool cannot use the fix |
| [practice/measuring-before-believing.md](practice/measuring-before-believing.md) | measured | the house rule, and the four times it paid |
| [practice/seeds.md](practice/seeds.md) | measured | **the variant generator** — what a seed does, why range is irrelevant, why variety saturates |
| [practice/recasting.md](practice/recasting.md) | measured | replacing the character in a finished project — 7 prompt fields, not one |
| [practice/image-benchmark.md](practice/image-benchmark.md) | assumed | comparing eighteen image models fairly — per-family axes, dialects, tiers |
| [practice/the-song.md](practice/the-song.md) | measured | **150 s holds, 84 BPM lands** — and the one check that decides if a take is usable |

---

## Raw sources

Immutable, in [`raw/`](raw/). Never edited — a source that turns out to be
wrong gets corrected on the page that cites it, not in the source.

---

## Log

[`log.md`](log.md) — append-only, one line per ingest, compile or lint.
