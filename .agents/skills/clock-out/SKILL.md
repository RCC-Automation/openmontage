---
name: clock-out
description: Use at the end of a work session on this repo, before the user stops or the context runs out. Leaves the repo in a state the next session can resume from cold — tests run, PROGRESS/DECISIONS/HANDOFF updated, work committed, scratch cleaned, next action named. Triggers on "clock out", "wrap up", "end of session", "save state", "I'm done for today", or when context is close to exhausted.
---

# Clock Out

The next session starts from what you leave behind, not from what you remember.
A clock-out that skips the write-up costs the next session an hour of
rediscovery — and rediscovery is where wrong assumptions get made.

Run this **before** the user stops, not after. If context is running low, clock
out early: a complete handoff at 70% context beats a truncated one at 95%.

---

## 1. Get to a known-good state

```bash
python -m pytest tests/contracts/test_vrgdg_tools.py tests/contracts/test_vrgdg_bridge.py -q
```

Record the count — it goes in `PROGRESS.md`.

If tests fail and you cannot fix them now, **that is the most important thing to
write down**. Name the failing test, what you were changing, and your best guess.
Never leave a red suite undocumented; the next session will assume green and
build on sand.

---

## 2. Update `PROGRESS.md`

This is the load-bearing document. It must match reality exactly.

- Move anything finished to its done state; update the layer table.
- Update file inventories and line counts if files were added or grew.
- Update the test counts.
- Update the model table if downloads advanced.
- **Rewrite the "Next" list.** Not a vague direction — the actual next action,
  specific enough to start cold. "Run the live round trip: export a 2-scene plan,
  render in the Builder, import, confirm scene ids match" beats "continue L2".
- Update the date and the HEAD line at the top.

**Invariant: `PROGRESS.md` must never disagree with `git status`.** If you list
something as committed, it must be in a commit. If work is uncommitted, say which
files. This is the first thing clock-in checks.

---

## 3. Record any decisions

If this session chose between real alternatives, add an entry to `DECISIONS.md`
in the existing form: context, decision, cost.

Worth an entry:

- You tried something, it failed, and the failure taught you the constraint.
  (The reasoning is worth more than the conclusion — it stops the same wrong turn
  being taken again.)
- You rejected a reasonable-looking alternative.
- You discovered a property of VRGDG, ComfyUI or the host that shapes the design.

Not worth an entry: routine implementation choices with no live alternative.

If a question surfaced that you could not settle, add it to **Open questions** at
the bottom rather than leaving it in the conversation.

---

## 4. Update `HANDOFF.md` only if the world changed

Do not rewrite it every session. Update it when:

- A new trap was discovered — add it to **Traps**, with the symptom and the cause.
  This section is the highest-value part of the file.
- Paths, versions or hardware changed.
- A command in **Running things** is now wrong.
- What is built changed materially.

---

## 5. Commit

**Run git in a real terminal on the host.** Never through a Cowork device-bridge
shell: it cannot delete files, so every invocation strands `.git/index.lock`, and
`git add`/`git commit` also leave ref locks and `tmp_obj_*` behind, blocking the
next command.

```bash
git add <explicit paths>
git commit
```

Explicit paths, not `git add -A` — scratch directories and `_to_delete/` must not
enter the repo.

Write a commit message that explains **why**, not just what. The pattern that has
worked here: a one-line summary, then a paragraph of context, then a section per
file group explaining the reasoning. Someone reading `git log` in six months
should not need the conversation.

If you deliberately leave work uncommitted, say so in `PROGRESS.md` with the file
list and the reason.

---

## 6. Clean up

- Delete scratch files, temp archives and `.before` backups.
- If a tool could not delete something (the device bridge cannot), say so
  explicitly, with the path, so the user can remove it by hand.
- Never leave a stale `.git/*.lock`. If one exists, move it aside and report it.

---

## 7. Sync the Claude project

If this session produced durable analysis rather than only code, write it to the
attached Claude project (`ComfyUI-OpenMontage-VRGDG`) with `project_write`. The
split that works:

- **Repo docs** carry what a developer needs at the keyboard.
- **Project docs** carry the deeper analysis: route inventories, schemas, system
  profile, the multi-layer design.

Update the existing doc rather than adding a near-duplicate.

---

## 8. Hand off

Close with a short summary the user can act on:

```
Done this session: <what actually changed>
Committed: <sha and summary, or "nothing — <files> left uncommitted because …">
Tests: <count, or what is red>
Left for you: <anything only the human can do — commits, deletions, downloads>
Next session starts with: <the one action, same wording as PROGRESS.md>
```

---

## Definition of done

Do not consider the session closed until every line is true:

- [ ] Tests run; result recorded in `PROGRESS.md`
- [ ] `PROGRESS.md` matches `git status` exactly
- [ ] "Next" names a concrete action, not a direction
- [ ] New decisions in `DECISIONS.md`; new traps in `HANDOFF.md`
- [ ] Work committed, or the uncommitted list written down with a reason
- [ ] Scratch removed, or the leftovers named for the user
- [ ] Anything only the human can do is stated plainly
