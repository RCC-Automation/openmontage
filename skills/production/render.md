# Render — make the clips

Step 7 of `vrgdg-character-film`. **The human does this one**, in the Builder.
It is the creative eye on every take, and nothing here should try to take that
over.

## triggers

*"I'm going to render"*, *"how long will this take"*. Dashboard action:
`render.start` — which only records that rendering began; it cannot press
anything.

## needs

An exported project, approved.

## produces

Rendered clips inside the VRGDG project; checkpoint `checkpoint_render.json`,
**gated** — the human says when the footage is done.

## does

1. **Cost it honestly first.** Ask the render clock how long the film is likely
   to take and say the number. LTX video is by a wide margin the slowest thing
   on this machine. If a route has never been measured, say it is unknown
   rather than inventing a plausible figure.

2. **Say what to press, then get out of the way.** Which scenes, in what order,
   and anything the export could not fill. The Builder is where the creative
   judgement happens — re-take a scene, tweak a prompt, try a seed.

3. **Queue nothing else.** One GPU job at a time. A casting round or a Lab
   sweep started during a render both fights for the GPU and corrupts the
   render clock's measurements, which are taken from submission time.

4. Wait. When the human says it is done, checkpoint and move to import.

## presents

The render list and the estimate. Then nothing until they come back.

## send-back

There is nothing to send back — this step produces what it produces. A bad take
is handled at dailies, which is where the judgement belongs.

## traps

**Do not poll the Builder.** It is a person at a machine, not a job queue.
Asking repeatedly whether they are finished is both useless and irritating.

**A failed scene is not a failed film.** One bad take goes back to scene look
or export for that scene; every other scene keeps its approval.

**Check the LTX weights are selected in the Builder** before a first LTX
render. The client reads `VRGDG_Model_Defaults`, which only gets written when
the models have been picked once in the UI.
