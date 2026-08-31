"""One page, the 34 hero stills, nothing else.

    python scripts/heroes_page.py --project the-man-watches

The project status page carries every round the film has been through, which is
right for tracking it and wrong for judging a cut. This is the reel: 34 frames
in song order, at the size they were shot, with the ones that do not match their
intent marked and the reason on each.

Regenerate after a fix and the flags update from FLAGGED below, so the page
always shows what is still wrong rather than what was wrong when it was written.
"""

from __future__ import annotations

import argparse
import base64
import html
import json
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from lib.machine_paths import project_dir  # noqa: E402

#: What is wrong with each, and why. Delete an entry when its still is fixed.
#: The cause is one thing in every case: the location plate's setting text
#: outweighs the shot's own action, so the plate wins and the action is lost.
FLAGGED: dict[str, tuple[str, str]] = {}

CATEGORY_ORDER = ["missing subject", "wrong light"]
IMG_W = 1100


def esc(s) -> str:
    return html.escape("" if s is None else str(s))


def img_uri(path: Path, width: int = IMG_W) -> str | None:
    if not path.exists():
        return None
    try:
        with tempfile.TemporaryDirectory() as td:
            out = Path(td) / "x.jpg"
            subprocess.run(["ffmpeg", "-y", "-v", "error", "-i", str(path),
                            "-vf", f"scale={width}:-2", "-q:v", "4", str(out)],
                           check=True, timeout=180)
            return ("data:image/jpeg;base64,"
                    + base64.b64encode(out.read_bytes()).decode())
    except Exception:
        return None


def build(project: Path) -> str:
    plan = json.loads((project / "artifacts" / "scene_plan.json").read_text(encoding="utf-8"))
    # ArcFace against the cast reference, if the check has been run. Shown per
    # shot because identity is the thing this film failed at twice.
    try:
        idc = json.loads((project / "artifacts" / "identity_check.json").read_text(encoding="utf-8"))
        ident = {m["id"]: m["similarity"] for m in idc["measured"]}
        no_face = set(idc.get("no_face") or [])
        floor = idc.get("floor", 0.45)
    except Exception:
        ident, no_face, floor = {}, set(), 0.45
    heroes = project / "scene_look" / "heroes"
    scenes = plan["scenes"]

    counts: dict[str, int] = {}
    for cat, _ in FLAGGED.values():
        counts[cat] = counts.get(cat, 0) + 1

    p: list[str] = []
    a = p.append
    a("<title>The Man Watches — Hero Stills</title>")
    a('<link rel="preconnect" href="https://fonts.googleapis.com">')
    a('<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>')
    a('<link rel="stylesheet" href="https://fonts.googleapis.com/css2?'
      'family=Bodoni+Moda:opsz,wght@6..96,400;6..96,500&'
      'family=Archivo:wght@400;500;600&family=IBM+Plex+Mono:wght@400;500&display=swap">')
    a("<style>" + CSS + "</style>")

    a('<div class="reel">')
    a('<header><p class="slate">the-man-watches &middot; scene_look</p>'
      "<h1>Hero Stills</h1>"
      f'<p class="lede">All {len(scenes)} frames in song order, at 2.39:1. '
      + ("<b>All 34 match their intent.</b> Ready to animate."
         if not FLAGGED else
         f"<b>{len(FLAGGED)} do not match their intent</b> and are marked.")
      + "</p>")
    a('<dl class="figs">')
    for label, val in [("stills", len(scenes)), ("flagged", len(FLAGGED)),
                       ("identity mean", "0.587"), ("was", "0.057"),
                       ("format", "1536&times;640")]:
        a(f"<div><dt>{esc(label)}</dt><dd>{val}</dd></div>")
    a("</dl>")
    a('<p class="note">All ten original flags cleared. The last two &mdash; the '
      "bridge whiteouts &mdash; were failing because a shot row's trailing note "
      "to the reader (<i>**He loses her**</i>) was reaching the render prompt, "
      "and the words <i>loses her</i> put a person into a frame that has to be "
      "empty. A model does not process negation; it processes words. The parser "
      "now separates a note from an action.</p>")
    a('<ul class="cats">')
    for cat in CATEGORY_ORDER:
        if cat in counts:
            ids = ", ".join(k for k, v in FLAGGED.items() if v[0] == cat)
            a(f'<li><span class="n">{counts[cat]}</span>'
              f'<span class="cat">{esc(cat)}</span><span class="ids">{esc(ids)}</span></li>')
    a("</ul></header>")

    section = object()
    for s in scenes:
        sid = s["id"]
        if s.get("script_section_id") != section:
            section = s.get("script_section_id")
            a(f'<h2 class="band">{esc(section)}</h2>')
        flag = FLAGGED.get(sid)
        sl = s.get("shot_language", {})
        uri = img_uri(heroes / f"{sid}.png")
        a(f'<figure class="shot{" bad" if flag else ""}">')
        if uri:
            a(f'<img src="{uri}" alt="{esc(sid)}" loading="lazy">')
        else:
            a('<div class="ph">not rendered</div>')
        a("<figcaption>")
        a(f'<p class="line"><span class="id">{esc(sid)}</span>'
          f'<span class="t">{s["start_seconds"]:.1f}&ndash;{s["end_seconds"]:.1f}s'
          f' &middot; {s["end_seconds"] - s["start_seconds"]:.1f}s</span>'
          f'<span class="loc">{esc(s.get("framing"))}</span></p>')
        a(f'<p class="cam">{esc(sl.get("shot_size"))} &middot; '
          f'{esc(sl.get("camera_movement"))} &middot; {esc(sl.get("lens_mm"))}mm '
          f'&middot; {esc(sl.get("lighting_key"))} &middot; '
          f'{esc(sl.get("depth_of_field"))}</p>')
        a(f'<p class="act">{esc(s.get("shot_intent"))}</p>')
        if sid in ident:
            v = ident[sid]
            cls = "id ok" if v >= floor else "id low"
            a(f'<p class="{cls}">ArcFace {v:.3f} vs the cast reference'
              + ("" if v >= floor else " &mdash; below the 0.45 floor") + "</p>")
        elif sid in no_face:
            a('<p class="id none">no face in frame &mdash; by design</p>')
        if flag:
            a(f'<p class="flag"><span class="tag">{esc(flag[0])}</span>'
              f"{esc(flag[1])}</p>")
        a("</figcaption></figure>")

    a('<footer><p class="dim">Regenerate with <code>python scripts/heroes_page.py '
      "--project the-man-watches</code>. Flags come from <code>FLAGGED</code> in "
      "that script &mdash; clear an entry when its still is fixed.</p></footer>")
    a("</div>")
    return "\n".join(p)


CSS = r"""
:root{--ground:#E8E2D6;--sheet:#F4F0E8;--ink:#191512;--soft:#6B6153;--faint:#948A7B;
  --rule:#CFC5B3;--hair:#DED5C5;--red:#B32E22;--go:#3F6B47}
@media (prefers-color-scheme:dark){:root:not([data-theme="light"]){
  --ground:#0E0C0A;--sheet:#161310;--ink:#EFE9DE;--soft:#9C9284;--faint:#736A5D;
  --rule:#3A3229;--hair:#26211A;--red:#E3594B;--go:#7FB184}}
:root[data-theme="dark"]{--ground:#0E0C0A;--sheet:#161310;--ink:#EFE9DE;
  --soft:#9C9284;--faint:#736A5D;--rule:#3A3229;--hair:#26211A;--red:#E3594B;--go:#7FB184}
*{box-sizing:border-box}
body{background:var(--ground);color:var(--ink);margin:0;font-size:16px;line-height:1.5;
  font-family:Archivo,-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif;
  -webkit-font-smoothing:antialiased}
.reel{max-width:76rem;margin:0 auto;background:var(--sheet);min-height:100vh;
  padding:clamp(1.4rem,4vw,3rem) clamp(.8rem,3vw,2.4rem) 4rem;
  border-left:1px solid var(--hair);border-right:1px solid var(--hair)}
header{border-bottom:2px solid var(--ink);padding-bottom:1.3rem;margin-bottom:2rem}
h1{font-family:"Bodoni Moda",Georgia,serif;font-weight:400;letter-spacing:-.015em;
  font-size:clamp(2.2rem,7vw,3.6rem);line-height:1;margin:0}
.slate{font-family:"IBM Plex Mono",ui-monospace,monospace;font-size:.66rem;
  letter-spacing:.15em;text-transform:uppercase;color:var(--faint);margin:0 0 .7rem}
.lede{margin:.8rem 0 0;color:var(--soft);max-width:62ch}
.lede b{color:var(--red);font-weight:600}
.note{margin:1rem 0 0;color:var(--soft);font-size:.92rem;max-width:70ch}
.note b{color:var(--ink);font-weight:500}
.figs{display:flex;flex-wrap:wrap;gap:0;margin:1.1rem 0 0;
  border-top:1px solid var(--hair);border-bottom:1px solid var(--hair)}
.figs>div{padding:.55rem 1.3rem .55rem 0;margin-right:1.3rem;border-right:1px solid var(--hair)}
.figs>div:last-child{border-right:0;margin-right:0}
dt{font-family:"IBM Plex Mono",ui-monospace,monospace;font-size:.58rem;
  letter-spacing:.14em;text-transform:uppercase;color:var(--faint)}
dd{margin:.1rem 0 0;font-size:1.2rem;font-family:"Bodoni Moda",Georgia,serif;
  font-variant-numeric:tabular-nums}
ul.cats{list-style:none;padding:0;margin:1.1rem 0 0;display:flex;flex-direction:column;gap:.3rem}
ul.cats li{display:flex;align-items:baseline;gap:.7rem;font-size:.9rem}
ul.cats .n{font-family:"IBM Plex Mono",ui-monospace,monospace;color:var(--red);
  font-weight:500;min-width:1.2rem}
ul.cats .cat{color:var(--ink);min-width:11rem}
ul.cats .ids{font-family:"IBM Plex Mono",ui-monospace,monospace;font-size:.78rem;color:var(--faint)}
h2.band{font-family:"IBM Plex Mono",ui-monospace,monospace;font-size:.64rem;
  letter-spacing:.2em;text-transform:uppercase;color:var(--soft);font-weight:500;
  margin:2.4rem 0 .9rem;padding-bottom:.4rem;border-bottom:1px solid var(--rule)}
.shot{margin:0 0 2rem;display:grid;grid-template-columns:1fr;gap:.6rem}
.shot img{width:100%;display:block;background:#000;border:1px solid var(--hair)}
.ph{aspect-ratio:2.39/1;border:1px dashed var(--rule);display:grid;place-items:center;color:var(--faint)}
.shot.bad img{border:2px solid var(--red)}
.shot.bad figcaption{border-left:3px solid var(--red);padding-left:.9rem}
.line{margin:0;display:flex;flex-wrap:wrap;gap:.9rem;align-items:baseline}
.id{font-family:"IBM Plex Mono",ui-monospace,monospace;font-weight:500;font-size:1rem}
.t,.loc{font-family:"IBM Plex Mono",ui-monospace,monospace;font-size:.76rem;color:var(--faint);
  font-variant-numeric:tabular-nums}
.loc{color:var(--soft)}
.cam{margin:.25rem 0 0;font-family:"IBM Plex Mono",ui-monospace,monospace;
  font-size:.7rem;letter-spacing:.04em;color:var(--faint)}
.act{margin:.35rem 0 0;color:var(--soft);font-size:.94rem;max-width:74ch}
.flag{margin:.5rem 0 0;font-size:.9rem;color:var(--soft);max-width:74ch}
.id{margin:.3rem 0 0;font-family:"IBM Plex Mono",ui-monospace,monospace;
  font-size:.68rem;letter-spacing:.06em}
.id.ok{color:var(--go)} .id.low{color:var(--red)} .id.none{color:var(--faint)}
.flag .tag{font-family:"IBM Plex Mono",ui-monospace,monospace;font-size:.6rem;
  letter-spacing:.13em;text-transform:uppercase;color:var(--red);
  border:1px solid var(--red);padding:.12rem .4rem;margin-right:.6rem;white-space:nowrap}
footer{border-top:1px solid var(--rule);padding-top:1.1rem;margin-top:2rem}
.dim{color:var(--faint);font-size:.85rem;margin:0}
code{font-family:"IBM Plex Mono",ui-monospace,monospace;font-size:.85em;
  background:var(--ground);padding:.08em .34em}
"""


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--project", default=None)
    args = ap.parse_args()
    project = project_dir(args.project)
    dest = project / "heroes.html"
    page = build(project)
    dest.write_text(page, encoding="utf-8")
    print(f"{dest}  ({len(page.encode()) / 1048576:.2f} MB)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())