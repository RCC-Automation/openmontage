# Dailies — check the footage *(loop)*

Step 9 of `vrgdg-character-film`. **The agent flags; the human decides.**
Nothing here rejects a take.

## triggers

*"how does it look"*, *"check the footage"*, *"dailies"*. Dashboard action:
`dailies.start`.

## needs

`asset_manifest` and `edit_decisions` from import; `scene_plan` and
`cast_record` to check them against.

## produces

A dailies report; checkpoint `checkpoint_dailies.json`, **gated**.

## does

1. **Check each clip against what its scene asked for.** Did the movement
   happen — is the orbit an orbit, is the push-in a push-in? Is the framing
   what was planned? Does the duration match?

2. **Check the character held.** Sample frames and measure identity against the
   cast record with ArcFace. Drift is the failure this step exists to catch,
   and it has already happened in production once with nothing reporting it
   until it was measured.

3. **Check the technical failures.** Artefacts, frozen frames, a "video" that
   is really a still.

4. **Rank the findings and stop.** Every one is input to a human judgement.
   Say what is wrong, say why you think so, and give the number behind it.

## presents

```
Dailies — 2 scenes

  sc1  4.0s  planned 4.0   identity 0.89   push-in present          ok
  sc2  5.0s  planned 5.0   identity 0.34   orbit present            <- she drifted

  sc2's description says "The same clockwork heroine" - no image model can
  resolve that. Re-stating the character has fixed exactly this before
  (0.34 -> 0.55 face, 0.33 -> 0.68 look).

  Keep, re-shoot sc2, or change the plan?
```

## send-back

Per scene, and to different places depending on what was wrong:

| What is wrong | Goes back to |
|---|---|
| the look — lighting, composition, place | **scene look** (step 5) |
| the motion — wrong move, no move | **export** (step 6), fix the motion prompt |
| the character — she drifted | **scene plan** (step 4), re-state the description |
| the render itself — mush, artefacts | the **Lab**, not another prompt |

Everything not sent back keeps its approval.

## traps

**A low identity score is a flag, not a verdict.** A scene where she is meant
to be in shadow, or turned away, will score low and be exactly right. Look
before believing the number.

**Check the description before blaming the model.** Cross-scene reference —
"the same X", "she" with no antecedent — is the most common cause of drift and
the cheapest thing to fix.

**Measure, do not assert.** "It looks fine" is not a dailies report. Every
claim here should have a number or a frame behind it.
