# Score — write and make the song *(loop)*

Step 3 of `vrgdg-character-film`. Also usable on its own: "write me a song for
a clockwork heroine" with no film in progress produces a track, its lyrics and
its beat map, and those outlive whatever they were made for.

**The track comes before the shots.** In a music video the song decides when to
cut. Written first, scene boundaries land on real beats because they were
planned that way; written last, every cut has to be nudged onto a grid that
already exists. That ordering is the whole reason this step is where it is.

---

## triggers

*"let's do the song"*, *"write the score"*, *"make the music"*, *"I have a
track"*. Dashboard action: `score.start`.

## needs

| Artifact | Required | Why |
|---|---|---|
| `brief` | no | supplies mood, length and subject when there is one |
| `cast_record` | no | only to name singers. A song can be written before anyone is cast; a *singer* cannot |

Approved first: nothing. This step can open a film.

## produces

| | |
|---|---|
| `song` | the words — sections, lines, a singer and a time per line |
| `beat_map` | the measured grid the scene plan will cut to |
| an audio asset | in `assets/music/`, listed in the `asset_manifest` |
| checkpoint | `checkpoint_score.json`, **gated** — the human hears it before anything is built on it |
| `decision_log` | `category: "music_selection"`, subject `"Score"` |

---

## does

### 1. Agree the song before generating a note

Write the `song` artifact first — title, style, and the lyrics as sections then
lines. Show it as words on a page. Generating before the words are agreed
wastes a render and, worse, anchors the conversation on a track nobody chose.

Style is written as the generator wants it: comma-separated tags
(`"cinematic synthwave, female vocals, analog bass"`), not a paragraph. **Do
not put a tempo in the style string** — it goes in `requested_tempo_bpm`.

Section labels double as the generator's structure tags, so use its vocabulary:
`intro`, `verse`, `chorus`, `bridge`, `outro`, `instrumental`. Read
`.agents/skills/acestep/SKILL.md` before writing lyrics — UPPERCASE is vocal
intensity, parentheses are backing vocals, and 6–10 syllables a line sits
naturally against a beat.

If the film has cast characters, assign a `singer` per line. The name must
match a `cast_record` character: VRGDG resolves singers against the same
reference subjects casting already writes, so a name that matches is a singer
that exists and a name that does not is a line nobody sings.

**Gate one: show the words. Wait.** Cheap to change now, expensive later.

### 2. Generate, or take what the user has

Announce the tool, provider, model and whether this is a sample before calling —
the decision-communication contract applies here as everywhere.

Local and free: `comfyui_music` (ACE-Step 1.5 Turbo). About 30 s for a 9-second
track on this machine, so iterating is cheap. Build its `lyrics` parameter from
the `song` artifact, not from a separately-written string — the artifact is the
source of truth and a second copy will drift from it. Delivery directions go in
as `[bracketed]` prefixes; they are instructions to the generator.

If the user brings a track, skip generation entirely and set `source:
"provided"`. `music_library/` counts as provided.

### 3. Measure it. Never trust what you asked for

```
audio_beatmap  audio_path=<the delivered track>  requested_tempo_bpm=<what you asked>
```

**This is the step that exists because of a measured failure.** ACE-Step has
been asked for 90 BPM on this machine and delivered 117.5, and for 110 and
delivered 112.3. A plan timed from the request rather than the delivery is
wrong by up to 30%, silently. `audio_beatmap` records both and warns when they
disagree; everything downstream reads `tempo_bpm`, never `requested_tempo_bpm`.

Read `confidence` and honour it:

| | |
|---|---|
| `strong` | a real pulse. Cuts may land hard on beats |
| `weak` | the tracker imposed a grid on calm music. **Pace by phrase**, never hard-cut |
| `none` | no usable rhythm. Time the film by content alone |

The bands behind that verdict are **not calibrated** (QUESTIONS Q1). On a
`strong` verdict, spot-check one cut by ear before trusting the whole grid.

### 4. Give the lines their times

```
lyric_align  audio_path=<track>  song_path=artifacts/song.json
```

This is **forced alignment, not transcription** — it is handed the lyrics you
wrote and asked where they occur. It cannot get the words wrong because it is
not choosing them, and it stems the vocal out first so it works over a full
mix. Word-level times, and instrumental gaps marked.

Without this the lines have no times, and a line with no time cannot be placed
on a timeline, in a cue, or in a caption.

### 5. Present it and stop

Play the track. Show the lyrics with their times. Show the measured tempo
**next to** the requested one when they differ — that gap is interesting to a
human, not just to the machine.

Then **write the checkpoint as `awaiting_human` and end the turn.** Doing more
work in the same response is a gate violation.

---

## the loop

A reaction becomes the next round. Hold the state in
`lib/loop_session.LoopSession(project_dir, "score")` — the reaction verbatim
*and* what was made of it, so a misreading is visible later.

| They say | You change |
|---|---|
| *slower* / *faster* | `requested_tempo_bpm`, then re-measure — the delivered tempo will still not be the asked one |
| *darker* / *warmer* / *bigger* | style tags; keep the lyrics fixed so only one thing varies |
| *the second verse is wordy* | that section's lines only; regenerate |
| *lose the vocal in the intro* | an `[instrumental]` section at the front |
| *try again* | same everything, new seed |
| *that's it* | `decide()`, write the cast-style verdict, checkpoint |

Anything outside this vocabulary: ask in plain words rather than guessing. If a
phrase recurs, add it here.

**Keep one thing varying per round.** Changing the style and the lyrics
together produces a different song, not a better one, and there is no way to
tell which change did it.

---

## presents

```
"Wake The Brass" — cinematic synthwave, female vocals    take 2 of 3

  [verse]    0.00-2.96  The gears begin to turn            Heroine
             2.96-4.84  and the dust remembers light       Heroine
  [chorus]   4.84-7.36  WAKE THE BRASS                     Heroine
             7.36-9.53  wake the light                     Machinist
  [instrumental] 9.53-17.53

  20.0s   asked 110 BPM -> delivered 112.3   grid: strong (38 beats)

  Play it. Then: keep it, change something, or another take?
```

Ask exactly one question and stop.

## send-back

A rejection re-runs generation and re-measures. It **keeps** the `song`
artifact's words unless the words are what was rejected, and keeps every
previous round in the loop session — a take that was rejected is still evidence
about what the user wants.

Rejecting *after* the scene plan exists is more expensive: a new track has a
new grid, so the scene boundaries no longer land on beats. Say so before
regenerating, and re-run the scene plan's timing pass afterwards.

---

## traps

**Never time anything from `requested_tempo_bpm`.** It is recorded so the gap
stays visible, and for no other purpose.

**A `weak` grid is not a broken track.** Calm music genuinely has no pulse to
cut to. Pacing by phrase is the right answer, not a worse one.

**Lyrics need times before export.** `apply_song_to_session` places lines by
overlap with each segment; lines without times are silently unplaceable and it
will tell you so. Run step 4 before step 5 of the film.

**The singer's name must match a cast character.** Otherwise the Builder has
nothing to resolve it against. Whether names alone are enough, or ids are
needed, is QUESTIONS Q4 — unanswered, so check the Builder after the first
two-singer export.
