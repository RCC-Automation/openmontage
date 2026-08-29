---
title: The song — generating one that a film can be cut to
status: measured
updated: 2026-08-29
sources: [../vrgdg/lyrics-and-beats.md, ../../projects/the-man-watches/artifacts/song_takes.json]
---

In a music video the song is the script: picture is cut to it, never under it.
This page is what we measured generating one on this machine — length, tempo
accuracy, and the check that decides whether a take is usable at all.

Measured on `the-man-watches` 2026-08-29, five takes of a 43-line lyric through
`comfyui_music` (ACE-Step 1.5 Turbo, bundled
`ace-step-1.5-turbo-aio-t2a.json`).

---

## What we know

**A 150-second track is fine.** Every take delivered **150.0 s** against 150
requested, at roughly **two minutes of GPU each**. The bundled workflow defaults
to 30 s and nothing here had been asked for more than 60 s before, so this was
an open risk; it is closed. Cost is effectively zero, so generate five takes,
not one.

**Tempo came back accurate for the first time.** Asked 84, delivered
**83.4–86.1 BPM**. That is a much better hit rate than the history — asked 90 it
gave 117.5, asked 110 it gave 112.3 (`DECISIONS.md` #34) — and the difference is
that this request also carried a full structured lyric and a `keyscale`. Do not
generalise it into a rule yet; **still cut picture to the measured grid**, never
the requested number.

**Structure and section order survive a long lyric.** All five takes sang all 26
lines, in order, with the `[verse]` / `[pre-chorus]` / `[chorus]` / `[bridge]` /
`[outro]` sections intact and distinguishable. A one-word change between two
otherwise identical choruses came through as a different sung word.

## The check that decides usability

Forced-align the delivered take against **our own lyrics**
(`tools/audio/lyric_align.py`, which stems the vocal first and is told the
words), then look at two numbers:

| number | why | bad |
|---|---|---|
| **shortest aligned line** | cut boundaries are derived from these | any line under ~1 s |
| **share of track with no vocal** | how much of the film has nothing to cut to | film 1 shipped at 61% |

**Two of five takes carried a sub-second line** (0.60 s and 0.98 s) while
sounding perfectly fine. This is not a cosmetic defect: film 1 derived its cut
boundaries from an alignment that had collapsed the same way and shipped three
shots of **0.11 s, 0.10 s and 0.31 s** — rendered, paid for, invisible, and
signed off by a verification note reading "All 15 scenes assembled cleanly".

So the rule: **a take is unusable if any aligned line is under a second, however
good it sounds.** The check costs seconds and it is the only thing standing
between a good song and an unwatchable edit.

The alignment is in `data['alignment']['segments']`. `data['song']` is filled
only when a song *artifact* is passed in and is `null` for raw lyrics — reading
the wrong key makes a working alignment look like zero results.

## What the machine cannot decide

Which take wins. Every axis above is a disqualifier, not a ranking: they remove
unusable takes and say nothing about whether the song is good. For
*The Man Watches* the selection criterion is whether a listener can hear the
chorus turn from "Build me" to "Burn me" — a question no metric answers.

Generate five, disqualify on the numbers, pick by ear from what survives.

## Traps

**The requested arrangement is a bias, not an instruction.** Tags like "no drums
until 0:46" and "hard drop-out at 2:16" push the arrangement toward a build; they
do not place events at those times. Every timing in the written song is a target
until the track exists.

**The instrumental head is longer than you asked for.** Intros landed at
20–34 s against 14 s intended, and outros ran long too. Retime the shot list
against the delivered track rather than trimming the track to the plan — the
extra seconds at the ends are usually free coverage, and the compression is
always in the middle where it matters.

**`comfyui_music` returns a `ToolResult`, not a dict.** `.success` and `.data`
are the contract; `result.get(...)` raises `AttributeError` *after* the render
has already completed and written the file, so a run can look failed while its
output sits on disk.
