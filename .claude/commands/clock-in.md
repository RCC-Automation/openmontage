---
description: Start a work session on the VRGDG integration — read the continuity docs, verify git/ComfyUI/models/tests, report the state and propose the next action.
argument-hint: [optional — what you intend to work on]
---

Follow `.agents/skills/clock-in/SKILL.md` in full before doing anything else.

Run every step: continuity docs, git state, environment, models, baseline tests.
Then report in the shape the skill specifies and **wait for confirmation** before
starting work.

The user's intent for this session, if given: $ARGUMENTS

Use it only to decide which parts of `DECISIONS.md` to read in full and whether
the model check matters — never to skip a step. A mismatch between `PROGRESS.md`
and `git status` outranks whatever the user asked for; report it first.
