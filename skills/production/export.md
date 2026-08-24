# Export — fill the Builder timeline

Step 6 of `vrgdg-character-film`. The hand-over: everything decided so far
becomes a VRGDG project that opens ready to render.

## triggers

*"export it"*, *"send it to the Builder"*. Dashboard action: `export.start`.

## needs

| Artifact | Required |
|---|---|
| `scene_plan` | **yes**, approved |
| `cast_record` | **yes**, approved |
| `song` + `beat_map` | when the film has music |
| hero stills | from scene look, listed in the `asset_manifest` |

## produces

A VRGDG project with a filled timeline; `vrgdg_scene_map.json`; checkpoint
`checkpoint_export.json`, **gated**.

## does

1. **A human creates the project first.** `new_project` makes the folder
   skeleton and names a `session_path` it never writes — the Builder UI writes
   the first session itself. A project created through the route alone cannot
   be loaded, so target an existing one via `project_folder`. This is
   QUESTIONS Q3, unresolved; say so rather than letting it look like a bug.

2. Run `vrgdg_project_sync operation="export"` with `scene_plan`, `casting`,
   `audio_path` and `song`. It writes per-scene model settings, a fixed seed,
   the reference per shot family, the still and motion prompts, the hero
   stills, the analyzed audio with its beat markers, and the lyrics.

3. **Reload the project in the Builder before touching anything.** The Builder
   holds the session in memory and does not watch the file. Export while it is
   open and the user sees a stale blank timeline — and worse, any save from
   that stale UI silently overwrites the export.

4. Checkpoint `awaiting_human` and **end the turn.**

## presents

The timeline as exported — scenes, prompts, cast, references, audio, lyrics —
and the reminder to reload before editing. Then: change anything in the Builder
before rendering.

## send-back

Re-exporting refuses to overwrite a timeline that already holds work unless
told to. If one scene is wrong, prefer fixing it in the Builder to re-exporting
the film: the Builder is where the human's edits live.

## traps

**Never make the approved slot a scene's only image source.** The Builder's
render prep copies the scene's image *source* into the approved slot on every
render, and `save_scene_image` has no same-file guard. A scene whose only
source is the approved slot copies the file onto itself and dies with
`[WinError 32]` — which survives a reboot, because nothing external holds the
file. The export stages stills into `openmontage_stills/` for exactly this
reason.

**`audio_path` must ride at the payload top level on save.** The server
overrides the session's own key with it every time, and that field is also what
makes VRGDG snapshot the track into the project.

**Template model names are not yours.** Always pass `unet_name` / `clip_name` /
`vae_name`; `model_defaults` returns the user's real choices.

**Lyrics need times.** Lines without them cannot be placed and are reported as
unplaceable. Run the score's alignment step first.
