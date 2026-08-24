# Post — colour, grain, stitch

Step 10 of `vrgdg-character-film`. The last step: the approved takes become a
film.

## triggers

*"finish it"*, *"stitch it together"*, *"final cut"*. Dashboard action:
`post.start`.

## needs

Approved dailies.

## produces

The film in `renders/`; a `render_report`; checkpoint `checkpoint_post.json`,
**gated**.

## does

1. **Compose from `edit_decisions`.** Cuts in order, with the music resolved
   through `audio.music.asset_id` against the `asset_manifest`.

2. **Set the geometry deliberately.** `compose_target` defaults to 1920×1080,
   which letterboxes native 1920×1024 LTX clips into black bars. Pass the
   clips' real geometry. Frame rate is **hardcoded to 30** and the clips are
   24 — a known limitation with no public knob (PLAN WP6, loss 4). It matters
   most on a beat-synced film, so say it rather than shipping a silent
   resample.

3. **Burn captions if the film has lyrics.** `subtitle_gen` carries `karaoke`
   and `word_by_word` styles, and the `song`'s lines have word-level times from
   alignment — which is exactly what those styles want.

4. **VRGDG's post routes** cover LUT, grain, face repair, enhance and stitch.
   They are L4 and not yet wired on our side, so running them by hand in the
   Builder is the current path. Say that rather than quietly skipping the grade.

5. Checkpoint `awaiting_human` and **end the turn.**

## presents

The film, and what was done to it: geometry, frame rate, whether music was
mixed, whether captions were burned, and anything skipped for want of wiring.

## send-back

A rejected cut goes back to dailies, or to a specific scene. The composition
itself is cheap to re-run — it is seconds of FFmpeg — so re-running with a
different grade or a different geometry costs nothing.

## traps

**The FFmpeg path does not resolve `audio.music.asset_id`.** Only
`hyperframes_compose` does. Resolve the id against the manifest yourself and
pass `audio_path`, or the film comes out silent with nothing reporting why.

**Check the output duration against the timeline.** A film that is 8.9 s when
the timeline is 9.0 s has dropped frames somewhere, and a silently short film
is this step's characteristic failure.

**Compose re-encodes every segment.** That is deliberate — stream copy cannot
cut on a non-keyframe and produces segments longer than asked for — but it
means quality settings matter here in a way they do not elsewhere.
