# Wiki conventions

How this wiki is written and maintained. Read before adding a page.

The pattern is Karpathy's **LLM wiki**: raw sources stay immutable, the agent
compiles them into durable pages, and answers cite pages rather than
re-reading sources every time. The point, in his words, is that *"the tedious
part of maintaining a knowledge base is not the reading or the thinking — it's
the bookkeeping."* The human curates and asks; the agent does the bookkeeping.

Source: <https://gist.github.com/karpathy/442a6bf555914893e9891c11519de94f>

---

## Three layers, and the difference matters

| Layer | Where | Who writes it | Mutable? |
|---|---|---|---|
| **Raw sources** | `wiki/raw/` | copied in verbatim | **never edited** |
| **The wiki** | `wiki/<topic>/` | the agent, compiled from sources and from what we measured | continuously |
| **The schema** | this file + `wiki/index.md` | the agent, with Raul | rarely |

A raw source is evidence. A wiki page is a claim. Never edit a raw source to
make a page correct — write the correction on the page and say the source is
wrong.

---

## Where a page goes

```
wiki/
├── index.md              the catalog - every page, by topic. Updated on EVERY change.
├── log.md                append-only. One line per ingest, compile or lint.
├── CONVENTIONS.md        this file
├── raw/                  immutable sources, by topic
│   └── <topic>/YYYY-MM-DD-slug.md
├── openmontage/          the governance engine: pipelines, artifacts, gates
├── comfyui/              the renderer: this machine, graphs, models, failures
├── vrgdg/                the Builder: session, routes, lyrics, traps
├── character/            holding one character across scenes
└── practice/             how we actually work: the loops, casting, scoring
```

A topic folder earns its existence at three pages. Below that, put the page in
the closest existing folder.

---

## Page format

Every page opens with this block and nothing above it:

```markdown
---
title: <what a person would call this>
status: measured | researched | assumed | stub
updated: YYYY-MM-DD
sources: [raw/comfyui/2026-08-25-rocm-notes.md, https://example.com/thing]
---
```

`status` is the field that keeps this wiki honest, and it is not decoration:

| status | means |
|---|---|
| **measured** | we ran it on this machine and have numbers. The strongest claim we make. |
| **researched** | read from outside sources, verified, but not run here |
| **assumed** | our working belief, with a stated reason, not yet checked |
| **stub** | the page exists so links resolve; the content does not exist yet |

**Never promote a page to `measured` without a number and where it came from.**
Four guessed constants have been checked against real output on this machine
and all four were wrong (`DECISIONS.md` #27, #31). A page that says "works
well" is a page nobody can act on.

Then the body:

1. **One paragraph saying what this is**, for someone who has never seen it.
2. **What we know**, strongest evidence first.
3. **What it costs** — time, VRAM, money, GPU-minutes — when relevant.
4. **Traps**, if any. These are the highest-value paragraphs on any page.
5. **Open questions**, linking to `QUESTIONS.md` entries by number.

---

## Linking

Wiki pages link to each other with normal relative markdown links:
`[the builder session](vrgdg/builder-session.md)`.

Link generously. A link to a page that does not exist yet is a **stub request**,
not an error — create the stub with `status: stub` so the link resolves and the
gap is visible in the index.

Cite a raw source the same way. Cite an external URL inline.

**Do not duplicate what a repo doc already says.** `DECISIONS.md`, `HANDOFF.md`
and `PROGRESS.md` are the operational record and stay authoritative; the wiki
links to them rather than copying them. The wiki is for knowledge that outlives
this project — how a thing works, what we measured, what to do — not for run
state.

---

## The log

`wiki/log.md` is append-only, newest at the bottom, one line each:

```
## [2026-08-25] compile | character/lora-training | from research workflow wf_1deb0755
## [2026-08-25] ingest  | raw/comfyui/2026-08-25-oom-crash.md
## [2026-08-25] lint    | 3 broken links fixed, 1 stub created
```

Never rewrite history in it. A wrong entry gets a later entry correcting it.

---

## Maintenance

Run `python scripts/wiki_lint.py` — it checks that every page is in the index,
every link resolves, every page has frontmatter, and no page has gone stale
past its status. It fixes what it can and reports what it cannot.

The lint is not a formality. The failure mode of any wiki is quiet rot: a page
that was true in April, contradicted in June by a page nobody linked to it
from. `status` plus `updated` plus the link graph is what makes that findable.

---

## When to write a page

- **After any measurement.** A number that only exists in a chat transcript is
  a number we will pay to rediscover.
- **After research.** Findings land as pages, not as a summary in conversation.
- **After a trap costs time.** If it cost an hour once, it will cost an hour
  again. Traps are the highest-return content in this wiki.
- **Not** for run state, decisions, or progress. Those have their own files.
