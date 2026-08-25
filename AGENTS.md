# OpenMontage

**MANDATORY: Read `AGENT_GUIDE.md` before responding to ANY user message.**

Do not act on the user's request until you have read AGENT_GUIDE.md.
It contains routing rules that determine your first action based on what the user asked.
Skipping it WILL cause you to take the wrong action.

There are no instructions in this file. All instructions are in AGENT_GUIDE.md.

---

## This fork: RCC-Automation/openmontage

Upstream is `calesthio/OpenMontage`. This fork adds a **VRGDG integration**: it
drives a local ComfyUI running the `comfyui-vrgamedevgirl` (VRGDG) node pack, and
bridges OpenMontage's `scene_plan` to VRGDG's Music Video Builder timeline in both
directions.

Read these before working on that integration:

| Doc | For |
|---|---|
| [`wiki/`](wiki/index.md) | **What we know**, compiled to last: how the tools work, what we measured, the traps. Start at `wiki/index.md`; read [`wiki/CONVENTIONS.md`](wiki/CONVENTIONS.md) before adding to it. |
| [`QUESTIONS.md`](QUESTIONS.md) | Open questions parked with the assumption made and what changes if it is wrong. |
| [`HANDOFF.md`](HANDOFF.md) | **Start here if you are picking this up cold.** Environment, paths, how to run things, the traps. |
| [`PROGRESS.md`](PROGRESS.md) | What is built, what is in flight, what is next. |
| [`DECISIONS.md`](DECISIONS.md) | Why the integration is shaped the way it is. Read before changing it. |
| [`IDEAS.md`](IDEAS.md) | Proposed but undecided directions — the screen-test lab and the dailies loop. Not scheduled; read before proposing new architecture. |
| [`.agents/skills/comfyui/SKILL.md`](.agents/skills/comfyui/SKILL.md) | The three graph sources, including `vrgdg_build`. Mandatory before calling any `comfyui_*` tool. |
| [`.agents/skills/clock-in/SKILL.md`](.agents/skills/clock-in/SKILL.md) and [`clock-out`](.agents/skills/clock-out/SKILL.md) | **Run clock-in before your first action in a session, and clock-out before it ends.** They are what keeps the docs above true. |

**The wiki is part of the work, not a write-up afterwards.** Anything measured,
researched, or that cost time as a trap goes in `wiki/` while it is fresh — a
number that lives only in a chat transcript is a number we will pay to
rediscover. Run `python scripts/wiki_lint.py` before you finish. `clock-out`
enforces this.

Three constraints that will waste your time if you do not know them:

1. **The host is AMD/ROCm, not CUDA.** Triton, SageAttention and xformers are
   unavailable. Prefer fp8/GGUF/int8 weights. **`bitsandbytes` DOES work**
   (corrected 2026-08-25), and `TORCH_ROCM_AOTRITON_ENABLE_EXPERIMENTAL=1`
   is worth 8.2× on isolated attention but showed **no gain on a real render**
   — set it for training, not as a rendering fix. See
   [`wiki/comfyui/this-machine.md`](wiki/comfyui/this-machine.md).
2. **Models live outside the ComfyUI install**, in ComfyUI Desktop's shared tree.
   See `HANDOFF.md` for the paths.
3. **Never run `git` through a Cowork device-bridge shell.** It cannot delete
   files, so every invocation leaves `.git/index.lock` behind and blocks the next
   command. Run git in a real terminal on the host.
