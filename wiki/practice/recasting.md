---
title: Recasting — replacing the character in a finished project
status: measured
updated: 2026-08-28
sources: [../character/face-swap.md, ../vrgdg/traps.md, ../../DECISIONS.md]
---

A VRGDG project is written, composed, timed and rendered, and the person in it
is wrong. The scenes are right; only she is not. Done on `BurningManGirl`,
2026-08-28: 15 scenes, a different woman, everything else kept.

**The instinct is to face-swap the existing images. That is the wrong tool.**
In these shots the face occupies **0.2 – 1.3 %** of the frame. At that scale a
person is recognised by hair, silhouette and costume — none of which a face
swap touches. Swapping all fifteen would have changed the one part nobody can
see and left the character unchanged.

**What actually replaces a character is the description**, and then the images
have to be regenerated from it.

---

## The order that works

1. **Rewrite the character out of every prompt field.** Not one field — seven,
   per scene. On this project the old description lived in `t2i_prompt`,
   `flux_prompt`, `nb_prompt`, `enhance_prompt`, `flow_gpt_prompt`, `i2v_prompt`
   and `story_beat`, and in four files beside the session: `storyboard.json`
   (299 mentions), `wizard_draft.json`, `prompts/t2i_prompts.txt`,
   `prompts/i2v_prompts.txt`. **575 edits in the session, 445 in the side
   files.** Miss `i2v_prompt` and the video stage puts the old character back.

2. **Regenerate each scene** on the project's own engine, conditioned on the new
   character's masters, from the rewritten prompt. Composition, action, location
   and mood survive because only the character clause changed.

3. **Face-swap only where the face is visible.** Above ~0.4 % of frame it lifts
   identity from ~0.15 to ~0.80. Below that, skip it — and on an
   over-the-shoulder shot skip it entirely; the recast already works there
   through hair and costume.

4. **Append, never replace.** Write each new image to the scene's
   `image_history` and move `image_history_index` to it. That is the first
   thing the Builder's render prep reads, so it is what takes effect, and the
   originals stay one click away in the UI.

## What it cost

15 scenes, roughly 30 minutes of GPU for the renders plus swaps. Twelve came
back at 0.68 – 0.83 identity; three were plain renders (face turned away or too
small), which is correct rather than a shortfall.

## Traps

**Substitution tables miss wording variants.** The prompts said "hand-painted
silver jacket" in some scenes and "textured silver jacket" in others; a table
carrying only the first left 27 mentions behind and the images kept the jacket.
**Verify by counting the old terms afterwards**, not by trusting the edit count.

**Order the patterns longest-first.** With `silver jacket` listed before
`textured silver jacket`, the bare form matches first and the qualifier is
orphaned.

**Prompt-only edits do not change rendered images.** Obvious in hindsight and
easy to get backwards: after fixing the wording, the images on disk were still
the ones generated from the old text. Either regenerate, or accept that text
and picture disagree.

**A guard that says "zero edits" may mean "already done".** The recast script
refuses to run when nothing matches, on the assumption the patterns are wrong.
On a second pass over an already-recast session that is a false alarm — hence
`--rerender`.

**The Builder does not watch the session file.** Reload the project before
touching anything, or a save from a stale UI silently overwrites the work.

## The scripts

    scripts/recast_vrgdg_project.py   rewrite prompts, regenerate, swap
    scripts/commit_recast.py          write images + every prompt field, with backups

Both back up before writing, and `commit_recast` refuses a partial set rather
than committing a project where some scenes changed and others did not.
