"""Render one hero still per scene, straight from the approved scene plan.

    python scripts/hero_stills.py --project the-man-watches
    python scripts/hero_stills.py --project the-man-watches --only sc15 sc21
    python scripts/hero_stills.py --project the-man-watches --dry-run

This is the `scene_look` stage's output: the still that every shot is animated
from. Identity is locked in an image first because the first film let
text-to-video re-invent the face on every clip.

It renders the `scene_plan` descriptions verbatim
--------------------------------------------------

Nothing is composed here. `retime_plan.py` already builds each description out
of the picked location plate, the shot's action, the cast, her weathering state
for that point in the week, and the shot's designed composition, angle, light,
movement and lens. Re-composing a prompt at render time would mean two places
that decide what a shot looks like, and they would disagree within a day.

If a still is wrong, the scene plan is wrong. Fix it there and re-render.

One seed per location, deliberately
-----------------------------------

Every shot in a location renders at the *same* seed, so the ground, the light
and the far edge stay the same and only what the description changes moves. That
is the reuse discipline in seed form: a week has to read as one place observed
over time, not as thirty-four unrelated images, and changing the angle or the
seed between them destroys the timelapse.

Resumable, because it is an hour of render
------------------------------------------

An existing still is skipped. Delete one to re-render it.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from lib.machine_paths import project_dir, repo_root  # noqa: E402

REPO = repo_root()
sys.path.insert(0, str(REPO / "workflows" / "image-bench"))
from graphs import MODELS, build  # noqa: E402

#: Z-Image Base: its negative branch is live, which is what holds her scale and
#: refuses the flat look. Most of the pool cannot do this at all - see
#: wiki/character/placing-her.md.
MODEL = "zImageBase"
WIDTH, HEIGHT = 1536, 640      # 2.39:1, chosen by Raul 2026-08-30
BASE_SEED = 4402

#: What every shot refuses.
COMMON = (
    "drone footage, tilt-shift, fisheye, watermark, illustration, cartoon, "
    "oversaturated, HDR, "
    "hood, hooded, cowl, robe, cloak, monk, veil, cape, "
    "pink scarf, salmon, coral, pastel, washed out colour, "
    "gaunt, emaciated, sickly, unwell, sunken eyes, hollow cheeks, grey skin, "
    "deformed hands, extra fingers, extra limbs, "
    # sc09 rendered two of her side by side. Refused by name, everywhere.
    "duplicate person, twins, two identical women, cloned figure, "
    # sc03 had one of three carriers facing back against the other two.
    "people facing opposite directions, one person walking backwards, "
    # Three people gripping one rigid object is a coordination the model
    # cannot hold - sc03 kept rendering them pulling against each other.
    # The scenario changed so nothing is shared; this refuses the shape.
    "several people carrying one object together, shared load, "
    # sc03 again: she faced camera while everyone else had their back to
    # it. One line, one direction - refuse the mixture by name.
    "some people walking toward the camera and others away, "
    "mixed directions, one person facing the opposite way, "
    # The crowd is minimal dress, not undressed. A fully nude figure in
    # the background reads as an artefact and pulls the eye off her.
    # This applies to the CROWD; the cast record governs her.
    "naked person in the crowd, fully nude figure, bare buttocks, "
    "no shorts, no trousers, undressed background figure, "
    "figures pulling against each other, tug of war, "
    "the same person twice, mirrored figure, "
    "flat lighting, snapshot, webcam, phone photo, overexposed, low contrast, "
    "muddy, dull, amateur, stock photo, harsh direct flash"
)

#: Wides additionally refuse her becoming the subject - the refusal that took
#: ten renders to find (wiki/character/placing-her.md).
WIDE_ONLY = (", portrait, close-up, foreground subject filling the frame, "
             "person facing camera, centred and static composition")

#: Close shots must NOT refuse those: they ARE portraits. Using one negative for
#: all 34 would have fought every close-up in the film - it produced a crowd
#: wide instead of a face in the L3 round, which is how this was caught.
CLOSE_ONLY = (", full body, wide shot, distant figure, tiny in frame, "
              "crowd filling the frame")

CLOSE_SIZES = {"close_up", "medium_close", "medium"}


#: The bridge whiteouts must be empty of people. A shape in them reads as the
#: watcher, and he is never in frame - the film is shot from him, not of him.
EMPTY_SHOTS = {"sc25", "sc26"}
EMPTY_ONLY = (", person, people, figure, silhouette, human, crowd, standing "
              "figure, dark shape, anyone in frame")


def negative_for(shot_size: str, shot_id: str = "") -> str:
    if shot_id in EMPTY_SHOTS:
        return COMMON + EMPTY_ONLY
    return COMMON + (CLOSE_ONLY if shot_size in CLOSE_SIZES else WIDE_ONLY)


#: Shots that must NOT share their location's seed. The bridge whiteouts kept
#: rendering a figure at centre with "no people" in the prompt AND person terms
#: in the negative - the seed's composition was putting it there and no amount
#: of wording moved it. Same-seed structure beats a negative term. A whiteout
#: has no ground detail to match across shots, so the seed rule costs nothing
#: here and is the only thing that actually empties the frame.
SEED_OVERRIDE = {"sc25": 9101, "sc26": 9102}


def seed_for(location: str, shot_id: str = "") -> int:
    """Same seed for every shot in a location, so the ground matches across the
    week - except where a shot has to break composition rather than keep it."""
    if shot_id in SEED_OVERRIDE:
        return SEED_OVERRIDE[shot_id]
    return BASE_SEED + sum(ord(c) for c in (location or "?").upper())


def render(server: str, graph: dict, dest: Path, minutes: float = 30.0) -> float | None:
    start = time.time()
    req = urllib.request.Request(f"{server}/prompt",
                                 data=json.dumps({"prompt": graph}).encode(),
                                 headers={"Content-Type": "application/json"})
    try:
        pid = json.loads(urllib.request.urlopen(req, timeout=120).read())["prompt_id"]
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode(errors="replace")
        try:
            d = json.loads(detail)
            errs = [f"node {n} ({v.get('class_type')}): {e.get('details') or e.get('message')}"
                    for n, v in (d.get("node_errors") or {}).items()
                    for e in v.get("errors") or []]
            detail = "; ".join(errs) or detail
        except Exception:
            pass
        print(f" HTTP {exc.code}: {detail[:200]}")
        return None

    while time.time() - start < minutes * 60:
        try:
            hist = json.loads(urllib.request.urlopen(
                f"{server}/history/{pid}", timeout=60).read())
            if pid in hist:
                break
        except Exception:
            pass
        time.sleep(3)
    else:
        print(f" no result after {minutes:.0f} min")
        return None

    for node in (hist[pid].get("outputs") or {}).values():
        for item in node.get("images") or []:
            q = urllib.parse.urlencode({
                "filename": item["filename"], "subfolder": item.get("subfolder", ""),
                "type": item.get("type", "output")})
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_bytes(urllib.request.urlopen(
                f"{server}/view?{q}", timeout=900).read())
            return round(time.time() - start, 1)
    print(" finished but wrote no image")
    return None


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--project", default=None)
    ap.add_argument("--server", default="http://127.0.0.1:8189")
    ap.add_argument("--only", nargs="+", help="scene ids, e.g. sc15 sc21")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    project = project_dir(args.project)
    plan = json.loads((project / "artifacts" / "scene_plan.json").read_text(encoding="utf-8"))
    scenes = plan["scenes"]
    if args.only:
        wanted = set(args.only)
        scenes = [s for s in scenes if s["id"] in wanted]

    out = project / "scene_look" / "heroes"
    out.mkdir(parents=True, exist_ok=True)
    spec = next(m for m in MODELS if m["key"] == MODEL)

    todo = [s for s in scenes if not (out / f"{s['id']}.png").exists()]
    print(f"{len(scenes)} scenes, {len(todo)} to render, "
          f"{WIDTH}x{HEIGHT} on {spec['label']}\n")
    if args.dry_run:
        for s in scenes:
            mark = " " if (out / f"{s['id']}.png").exists() else "*"
            sl = s.get("shot_language", {})
            print(f" {mark} {s['id']}  {s['framing']:3} seed {seed_for(s["framing"], s["id"])}  "
                  f"{sl.get('shot_size','?'):13} {sl.get('camera_movement','?'):14} "
                  f"{sl.get('lens_mm','?')}mm  {sl.get('lighting_key','?')}")
        return 0

    rows, failed = [], []
    for i, s in enumerate(scenes, 1):
        dest = out / f"{s['id']}.png"
        if dest.exists():
            continue
        seed = seed_for(s["framing"], s["id"])
        print(f"  [{i:2}/{len(scenes)}] {s['id']} {s['framing']:3} seed {seed} ...",
              end="", flush=True)
        size = s.get("shot_language", {}).get("shot_size", "wide")
        graph = build(spec, prompt=s["description"], negative=negative_for(size, s["id"]),
                      width=WIDTH, height=HEIGHT, seed=seed,
                      prefix=f"hero_{s['id']}")
        secs = render(args.server, graph, dest)
        print(f" {secs}s" if secs else "")
        (failed if secs is None else rows).append(s["id"])
        if secs:
            rows_entry = {"id": s["id"], "location": s["framing"], "seed": seed,
                          "seconds": secs, "path": str(dest),
                          "shot_language": s.get("shot_language", {}),
                          "start_seconds": s["start_seconds"],
                          "end_seconds": s["end_seconds"]}
            manifest = out / "heroes.json"
            existing = json.loads(manifest.read_text(encoding="utf-8")) if manifest.exists() else []
            existing = [e for e in existing if e["id"] != s["id"]] + [rows_entry]
            existing.sort(key=lambda e: e["id"])
            manifest.write_text(json.dumps(existing, indent=2), encoding="utf-8")

    # The bookend is ONE keyframe used twice. Shots 01 and 34 must be
    # frame-identical or it does not read as a bookend, and two renders of
    # similar prompts are never identical - drifting dust is exactly the thing a
    # generator will not repeat. So 34 is a copy of 01, not a render of its own.
    a, b = out / "sc01.png", out / "sc34.png"
    if a.exists():
        import shutil
        if not b.exists() or b.read_bytes() != a.read_bytes():
            shutil.copyfile(a, b)
            print("  sc34 <- sc01 (the bookend is one keyframe used twice)")

    done = len(list(out.glob("sc*.png")))
    print(f"\n{done}/34 hero stills on disk")
    if failed:
        print(f"failed: {', '.join(failed)} - re-run to retry")
    return 0 if not failed else 1


if __name__ == "__main__":
    raise SystemExit(main())
