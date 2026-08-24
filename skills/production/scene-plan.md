# Scene plan — write the shots, on the beat

Step 4 of `vrgdg-character-film`.

## triggers

*"write the scene plan"*, *"plan the shots"*. Dashboard action: `scene_plan.start`.

## needs

| Artifact | Required | Why |
|---|---|---|
| `brief` | **yes**, approved | the story and the character block |
| `cast_record` | **yes**, approved | who she is; which shot families have references |
| `beat_map` | **yes** | scene boundaries land on measured beats |

The manifest requires `beat_map`, so the score is locked first. A film
genuinely without music needs that requirement relaxed — say so rather than
inventing a grid.

## produces

| | |
|---|---|
| `scene_plan` | ordered scenes with timing, framing, camera, lighting, movement |
| checkpoint | `checkpoint_scene_plan.json`, **gated** |
| `decision_log` | `category: "scene_structure"`, subject `"Scene plan"` |

## does

1. **Lay the scenes on the grid, according to what the grid is worth.** Read
   `beat_map.confidence` first:

   | | |
   |---|---|
   | `strong` | boundaries snap to beats; prefer downbeats where you have them |
   | `weak` | the tracker imposed a grid on calm music — **pace by phrase**, never hard-cut |
   | `none` | time by content alone |

   Snapping to a grid the tracker invented is worse than ignoring it.

2. **Group by section before beat.** A chorus is one visual idea; cutting
   across its boundary because a beat happened to fall there reads as a
   mistake. Use `beat_map.sections` and the song's section spans.

3. **Re-state the character in every scene description.** Never "the same
   heroine", never "she" as the only reference. This is not style, it is a
   measured failure: a scene whose description said "The same clockwork
   heroine" rendered a different woman, and restating it fixed the identity
   score from 0.34 to 0.55. Paste the brief's character block.

4. **Choose shot sizes against the references you actually have.** The cast
   record carries a reference per shot family. A shot size with no reference
   will hold identity less well — either add one, or choose differently, but do
   it knowingly.

5. **Write movement as movement, not as a mood.** It becomes the video prompt.
   "The camera orbits a full 360 degrees around her and returns to where it
   started; she stays planted, facing forward" beats "dynamic camera work".

6. Checkpoint `awaiting_human` and **end the turn.**

## presents

The plan scene by scene, on the board. For each: what happens, how it is shot,
how long, and **which beat its boundary lands on**. Then: edit, reorder, add,
remove.

## send-back

A rejected plan is rewritten. If the *score* changed, re-run the timing pass —
a new track has a new grid and the old boundaries no longer land on beats.

## traps

**"Beat" means two things here.** `story_beat` and `narrative_role` are
dramatic beats. Musical beats live only in `beat_map`. Never time a cut from a
`story_beat`.

**A scene shorter than about a second is not a shot.** The grid will happily
offer you one.
