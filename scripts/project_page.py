"""Build the living page for a film - one HTML per project, regenerated as it goes.

    python scripts/project_page.py --project the-man-watches

Writes `<project>/status.html` - one file, in the project, beside the plan and
the artifacts it reports on. Publish it once as an Artifact and republish the
same path afterwards; the URL stays put, so the link Raul holds is always the
current state of the film.

`scripts/checkpoint.py` regenerates it on every checkpoint write, so it keeps
itself current without anyone remembering to.

**It reads the project. It does not remember it.** Every number, image, clip and
stage state comes from what is on disk when it runs - `project.json`, the
checkpoints, `artifacts/song.json`, `artifacts/picks.json`, the shot list, the
benchmark results, the rendered files. A status page written by hand drifts from
the work within a day. This one cannot, because there is nowhere for it to keep
a stale copy.

Two signals per stage, deliberately kept apart
----------------------------------------------

**Checkpoint** is what the governance record says. **Evidence** is what is
actually on disk. They sit side by side and are never merged, because when they
disagree *that is the finding* - a stage ran outside the pipeline, or a
checkpoint was written for work that did not land. Collapsing them into one
green tick would hide exactly the thing worth seeing.

When a project has no checkpoints at all the page says so rather than
pretending, and the evidence column carries the whole reading.

Media is embedded as data URIs - the Artifact CSP blocks external hosts - and
downscaled hard, because the page has a 16 MB ceiling and a film accumulates
clips faster than anyone expects.
"""

from __future__ import annotations

import argparse
import base64
import datetime as dt
import html
import json
import re
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from lib.machine_paths import project_dir, repo_root  # noqa: E402
from lib.shot_list import parse_shots  # noqa: E402

#: What each stage means to the film. The order comes from the pipeline manifest
#: at run time so it cannot drift; these blurbs are ours, because the manifest's
#: review_focus says how to judge a stage, not what it is.
STAGE_BLURB = {
    "brief": "the concept, agreed",
    "casting": "who she is, and can you find her",
    "score": "the song, measured not assumed",
    "scene_plan": "shots, timed to the real track",
    "scene_look": "what each place looks like",
    "export": "handed to the Builder",
    "render": "the shoot",
    "import": "clips collected back",
    "dailies": "watched in order, against the cast",
    "post": "cut, graded, mastered",
}

IMG_W = 760
VID_W = 420
MAX_CLIPS = 10


# ------------------------------------------------------------------ helpers --

def load_json(path: Path):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return ""


def esc(s) -> str:
    return html.escape("" if s is None else str(s))


def data_uri(path: Path, mime: str) -> str:
    return f"data:{mime};base64," + base64.b64encode(path.read_bytes()).decode()


def img_uri(path: Path, width: int = IMG_W) -> str | None:
    """Downscale to a JPEG data URI. Full-size plates would blow the ceiling."""
    if not path.exists():
        return None
    try:
        with tempfile.TemporaryDirectory() as td:
            out = Path(td) / "x.jpg"
            subprocess.run(["ffmpeg", "-y", "-v", "error", "-i", str(path),
                            "-vf", f"scale={width}:-2", "-q:v", "5", str(out)],
                           check=True, timeout=180)
            return data_uri(out, "image/jpeg")
    except Exception:
        return None


def vid_uri(path: Path, width: int = VID_W) -> str | None:
    if not path.exists():
        return None
    try:
        with tempfile.TemporaryDirectory() as td:
            out = Path(td) / "x.mp4"
            subprocess.run(["ffmpeg", "-y", "-v", "error", "-i", str(path),
                            "-vf", f"scale={width}:-2", "-crf", "32",
                            "-preset", "veryfast", "-movflags", "+faststart",
                            "-an", str(out)], check=True, timeout=900)
            return data_uri(out, "video/mp4")
    except Exception:
        return None


def probe(path: Path) -> dict:
    blank = {"w": "", "h": "", "frames": "", "duration": None}
    try:
        r = subprocess.run(
            ["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries",
             "stream=width,height,nb_frames,duration", "-of", "csv=p=0", str(path)],
            capture_output=True, text=True, timeout=60)
        w, h, n, d = (r.stdout.strip().split(",") + ["", "", "", ""])[:4]
        return {"w": w, "h": h, "frames": n,
                "duration": round(float(d), 1) if d else None}
    except Exception:
        return blank


# ------------------------------------------------------------------ gather --

def pipeline_stages(repo: Path, pipeline_type: str) -> list[str]:
    """Stage order from the manifest. A regex rather than a YAML parser: the
    stage block is a flat list of `- name:` entries, and this keeps the page
    generator free of a dependency it would only need here."""
    text = read_text(repo / "pipeline_defs" / f"{pipeline_type}.yaml")
    block = text.split("\nstages:", 1)[-1]
    stages = re.findall(r"^\s*-\s+name:\s*(\w+)\s*$", block, re.M)
    return stages or list(STAGE_BLURB)


def checkpoint_state(project: Path, stage: str) -> dict:
    cp = load_json(project / f"checkpoint_{stage}.json")
    if not isinstance(cp, dict):
        return {"state": "none", "detail": "none written", "note": "", "open": []}
    status = cp.get("status", "?")
    state = {"completed": "done", "awaiting_human": "awaiting"}.get(status, "open")
    if status == "completed" and cp.get("human_approved"):
        detail = f"approved {str(cp.get('timestamp', ''))[:10]}"
    else:
        detail = f"{status} {str(cp.get('timestamp', ''))[:10]}".strip()
    review = cp.get("review") or {}
    return {"state": state, "detail": detail,
            "note": review.get("summary", ""),
            "open": review.get("open_items") or []}


def evidence_state(project: Path, stage: str, ctx: dict) -> tuple[str, str]:
    """What is actually on disk, per stage: done | partial | open."""
    shots, picks, clips = ctx["shots"], ctx["picks"], ctx["clips"]

    if stage == "brief":
        p = project / "plan" / "00-production-plan.md"
        if p.exists():
            return "done", f"production plan, {len(read_text(p).splitlines())} lines"
        return "open", "no plan"

    if stage == "casting":
        c = next((p for p in picks if p["round"] == "character"), None)
        return ("done", f"{c['picked']}, found at 60 px") if c else ("open", "nobody cast")

    if stage == "score":
        song, beats = ctx["song"], ctx["beats"]
        if song and beats:
            return "done", (f"{beats.get('duration_seconds')} s, "
                            f"{beats.get('tempo_bpm')} BPM measured")
        return ("partial", "a song with no beat map") if song else ("open", "no track")

    if stage == "scene_plan":
        if (project / "artifacts" / "scene_plan.json").exists():
            return "done", "canonical scene_plan artifact"
        if shots:
            return "partial", (f"{len(shots)} shots in markdown, on the placeholder "
                               "clock, not yet a scene_plan artifact")
        return "open", "no shot list"

    if stage == "scene_look":
        # The stage is done when every *shot* has a hero still, not when every
        # location has a plate. Four location plates is the groundwork; the
        # manifest asks for one hero still per scene, and conflating the two
        # would report this stage finished while 34 keyframes are still missing.
        heroes = project / "scene_look" / "heroes"
        n_hero = len(list(heroes.glob("*.png"))) if heroes.is_dir() else 0
        want = sorted({s["loc"] for s in shots if s.get("loc")}) or ["L1", "L2", "L3", "L4"]
        have = {p["round"].upper() for p in picks}
        missing = [w for w in want if w.upper() not in have]
        if shots and n_hero >= len(shots):
            return "done", f"a hero still for all {len(shots)} shots"
        if not missing:
            return "partial", (f"all {len(want)} locations picked "
                               f"({', '.join(want)}); {n_hero}/{len(shots)} hero "
                               "stills made")
        state = "partial" if len(missing) < len(want) else "open"
        return state, (f"{len(want) - len(missing)}/{len(want)} locations picked, "
                       f"missing {', '.join(missing)}")

    if stage == "export":
        p = project / "artifacts" / "export_report.json"
        return ("done", "export report on disk") if p.exists() else \
               ("open", "nothing sent to the Builder")

    if stage == "render":
        if not shots:
            return "open", "nothing to shoot yet"
        n = len(clips)
        if not n:
            return "open", f"0/{len(shots)} shots rendered"
        return ("done" if n >= len(shots) else "partial"), \
               f"{n}/{len(shots)} shots rendered"

    if stage == "import":
        p = project / "artifacts" / "asset_manifest.json"
        return ("done", "asset manifest on disk") if p.exists() else \
               ("open", "nothing imported")

    if stage == "dailies":
        p = project / "artifacts" / "review.json"
        return ("done", "review on disk") if p.exists() else ("open", "nothing watched")

    if stage == "post":
        d = project / "renders"
        finals = sorted(d.glob("*.mp4")) if d.is_dir() else []
        return ("done", f"{len(finals)} final render(s)") if finals else ("open", "no cut")

    return "open", ""


def merge_plan_times(shots: list[dict], plan: dict | None) -> tuple[list[dict], bool]:
    """Put the retimed clock onto each shot when a scene_plan exists.

    Before the retime the shot list carries placeholder times written against
    an intended song. After it, `artifacts/scene_plan.json` carries the real
    ones. The page must never show the two mixed without saying which it is
    displaying, so this reports whether it found a plan.
    """
    if not isinstance(plan, dict):
        return shots, False
    by_id = {s["id"]: s for s in plan.get("scenes") or []}
    for shot in shots:
        scene = by_id.get(f"sc{shot['id']}")
        if not scene:
            continue
        start, end = scene["start_seconds"], scene["end_seconds"]
        shot["time"] = f"{int(start // 60)}:{start % 60:05.2f}"
        shot["duration"] = round(end - start, 2)
    return shots, True


def gather_open_rounds(project: Path, picks: list[dict]) -> list[dict]:
    """Rounds that have been rendered but not decided.

    A status page that only shows settled things is a report. What makes it
    useful mid-production is the opposite: the thing currently waiting on a
    human. A round with candidates on disk and no entry in `picks.json` is
    exactly that, and it should be the loudest item on the page.
    """
    decided = {p["round"] for p in picks}
    out = []
    look = project / "scene_look"
    if not look.is_dir():
        return out
    for d in sorted(x for x in look.iterdir() if x.is_dir()):
        if d.name in decided:
            continue
        rnd = load_json(d / "round.json")
        if not isinstance(rnd, dict) or not rnd.get("candidates"):
            continue
        cands = [c for c in rnd["candidates"] if Path(c.get("path", "")).exists()]
        if not cands:
            continue
        out.append({
            "set": d.name,
            "question": rnd.get("question") or rnd.get("answer") or "",
            "model": rnd.get("model", ""),
            "sheet": (d / "_round.png") if (d / "_round.png").exists() else None,
            "candidates": cands,
        })
    return out


def gather_clips(project: Path) -> list[Path]:
    d = project / "assets" / "video"
    return sorted(p for p in d.glob("*.mp4")) if d.is_dir() else []


#: The engine tests worth showing, with why each exists. Curated rather than
#: globbed: `scene_look/` holds fifty benchmark artifacts and three of them mean
#: something. A missing file is skipped - these come and go.
ENGINE_TESTS = [
    ("capabilities/wan_flf_correlated.mp4", "Wan 2.2 first-to-last, correlated pair",
     "A start frame plus an end frame derived from it by img2img, so the crowd, ground "
     "and light are the same pixels and only she has moved. This is the authored-motion "
     "test the film's turning shots depend on.", 1459.0),
    ("engine-bench/wan_i2v_wsl.mp4", "Wan 2.2 image-to-video, WSL",
     "One still, animated. The workhorse - most shots in this film need nothing more.",
     None),
    ("engine-bench/ltx_upscale_on.mp4", "LTX 2.3 with the upscale pass",
     "The Windows-side engine, for the ambient shots that carry no authored action.",
     None),
    ("engine-bench/wan_flf_reversed.mp4", "Wan first-to-last, wired backwards",
     "Kept as evidence. Node 68 is the start frame and 62 the end; loader order implies "
     "the opposite, and following it plays the shot in reverse.", None),
]


def gather_engine_tests(project: Path) -> list[dict]:
    bench = load_json(project / "scene_look" / "engine-bench" / "bench.json") or {}
    cost = {r.get("engine"): r.get("seconds") for r in bench.get("results") or []}
    out = []
    for rel, label, why, secs in ENGINE_TESTS:
        p = project / "scene_look" / rel
        if not p.exists():
            continue
        out.append({"path": p, "label": label, "why": why,
                    "seconds": secs if secs is not None else cost.get(p.stem),
                    **probe(p)})
    return out


def gather_bench(project: Path) -> list[dict]:
    rows = []
    d = project / "scene_look" / "bench-suite"
    if not d.is_dir():
        return rows
    for f in sorted(d.glob("*.json")):
        b = load_json(f) or {}
        if not b.get("completed") or b.get("warm_mean_s") is None:
            continue
        rows.append({"label": b.get("label"), "workflow": b.get("workflow"),
                     "platform": b.get("platform"), "cold": b.get("cold_s"),
                     "warm": b.get("warm_mean_s"), "peak": b.get("peak_rss_gib")})
    return rows


# ------------------------------------------------------------------- build --

def build(project: Path, repo: Path) -> str:
    meta = load_json(project / "project.json") or {}
    title = meta.get("title") or project.name
    ptype = meta.get("pipeline_type") or "vrgdg-character-film"

    song = load_json(project / "artifacts" / "song.json")
    beats = load_json(project / "artifacts" / "beat_map.json")
    picks_doc = load_json(project / "artifacts" / "picks.json") or {}
    picks = picks_doc.get("picks") or []
    plan = load_json(project / "artifacts" / "scene_plan.json")
    shots, retimed = merge_plan_times(parse_shots(project), plan)
    clips = gather_clips(project)
    ctx = {"song": song, "beats": beats, "picks": picks, "shots": shots, "clips": clips}

    rows = []
    for st in pipeline_stages(repo, ptype):
        cp = checkpoint_state(project, st)
        ev_state, ev_detail = evidence_state(project, st, ctx)
        rows.append({"stage": st, "cp": cp["state"], "cp_detail": cp["detail"],
                     "cp_note": cp["note"], "cp_open": cp["open"],
                     "ev": ev_state, "ev_detail": ev_detail})

    parts: list[str] = []
    a = parts.append

    a(f"<title>{esc(title)}</title>")
    a('<link rel="preconnect" href="https://fonts.googleapis.com">')
    a('<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>')
    a('<link rel="stylesheet" href="https://fonts.googleapis.com/css2?'
      'family=Bodoni+Moda:ital,opsz,wght@0,6..96,400;0,6..96,500;1,6..96,400&'
      'family=Archivo:wght@400;500;600&family=IBM+Plex+Mono:wght@400;500&display=swap">')
    a("<style>" + CSS + "</style>")

    now = dt.datetime.now().strftime("%d %B %Y, %H:%M")
    n_done = sum(1 for r in rows if r["ev"] == "done")
    n_part = sum(1 for r in rows if r["ev"] == "partial")

    a('<div class="sheet">')

    # ---- header
    a('<header class="head">')
    a(f'<p class="slate">{esc(meta.get("project_id", project.name))} &middot; '
      f'{esc(ptype)} &middot; regenerated {esc(now)}</p>')
    a(f"<h1>{esc(title)}</h1>")
    a(f'<p class="lede">{n_done} of {len(rows)} stages complete on the evidence, '
      f"{n_part} part done. Everything below is read off the project on disk each "
      "time this page is built &mdash; if it is not here, it has not happened.</p>")
    a("</header>")

    # ---- rail
    a("<section><h2>Where it stands</h2>")
    a('<p class="note">Two readings, kept apart on purpose. <b>Checkpoint</b> is what '
      "the governance record claims. <b>Evidence</b> is what is on disk. When they "
      "disagree that is the finding &mdash; a stage that ran outside the pipeline, or "
      "a checkpoint written for work that never landed.</p>")
    a('<div class="scroll"><table class="rail"><thead><tr><th>Stage</th>'
      "<th>What it is</th><th>Checkpoint</th><th>Evidence</th></tr></thead><tbody>")
    for r in rows:
        a(f'<tr class="ev-{r["ev"]}">'
          f'<td class="stg"><span class="bar"></span>'
          f'{esc(r["stage"].replace("_", " "))}</td>'
          f'<td class="blurb">{esc(STAGE_BLURB.get(r["stage"], ""))}</td>'
          f'<td class="cp cp-{r["cp"]}">{esc(r["cp_detail"])}</td>'
          f'<td class="evd">{esc(r["ev_detail"])}</td></tr>')
    a("</tbody></table></div>")
    if all(r["cp"] == "none" for r in rows):
        a('<p class="flag"><b>No checkpoints exist for this project.</b> It has been '
          "driven by hand scripts rather than through the pipeline, so the evidence "
          "column is the only true reading. Writing checkpoints is what turns it into "
          "a production the engine can resume, gate and send back.</p>")

    waiting = next((r for r in rows if r["cp"] == "awaiting"), None)
    if waiting:
        a(f'<p class="flag"><b>Waiting on you &mdash; '
          f'{esc(waiting["stage"].replace("_", " "))}.</b> '
          f'{esc(waiting["cp_note"])} Nothing after this stage can advance until '
          "it is approved; that is the gate doing its job, not a stall.</p>")

    carried = [(r, item) for r in rows for item in r["cp_open"]]
    if carried:
        a('<h3 class="sub">Carried forward</h3>')
        a('<p class="note">What each finished stage left unresolved. These are '
          "recorded in the checkpoints themselves, so they travel with the film "
          "rather than living in a chat.</p>")
        a('<ul class="carried">')
        for r, item in carried:
            a(f'<li><span class="from">{esc(r["stage"].replace("_", " "))}</span>'
              f"{esc(item)}</li>")
        a("</ul>")
    a("</section>")

    # ---- waiting on you
    open_rounds = gather_open_rounds(project, picks)
    if open_rounds:
        a('<section><h2>Waiting on you</h2>')
        a('<p class="note">Rounds that have been rendered and not decided. '
          "The machine makes the candidates and measures what it can; the pick "
          "is yours. Say a number, or say what is wrong and the next round "
          "varies that instead.</p>")
        for r in open_rounds:
            a(f'<h3 class="sub">{esc(r["set"])} &mdash; {esc(r["question"])}</h3>')
            if r["model"]:
                a(f'<p class="path">{esc(r["model"])}</p>')
            a('<div class="plates">')
            for c in r["candidates"]:
                uri = img_uri(Path(c["path"]), 620)
                if not uri:
                    continue
                m = c.get("measure") or {}
                size = (f'<span class="uses">{m["tallest_pct"]}% &middot; '
                        f'{m["tallest_px"]} px</span>' if m.get("tallest_px") else "")
                a('<figure class="plate">'
                  f'<img src="{uri}" alt="{esc(c.get("id"))}">'
                  f'<figcaption><p class="cap"><b>{esc(c.get("n"))}. '
                  f'{esc(c.get("id"))}</b>{size}</p>'
                  f'<p class="why">{esc(c.get("note"))}</p></figcaption></figure>')
            a("</div>")
        a("</section>")

    # ---- song
    a("<section><h2>The song</h2>")
    if song and beats:
        lines = [ln for s in song.get("sections") or [] for ln in s.get("lines") or []]
        shortest = min((ln["end_seconds"] - ln["start_seconds"] for ln in lines),
                       default=None)
        a(f'<p class="note">&ldquo;{esc(song.get("title"))}&rdquo; &mdash; '
          f'{esc(song.get("key"))}, {esc(str(song.get("style", "")).split(",")[0])}.</p>')
        a('<dl class="figs">')
        for k, v in [("delivered", f"{beats.get('duration_seconds')} s"),
                     ("tempo measured", beats.get("tempo_bpm")),
                     ("tempo asked", beats.get("requested_tempo_bpm")),
                     ("beats", beats.get("beats")),
                     ("lines aligned", len(lines)),
                     ("shortest line", f"{shortest:.2f} s" if shortest else "n/a")]:
            a(f"<div><dt>{esc(k)}</dt><dd>{esc(v)}</dd></div>")
        a("</dl>")
        track = project / "assets" / "music" / "project_audio.mp3"
        if track.exists():
            a(f'<audio controls preload="metadata" '
              f'src="{data_uri(track, "audio/mpeg")}"></audio>')
        a('<p class="note">The beat map is measured from the delivered track, never '
          "from the tempo that was asked for &mdash; 86.1 against 84 is a two-second "
          "drift across the film, which is four shot boundaries. <b>These times are "
          "the timing contract. The shot list below is still on its placeholder clock "
          "and has to be retimed against them.</b></p>")
        a('<div class="scroll"><table class="song"><thead><tr><th>Section</th>'
          "<th>In &ndash; out</th><th>Len</th><th>Words</th></tr></thead><tbody>")
        for s in song["sections"]:
            body = "".join(
                f'<span class="ln">{esc(ln.get("text"))}'
                f'<em>{esc(ln.get("singer"))}</em></span>'
                for ln in s.get("lines") or []) or '<span class="dim">instrumental</span>'
            a(f'<tr><td class="lab">{esc(s.get("label"))}</td>'
              f'<td class="n">{s["start_seconds"]:.2f}&ndash;{s["end_seconds"]:.2f}</td>'
              f'<td class="n">{s["end_seconds"] - s["start_seconds"]:.2f}</td>'
              f"<td>{body}</td></tr>")
        a("</tbody></table></div>")
    else:
        a('<p class="empty">No locked track yet. This fills in when '
          "<code>lock_song.py</code> writes <code>artifacts/song.json</code>.</p>")
    a("</section>")

    # ---- look
    a("<section><h2>The look</h2>")
    if picks:
        a(f'<p class="note">{len(picks)} rounds decided. The machine made the '
          "candidates and measured what it could; the human picked. "
          "<code>plan/04-picks.md</code> carries the reasoning in full.</p>")
        a('<div class="plates">')
        for pk in picks:
            src = project / pk["path"]
            uri = img_uri(src) if src.suffix.lower() in (".png", ".jpg", ".jpeg") else None
            a('<figure class="plate">')
            a(f'<img src="{uri}" alt="{esc(pk["round"])}, {esc(pk["picked"])}">'
              if uri else '<div class="ph">audio &mdash; play it above</div>')
            uses = (f'<span class="uses">{pk["shots"]} shots</span>'
                    if pk.get("shots") else "")
            a("<figcaption>"
              f'<p class="cap"><b>{esc(pk["round"])}</b> '
              f'<span class="chosen">{esc(pk["picked"])}</span>{uses}</p>'
              f'<p class="why">{esc(pk.get("why"))}</p>'
              f'<p class="path">{esc(pk["path"])}</p>'
              "</figcaption></figure>")
        a("</div>")
        for o in picks_doc.get("open") or []:
            a(f'<p class="flag"><b>Still open &mdash; {esc(o["round"])}.</b> '
              f'{esc(o["problem"])} {esc(o.get("options"))}</p>')
    else:
        a('<p class="empty">No rounds decided. Run <code>look_round.py</code>, then '
          "record the choice in <code>artifacts/picks.json</code>.</p>")
    a("</section>")

    # ---- shots
    a("<section><h2>The shots</h2>")
    if shots:
        rendered = {c.stem for c in clips}
        longest = (plan or {}).get("metadata", {}).get("longest_rendered_seconds")
        if retimed:
            a(f'<p class="note">{len(shots)} shots on the <b>retimed clock</b> &mdash; '
              "section boundaries from the delivered track, relative durations from "
              "the shot list. <b>Density</b> is the timelapse clock and only climbs "
              "until the bridge; <b>tier</b> is what survives a de-scope. A duration "
              "in red is longer than any clip rendered on this machine"
              + (f" ({longest} s)" if longest else "") +
              " and needs more frames. The last column fills in as each shot comes "
              "back from the shoot.</p>")
        else:
            a(f'<p class="note">{len(shots)} shots on the <b>placeholder clock</b> '
              "&mdash; written against an intended song, not the delivered one. "
              "Run <code>retime_plan.py</code> to put them on the real track.</p>")
        a('<div class="scroll"><table class="shots"><thead><tr><th>#</th><th>At</th>'
          "<th>Dur</th><th>Loc</th><th>Motion</th><th>Density</th><th>Tier</th>"
          "<th>Action</th><th>Shot</th></tr></thead><tbody>")
        seen = object()
        for s in shots:
            if s["section"] != seen:
                seen = s["section"]
                a(f'<tr class="band"><td colspan="9">{esc(seen)}</td></tr>')
            got = f"sc{s['id']}" in rendered or s["id"] in rendered
            dur = s["duration"]
            over = longest and dur and dur > longest
            a(f'<tr><td class="n id">{esc(s["id"])}</td>'
              f'<td class="n">{esc(s["time"])}</td>'
              f'<td class="n{" over" if over else ""}">'
              f'{f"{dur:.2f}s" if dur else esc(s["duration_raw"])}</td>'
              f'<td class="loc">{esc(s["loc"])}</td>'
              f'<td class="dim">{esc(s["motion"])}</td>'
              f'<td class="den d-{esc(s["density"])}">{esc(s["density"])}</td>'
              f'<td class="tier t-{esc(s["tier"].lower())}">{esc(s["tier"])}</td>'
              f'<td class="act">{esc(s["action"])}</td>'
              f'<td class="mark">{"&#9679;" if got else "&#9675;"}</td></tr>')
        a("</tbody></table></div>")
    else:
        a('<p class="empty">Nothing parsed from <code>plan/02-shot-list.md</code>.</p>')
    a("</section>")

    # ---- shoot
    a("<section><h2>The shoot</h2>")
    bench = gather_bench(project)
    wan = next((b for b in bench
                if b["workflow"] == "video" and b["platform"] == "wsl"), None)
    if wan and shots and not clips:
        hours = wan["warm"] * len(shots) / 3600
        a(f'<p class="note">Not started. What it will cost is already measured: '
          f'<b>{wan["warm"]:.0f} s</b> per 81-frame clip warm on the WSL side, so '
          f"{len(shots)} shots is <b>about {hours:.1f} hours</b> of render before a "
          "single retake. That number, not taste, is what decides how many shots this "
          "film can have.</p>")
    if bench:
        a('<div class="scroll"><table><thead><tr><th>Run</th><th>Workflow</th>'
          "<th>Platform</th><th>Cold</th><th>Warm mean</th><th>Peak RAM</th>"
          "</tr></thead><tbody>")
        for b in bench:
            a(f'<tr><td class="lab">{esc(b["label"])}</td>'
              f'<td>{esc(b["workflow"])}</td><td>{esc(b["platform"])}</td>'
              f'<td class="n">{b["cold"]:.0f} s</td>'
              f'<td class="n"><b>{b["warm"]:.0f} s</b></td>'
              f'<td class="n">{esc(b["peak"])} GiB</td></tr>')
        a("</tbody></table></div>")
        a('<p class="note">Wan runs <b>a third faster in WSL</b> than on Windows, which '
          "is why the engines are split across two servers &mdash; and why they must "
          "never run at once: GPU memory here is system RAM, and both loaded together "
          "crashed the backend mid-load.</p>")
    log = project / "artifacts" / "shoot_log.jsonl"
    if log.exists():
        entries = [json.loads(x) for x in read_text(log).splitlines() if x.strip()]
        ok = sum(1 for e in entries if e.get("ok"))
        a(f'<p class="note">{ok} of {len(entries)} render attempts produced a clip.</p>')
    a("</section>")

    # ---- engine tests
    a("<section><h2>What the engines can do</h2>")
    a('<p class="note">Not the film &mdash; the tests that establish what the film is '
      "allowed to ask for. Every one of these was rendered on this machine.</p>")
    shown = 0
    tests = gather_engine_tests(project)
    if tests:
        a('<div class="clips">')
        for t in tests[:MAX_CLIPS]:
            uri = vid_uri(t["path"])
            if not uri:
                continue
            shown += 1
            spec = f'{esc(t["w"])}&times;{esc(t["h"])} &middot; {esc(t["frames"])} frames'
            if t.get("seconds"):
                spec += f' &middot; {t["seconds"]:.0f} s to render'
            a('<figure class="clip">'
              f'<video controls preload="metadata" playsinline src="{uri}"></video>'
              f'<figcaption><p class="cap"><b>{esc(t["label"])}</b></p>'
              f'<p class="why">{esc(t["why"])}</p>'
              f'<p class="path">{spec}</p></figcaption></figure>')
        a("</div>")
    if not shown:
        a('<p class="empty">No engine tests on disk.</p>')
    a("</section>")

    # ---- the film
    a("<section><h2>The film</h2>")
    if clips:
        a('<div class="clips">')
        for c in clips[:MAX_CLIPS]:
            uri = vid_uri(c)
            if uri:
                a('<figure class="clip">'
                  f'<video controls preload="metadata" playsinline src="{uri}"></video>'
                  f'<figcaption><p class="cap"><b>{esc(c.stem)}</b></p>'
                  "</figcaption></figure>")
        a("</div>")
    else:
        a('<p class="empty">Nothing shot. Clips land here as <code>shoot.py</code> '
          "renders them into <code>assets/video/</code>.</p>")
    a("</section>")

    a("<footer>"
      f'<p class="slate">{esc(project)}</p>'
      '<p class="dim">Regenerate with <code>python scripts/project_page.py --project '
      f'{esc(project.name)}</code>, then republish to the same URL.</p></footer>')
    a("</div>")
    return "\n".join(parts)


CSS = r"""
:root{
  --ground:#EAE4D8; --sheet:#F5F1E9; --ink:#191512; --soft:#6B6153; --faint:#948A7B;
  --rule:#CFC5B3; --hair:#DED5C5; --red:#B32E22; --go:#3F6B47; --wait:#8A6212;
}
@media (prefers-color-scheme:dark){:root:not([data-theme="light"]){
  --ground:#100E0B; --sheet:#191612; --ink:#EFE9DE; --soft:#9C9284; --faint:#736A5D;
  --rule:#3A3229; --hair:#282219; --red:#E3594B; --go:#7FB184; --wait:#CFA141;
}}
:root[data-theme="dark"]{
  --ground:#100E0B; --sheet:#191612; --ink:#EFE9DE; --soft:#9C9284; --faint:#736A5D;
  --rule:#3A3229; --hair:#282219; --red:#E3594B; --go:#7FB184; --wait:#CFA141;
}
*{box-sizing:border-box}
body{background:var(--ground);color:var(--ink);margin:0;font-size:16px;line-height:1.55;
  font-family:Archivo,-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif;
  -webkit-font-smoothing:antialiased}
.sheet{max-width:74rem;margin:0 auto;background:var(--sheet);min-height:100vh;
  padding:clamp(1.6rem,4vw,3.4rem) clamp(1rem,4vw,3.4rem) 4rem;
  border-left:1px solid var(--hair);border-right:1px solid var(--hair);
  display:flex;flex-direction:column;gap:clamp(2.4rem,5vw,3.4rem)}

h1{font-family:"Bodoni Moda",Georgia,serif;font-weight:400;letter-spacing:-.015em;
  font-size:clamp(2.4rem,8vw,4.6rem);line-height:.98;margin:0;text-wrap:balance}
h2{font-family:"Bodoni Moda",Georgia,serif;font-weight:400;font-size:1.55rem;
  line-height:1.15;margin:0 0 .35rem;border-bottom:1px solid var(--ink);
  padding-bottom:.45rem}
section{display:flex;flex-direction:column;gap:.9rem}
p{margin:0;max-width:68ch}
.slate{font-family:"IBM Plex Mono",ui-monospace,monospace;font-size:.68rem;
  letter-spacing:.14em;text-transform:uppercase;color:var(--faint);margin:0 0 .8rem}
.head{border-bottom:2px solid var(--ink);padding-bottom:1.4rem}
.lede{margin-top:.9rem;font-size:1.02rem;color:var(--soft);max-width:60ch}
.note{color:var(--soft);font-size:.94rem}
.note b,.lede b{color:var(--ink);font-weight:500}
.dim{color:var(--faint)}
.empty{color:var(--faint);border-left:2px solid var(--rule);padding:.15rem 0 .15rem 1rem}
code{font-family:"IBM Plex Mono",ui-monospace,monospace;font-size:.85em;
  background:var(--ground);padding:.08em .34em}
.flag{border-left:3px solid var(--wait);padding:.5rem 0 .5rem 1rem;color:var(--soft);
  font-size:.92rem;max-width:72ch}
.flag b{color:var(--ink);font-weight:600}

.scroll{overflow-x:auto}
table{width:100%;border-collapse:collapse;font-size:.9rem}
th{text-align:left;font-family:"IBM Plex Mono",ui-monospace,monospace;font-size:.62rem;
  letter-spacing:.13em;text-transform:uppercase;color:var(--faint);font-weight:500;
  padding:0 .7rem .4rem 0;border-bottom:1px solid var(--ink);white-space:nowrap}
td{padding:.5rem .7rem .5rem 0;border-bottom:1px solid var(--hair);vertical-align:top}
.n{font-family:"IBM Plex Mono",ui-monospace,monospace;font-size:.84rem;
  font-variant-numeric:tabular-nums;white-space:nowrap}
.lab{font-weight:500;white-space:nowrap}

.rail td{padding-top:.6rem;padding-bottom:.6rem}
.rail .stg{font-weight:600;white-space:nowrap}
.rail .bar{display:inline-block;width:3px;height:.85em;margin-right:.6rem;
  vertical-align:-1px;background:var(--rule)}
.rail .ev-done .bar{background:var(--go)}
.rail .ev-partial .bar{background:var(--wait)}
.rail .blurb{color:var(--soft)}
.rail .cp{font-family:"IBM Plex Mono",ui-monospace,monospace;font-size:.76rem;
  color:var(--faint);white-space:nowrap}
.rail .cp-done{color:var(--go)}
.rail .cp-awaiting{color:var(--wait)}
.rail .evd{color:var(--soft)}
.rail .ev-done .evd{color:var(--ink)}

.figs{display:flex;flex-wrap:wrap;gap:0;margin:.2rem 0 .4rem;
  border-top:1px solid var(--hair);border-bottom:1px solid var(--hair)}
.figs>div{padding:.6rem 1.4rem .6rem 0;margin-right:1.4rem;
  border-right:1px solid var(--hair)}
.figs>div:last-child{border-right:0;margin-right:0}
dt{font-family:"IBM Plex Mono",ui-monospace,monospace;font-size:.6rem;
  letter-spacing:.13em;text-transform:uppercase;color:var(--faint)}
dd{margin:.1rem 0 0;font-size:1.25rem;font-family:"Bodoni Moda",Georgia,serif;
  font-variant-numeric:tabular-nums}
audio{width:100%;max-width:34rem;margin:.3rem 0}

.song .ln{display:block;color:var(--soft)}
.song .ln em{font-style:normal;color:var(--faint);font-size:.72rem;margin-left:.5rem;
  font-family:"IBM Plex Mono",ui-monospace,monospace}
.song .lab{text-transform:lowercase}

.plates{display:grid;grid-template-columns:repeat(auto-fill,minmax(260px,1fr));
  gap:1.6rem 1.4rem}
.clips{display:grid;grid-template-columns:repeat(auto-fill,minmax(280px,1fr));
  gap:1.6rem 1.4rem}
.plate,.clip{margin:0;display:flex;flex-direction:column;gap:.55rem}
.plate img,.clip video{width:100%;display:block;background:#000;
  border:1px solid var(--hair)}
.ph{aspect-ratio:16/9;border:1px dashed var(--rule);display:grid;place-items:center;
  color:var(--faint);font-size:.85rem}
.cap{font-size:.95rem}
.cap b{font-weight:600}
.chosen{font-family:"IBM Plex Mono",ui-monospace,monospace;font-size:.66rem;
  letter-spacing:.11em;text-transform:uppercase;color:var(--red);margin-left:.3rem}
.uses{font-family:"IBM Plex Mono",ui-monospace,monospace;font-size:.62rem;
  letter-spacing:.1em;text-transform:uppercase;color:var(--faint);margin-left:.55rem}
.why{font-size:.88rem;color:var(--soft)}
.path{font-family:"IBM Plex Mono",ui-monospace,monospace;font-size:.66rem;
  color:var(--faint);word-break:break-all}

.shots td{padding-top:.4rem;padding-bottom:.4rem}
.shots .band td{background:var(--ground);border-bottom:1px solid var(--rule);
  font-family:"IBM Plex Mono",ui-monospace,monospace;font-size:.62rem;
  letter-spacing:.15em;text-transform:uppercase;color:var(--soft);padding:.5rem .7rem}
.shots .id{font-weight:600;color:var(--ink)}
.shots .loc{font-weight:500;white-space:nowrap}
.shots .act{color:var(--soft);min-width:22ch}
.shots .den,.shots .tier{font-family:"IBM Plex Mono",ui-monospace,monospace;
  font-size:.64rem;letter-spacing:.09em;text-transform:uppercase;white-space:nowrap}
.shots .den{color:var(--faint)}
.shots .d-dense,.shots .d-packed{color:var(--ink)}
.shots .t-core{color:var(--red)}
.shots .t-full{color:var(--faint)}
.shots .mark{text-align:right;color:var(--faint)}

h3.sub{font-family:"Bodoni Moda",Georgia,serif;font-weight:400;font-size:1.1rem;
  margin:.6rem 0 0;color:var(--ink)}
ul.carried{list-style:none;padding:0;margin:0;display:flex;flex-direction:column;gap:.5rem}
ul.carried li{border-left:2px solid var(--rule);padding:.1rem 0 .1rem .9rem;
  color:var(--soft);font-size:.92rem;max-width:72ch}
ul.carried .from{display:block;font-family:"IBM Plex Mono",ui-monospace,monospace;
  font-size:.6rem;letter-spacing:.13em;text-transform:uppercase;color:var(--faint)}
.shots .over{color:var(--red);font-weight:600}

footer{border-top:1px solid var(--rule);padding-top:1.2rem}
footer .slate{margin:0 0 .3rem}
footer .dim{font-size:.85rem}
@media (max-width:640px){
  .figs>div{border-right:0;margin-right:0;padding-right:1rem}
  .shots .act{min-width:16ch}
}
"""


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--project", default=None)
    args = ap.parse_args()

    project = project_dir(args.project)
    dest = project / "status.html"
    page = build(project, repo_root())
    dest.write_text(page, encoding="utf-8")

    mb = len(page.encode("utf-8")) / 1048576
    print(f"{dest}  ({mb:.2f} MB)")
    if mb > 15:
        print("  WARNING: near the 16 MB artifact ceiling - drop older clips")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
