---
name: clock-in
description: Use at the very start of a work session on this repo, before touching any file or answering the first request. Establishes where the previous session stopped, verifies the environment (git state, ComfyUI, VRGDG, models, tests) and proposes the next action. Triggers on "clock in", "start work", "where were we", "pick up where we left off", "resume", or any first message in a fresh session about the VRGDG integration.
---

# Clock In

Ten minutes here saves an hour of working from stale assumptions. The failure
this prevents is the expensive one: writing code against a state that changed —
a half-downloaded model, an uncommitted branch, a ComfyUI that isn't running.

**Do not start the user's task until every step below has run and you have
reported.** If the user is impatient, say what you're checking and why, and keep
going. The one exception: a purely conversational question ("what is VRGDG?")
needs no clock-in.

---

## 1. Read the continuity docs

In this order. Do not skim past a contradiction — a doc that disagrees with
reality is itself a finding worth reporting.

1. `AGENT_GUIDE.md` — mandatory for this repo regardless of task (Rule Zero, the
   decision-communication contract, gate protocol).
2. `PROGRESS.md` — what is built, what is uncommitted, what is next.
3. `HANDOFF.md` — the environment and the traps. **Read the Traps section in full
   every session**; they are not intuitive and they do not stay learned.
4. `DECISIONS.md` — skim the headings. Read any entry your task would touch.
   Changing a decision without reading why it was made is how the same bug gets
   reintroduced.

If the task involves a `comfyui_*` tool, also read
`.agents/skills/comfyui/SKILL.md` — mandatory per AGENT_GUIDE, and it carries the
three graph sources including `vrgdg_build`.

---

## 2. Establish the git state

Run in a **real terminal on the host** — never through a Cowork device-bridge
shell, which cannot delete files and strands `.git/index.lock` (HANDOFF.md, Traps).

```bash
git rev-parse --abbrev-ref HEAD
git log --oneline -3
git status -sb
```

Reconcile against `PROGRESS.md`:

- Does HEAD match the commit PROGRESS claims?
- Does the uncommitted list match what PROGRESS says is uncommitted?
- Is the branch ahead of origin, i.e. is work sitting unpushed?

**A mismatch is the single most important thing to report.** It means the last
session ended without a proper clock-out, and PROGRESS cannot be trusted until
reconciled.

---

## 3. Verify the environment

```bash
python -c "from tools._comfyui.vrgdg import VRGDGClient; c=VRGDGClient(); print('VRGDG reachable:', c.is_available())"
```

`False` does not mean broken. Distinguish the two causes — `unavailable_reason()`
already does:

- ComfyUI is not running → the user starts ComfyUI Desktop. Everything needing
  generation is blocked; bridge and unit work is not.
- ComfyUI is up but the routes are missing → the VRGDG pack failed to load.
  Check ComfyUI's log for a per-module import failure; a missing dependency
  silently removes a whole family of nodes.

Also confirm `.env` contains `COMFYUI_SERVER_URL=http://localhost:8188`. Without
it generation still works on the default, but preflight reports the provider as
unconfigured, which misleads the next person.

---

## 4. Check the model state

Only if the session's work touches generation.

```powershell
cd $env:LOCALAPPDATA\Comfy-Desktop\_vrgdg_setup
.\Install-VRGDGModels.ps1 -Preview
```

`-Preview` downloads nothing. Anything listed as `[part]` or "would download" is
not yet usable. Cross-check against the model table in `PROGRESS.md` and correct
that table if it has drifted.

Remember which build routes each file gates: no LTX weights means every LTX
route is dark, and the session's default `video_engine` is `"ltx"`.

---

## 5. Establish a green baseline

```bash
python -m pytest tests/contracts/test_vrgdg_tools.py tests/contracts/test_vrgdg_bridge.py -q
```

Expect **111 passed** (45 + 66) as of 2026-08-24. That number is a copy, and
copies rot — the Tests table in `PROGRESS.md` is the source of truth when the two
disagree, and this line is what should be corrected (DECISIONS.md #22). A failure
here is a finding, not a nuisance — you have just learned something changed
underneath the work. Fix or report it before starting anything new.

For a broader check, `python -m pytest tests/contracts -q` runs the whole suite
and is green on this machine; `PROGRESS.md` carries the current count. Expect
~13 unrelated failures in a bare environment (`google.genai`, mermaid CLI absent).

---

## 6. Report, then propose

Report in this shape. Short — the user wants the state, not the transcript.

```
Branch <name> at <sha>, <n> ahead of origin.
Uncommitted: <files, or "clean">
ComfyUI: <reachable / down / pack not loaded>
Models: <what is ready, what is still missing>
Tests: <n passed / what failed>
PROGRESS.md says next: <the next step from its list>
```

Then state the one action you propose to take, and **wait**. Do not begin. If
anything in step 2 disagreed with `PROGRESS.md`, say so first and propose
reconciling before any new work.

---

## Stop conditions

Raise these rather than working around them:

- **PROGRESS.md and git disagree.** Reconcile first, with the user.
- **The baseline suite fails.** Something changed underneath; understand it
  before building on it.
- **Work is uncommitted from a previous session** and you are about to touch the
  same files. Offer to commit it first so the boundary between sessions stays
  legible in history.
