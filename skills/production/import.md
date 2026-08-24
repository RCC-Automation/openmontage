# Import — bring it back

Step 8 of `vrgdg-character-film`. A read: it cannot corrupt anything, so it can
be run freely and re-run whenever more scenes finish.

## triggers

*"bring it back"*, *"import the footage"*. Dashboard action: `import.start`.

## needs

A rendered VRGDG project.

## produces

| | |
|---|---|
| `asset_manifest` | stills, clips and the music track, copied into the project |
| `edit_decisions` | cuts read off the timeline; music referenced by manifest id |
| `beat_map` | the grid VRGDG measured |
| `song` | the lyrics as they stand in the Builder, hand edits included |
| `vrgdg_scene_map` | refreshed |

Checkpoint `checkpoint_import.json` — **not gated**. It is a read; the
judgement happens at dailies.

## does

1. Run `vrgdg_project_sync operation="import"` with `project_dir` and
   `project_folder`.

2. **Set `render_runtime` deliberately.** It defaults to `ffmpeg`, which is
   right when the clips come back already rendered and the remaining edit is
   cuts and concat. Pass the value agreed at proposal rather than accepting the
   default blindly — the schema says as much.

3. **Check the ids came back.** The scene map should pair the same scene ids to
   the same segment ids the export wrote. That match is the proof that identity
   survived a human editing session in the Builder, and it is the single most
   informative thing this step reports.

4. **Report what did not come back.** A half-rendered project is a normal
   mid-production state. Unrendered scenes are warned about, not hidden — a
   silently short film is worse than an error.

## presents

Scene count, each clip's duration against its planned duration, whether the
lyrics came back changed, and anything missing.

## send-back

Nothing to send back. Re-run it freely as more scenes finish.

## traps

**Close the Builder first, or at least do not save from it afterwards.** The
import only reads, so it is safe — but a stale UI saving over the project
afterwards is not.

**A missing clip warns rather than failing.** Read the warnings.

**Hand-edited lyrics come home.** If the user rewrote a line in the Builder,
the imported `song` carries their version. That is intended — it is their
decision — but say so, because it means the artifact changed under them.
