# Brief — agree what the film is

Step 1 of `vrgdg-character-film`. The one page everything else is built on.

## triggers

*"I want to make a film about..."*, *"let's start"*, *"new film"*.
Dashboard action: `brief.start`.

## needs

Nothing. This step opens a film.

## produces

| | |
|---|---|
| `brief` | story, character, look, length, mood, platform |
| checkpoint | `checkpoint_brief.json`, **gated** |
| `decision_log` | `category: "creative_direction"`, subject `"Brief"` |

## does

1. **Ask, do not assume.** Read `skills/meta/creative-intake.md`. Four or five
   questions, not twenty — what happens, who is in it, how long, how it should
   feel.

2. **Write the character block so it can be pasted verbatim.** This is the one
   part of the brief with a downstream contract: every scene description will
   re-state the character, and this is the text they re-state. Write it as
   image language a model can render — "luminous pink hair, brass filigree
   collar" — not as adjectives about personality. If it cannot be pasted into a
   prompt unchanged, it is not finished.

3. **State the look as image language too.** "Low-key, warm amber, brass and
   dust" renders. "Moody and atmospheric" does not.

4. **Check the length against the render clock.** A ten-scene film is ten LTX
   renders plus casting plus scene look. Say what that costs in evenings before
   it is agreed, not after.

5. **Note the music intent**, even though the score is its own step — whether
   there is a song, whether it has words, whether a character sings. It changes
   what step 3 does.

6. Write the checkpoint as `awaiting_human` and **end the turn.**

## presents

The brief, one page, as prose a person would actually read. Then one question:
what to change.

## send-back

A rejected brief is rewritten in place. Nothing downstream exists yet, so this
is the cheapest send-back there is — which is the argument for spending real
time here.

## traps

**A brief that describes a mood instead of an image cannot be rendered.** The
test: paste the character block into an image prompt — do you get the right
person? If not, keep writing.

**Scene count times duration is not the film's length.** LTX renders are
per-scene and the render clock knows the real numbers. Ask it.
