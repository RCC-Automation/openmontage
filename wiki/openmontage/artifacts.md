---
title: Artifacts — the contracts between stages
status: measured
updated: 2026-08-25
sources: [../../AGENT_GUIDE.md]
---

Each stage of a pipeline produces one canonical artifact, and that artifact is
the contract the next stage reads. Not a convention — a JSON schema in
`schemas/artifacts/`, validated at checkpoint-write time.

## The artifacts

| Artifact | Produced by | Carries |
|---|---|---|
| `brief` | idea | story, character, look, length, mood |
| `cast_record` | casting | the locked identity: model, seed, LoRAs, references |
| `song` | score | lyrics as sections then lines, a singer and a time per line |
| `beat_map` | score | measured tempo, beat positions, sections, confidence |
| `scene_plan` | scene_plan | ordered scenes with timing, framing, camera, movement |
| `asset_manifest` | assets | every generated file, with provenance and scene linkage |
| `edit_decisions` | edit | cuts, overlays, subtitles, music **by manifest id** |
| `render_report` | compose | output paths, encoding profile, verification |

## The trap that matters most

**An artifact absent from `ARTIFACT_NAMES` is silently skipped by checkpoint
validation.** `lib/checkpoint._validate_artifacts_for_stage` does:

```python
if artifact_name not in ARTIFACT_NAMES:
    continue
```

No warning. The artifact is written into the checkpoint unchecked.

`cast_record` sat in exactly that state through a whole production — declared by
the pipeline manifest, produced, consumed by the export, and validated by
nothing. It had no schema at all until 2026-08-25, which is how a record with an
absolute Windows path where every other artifact is project-relative reached the
export unremarked.

**Registering the name in `ARTIFACT_NAMES` is what makes validation happen.**
Writing the schema file is not enough. The reason is now in `validate_artifact`'s
docstring so the next person does not repeat it.

## Music is referenced by id, never by path

`edit_decisions.audio.music.asset_id` resolved against the manifest is the real
contract — that is what `hyperframes_compose` reads. The top-level `music` block
the schema still carries is marked legacy.

The bridge had been writing `music: {"source": "<filename>"}` — a key that is
**not in the schema at all**, inside a block nothing reads. The track was
invisible to every composition path and no test could see it, because the
fixture never wrote an audio file to disk.

**The contract is not uniform across runtimes.** `hyperframes_compose` resolves
the asset id; `video_compose`'s FFmpeg path does not, and needs an explicit
`audio_path`. Resolve it yourself when composing through FFmpeg.

## Paths are project-relative

`"Relative path within the pipeline project directory"` — the `asset_manifest`
schema says so in as many words. An absolute path in a committed artifact is
invalid the moment the project moves.

`cast_record.references` is the known exception, carrying absolute paths into
`projects/screen-tests/`. Accepted rather than enforced, because tightening it
would break the one working export. `QUESTIONS.md` Q2.

## What the manifest declares but nobody enforces

`required_artifacts_in` is in the pipeline manifest schema and in **all 14
manifests**, and is read by no code in the repo. A `scene_plan` checkpoint
completes happily with no `beat_map` anywhere — which is exactly the failure
that moving Score before the scene plan was meant to prevent.

It reads like a guarantee and it is a comment. `QUESTIONS.md` Q5.
