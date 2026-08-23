---
description: End a work session — run tests, update PROGRESS/DECISIONS/HANDOFF, commit, clean up scratch, and leave a concrete next action.
argument-hint: [optional — anything the user wants noted in the handoff]
---

Follow `.agents/skills/clock-out/SKILL.md` in full.

Work through the Definition of done at the end of that skill and do not declare
the session closed until every line is true.

Anything the user wants recorded in the handoff: $ARGUMENTS

Two reminders that are easy to skip and expensive to miss: `PROGRESS.md` must
match `git status` exactly, and git must be run in a real terminal on the host,
never through a device-bridge shell.
