"""Retime a shot list against the song that was actually delivered.

    python scripts/retime_plan.py --project the-man-watches
    python scripts/retime_plan.py --project the-man-watches --dry-run

Writes `artifacts/scene_plan.json` - the canonical artifact the `scene_plan`
stage produces, and the thing every later stage is generated against.

Why this exists
---------------

A shot list is written before the song exists, against intended section times.
The delivered track never matches them. `The Man Watches` planned a 24-second
first verse and got 11.92; it planned a 14-second intro and got 25.94. Cutting
the film to the planned clock would put every shot boundary in the wrong place
by a growing margin, and the error compounds - the same defect that put three
invisible sub-half-second shots in the first film.

So: the banners in the shot list map one-to-one onto the song's sections, and
each group of shots is scaled to fill its section's **measured** start and end.
Relative durations inside a section are preserved, because those carry the
intended rhythm; only the absolute clock moves.

Two gates run on the result
---------------------------

**Too short.** Nothing under `--min-seconds` (1.5 by default). Below that a shot
does not register as an image, it registers as a flicker - the failure that
made three shots of film one invisible.

**Too long.** The longest clip this machine has ever rendered is 5.06 s (81
frames at 16 fps). A shot longer than that is not blocked, but it needs more
frames, and render cost scales with frames - so it gets named rather than
discovered during the shoot.

Neither gate edits the plan. They report, because the fix is a creative decision
about which shots to split or hold, and that is the human's.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from lib.machine_paths import project_dir  # noqa: E402
from lib.shot_list import group_by_section, parse_shots  # noqa: E402

#: The longest clip actually rendered on this machine, measured not assumed:
#: `scene_look/capabilities/wan_flf_correlated.mp4`, 81 frames at 16 fps.
LONGEST_RENDERED_S = 5.06

#: `type` is not decoration - the VRGDG bridge reads it to decide which scenes
#: the cast applies to, and it only recognises `character_scene` and
#: `talking_head`. Every scene was `generated`, so the export wrote no per-scene
#: model, seed or reference at all and warned "no scene matched the cast's
#: scope". A scene she is in IS a character scene; the six she is absent from
#: are not.
SCENE_TYPE = "generated"
CHARACTER_SCENE_TYPE = "character_scene"



#: A director's pass, shot by shot. Every shot used to be extreme_wide + static
#: because the camera was a forty-foot effigy that could not move; that rule was
#: dropped 2026-08-30 and the uniformity outlived it. Lens is meaning here - the
#: truck in shot 02 never arrives because 135mm flattens approach - and movement
#: is rationed, because it costs frames and because a hold only lands when the
#: shots around it moved.
CAMERA = {'01': ('extreme_wide', 'static', 24, 'blue_hour', 'deep'), '02': ('extreme_wide', 'dolly_in', 135, 'blue_hour', 'deep'), '03': ('wide', 'tracking_left', 35, 'golden_hour', 'deep'), '04': ('wide', 'crane_down', 24, 'natural', 'deep'), '05': ('medium_wide', 'static', 50, 'natural', 'medium'), '06': ('wide', 'static', 35, 'tungsten_warm', 'medium'), '07': ('wide', 'crane_down', 24, 'golden_hour', 'deep'), '08': ('medium_close', 'static', 85, 'natural', 'shallow'), '09': ('medium_close', 'static', 85, 'tungsten_warm', 'shallow'), '10': ('extreme_wide', 'crane_up', 24, 'golden_hour', 'deep'), '11': ('wide', 'tracking_right', 50, 'golden_hour', 'medium'), '12': ('wide', 'static', 35, 'neon', 'medium'), '13': ('medium', 'tracking_left', 50, 'golden_hour', 'medium'), '14': ('wide', 'static', 50, 'golden_hour', 'medium'), '15': ('medium', 'dolly_in', 85, 'golden_hour', 'shallow'), '16': ('medium_close', 'static', 85, 'golden_hour', 'shallow'), '17': ('wide', 'static', 50, 'tungsten_warm', 'medium'), '18': ('medium', 'dolly_in', 85, 'tungsten_warm', 'shallow'), '19': ('extreme_wide', 'crane_up', 24, 'golden_hour', 'deep'), '20': ('medium_wide', 'static', 135, 'silhouette', 'shallow'), '21': ('wide', 'static', 50, 'low_key', 'medium'), '22': ('extreme_wide', 'static', 24, 'neon', 'deep'), '23': ('wide', 'whip_pan', 35, 'tungsten_warm', 'medium'), '24': ('close_up', 'dolly_in', 135, 'golden_hour', 'shallow'), '25': ('extreme_wide', 'static', 35, 'high_key', 'deep'), '26': ('wide', 'static', 50, 'high_key', 'medium'), '27': ('close_up', 'dolly_in', 135, 'overcast_soft', 'shallow'), '28': ('extreme_wide', 'crane_down', 24, 'golden_hour', 'deep'), '29': ('extreme_wide', 'static', 24, 'blue_hour', 'deep'), '30': ('wide', 'static', 50, 'rim_lit', 'medium'), '31': ('close_up', 'dolly_in', 135, 'rim_lit', 'shallow'), '32': ('wide', 'tilt_up', 35, 'low_key', 'medium'), '33': ('extreme_wide', 'static', 35, 'low_key', 'deep'), '34': ('extreme_wide', 'static', 24, 'blue_hour', 'deep')}

MOVEMENT_TEXT = {'static': 'locked off camera, no camera move', 'dolly_in': 'a slow push in, the frame closing', 'crane_up': 'the camera rising, the ground opening out below', 'crane_down': 'steep downward angle looking down on them from above', 'tracking_left': 'the camera tracking left alongside the movement', 'tracking_right': 'the camera tracking right alongside the movement', 'pan_right': 'a slow pan right across the width of it', 'whip_pan': 'a fast whip pan following them across frame', 'tilt_up': 'the camera tilting up as it rises'}

LIGHT_TEXT = {'blue_hour': 'cold blue pre-dawn light, no sun in frame', 'golden_hour': 'low golden sun raking through the dust, long shadows', 'natural': 'hard high daylight', 'tungsten_warm': 'warm tungsten work light against the dark', 'neon': 'saturated coloured light from EL wire and art cars', 'low_key': 'near darkness with one hard source, everything else black', 'high_key': 'flat blinding white, near-zero contrast, visibility gone', 'silhouette': 'backlit hard, the figures reading as shapes against the light', 'rim_lit': 'lit from below and behind, edges burning, faces in shadow', 'overcast_soft': 'flat soft light through settling dust'}



#: Where she sits in the frame, and from what height. Composition was the one
#: thing never designed - every frame came back with the subject dead centre at
#: eye level, because that is the default and nothing in the positive prompt
#: said otherwise. "Centred composition" was already in the negative and did not
#: win; the same lesson as her scale - the positive has to state it.
#:
#: Centre appears FOUR times in thirty-four shots and each is a statement: 25
#: and 26 are whiteouts where symmetry IS the emptiness, 30 is ten thousand
#: people turning to camera at once, 34 is the bookend that must match 01.
COMP = {'01': ('horizon low, empty sky filling the top two thirds', 'eye_level'), '02': ('the truck tiny on the far right third, vast empty left', 'eye_level'), '03': ('her on the left third, trucks cutting across the right', 'low_angle'), '04': ('the grid filling frame, her small and off-centre bottom left', 'high_angle'), '05': ('her on the right third, scaffold poles crossing the foreground', 'eye_level'), '06': ('her small at the edge of a pool of light, dark filling most of frame', 'low_angle'), '07': ('the same frame as 04, her in the same off-centre place', 'high_angle'), '08': ('her head and shoulders filling the left third, the effigy rising behind her out of the top of frame', 'low_angle'), '09': ('her head and shoulders filling the left third, identical framing to 08, the lit effigy behind', 'low_angle'), '10': ('the city filling the lower half, sky above, her small in the right third', 'high_angle'), '11': ('art cars sweeping across the bottom third, her high in the left third', 'low_angle'), '12': ('her on the right third seen past a foreground bicycle wheel', 'low_angle'), '13': ('the pack filling the width of frame coming straight at camera, her in the front rank slightly left of centre', 'eye_level'), '14': ('her on the right third, the crowd streaming out of the left edge', 'eye_level'), '15': ('her filling the left third, the crowd blurred behind on the right', 'low_angle'), '16': ('her face high in the frame on the right third, dust below', 'low_angle'), '17': ('her on the right third, identical placement to 14', 'eye_level'), '18': ('her on the left third, firelight raking in from frame right', 'low_angle'), '19': ('the city edge to edge, her small in the lower right third', 'high_angle'), '20': ('dancers filling the right two thirds, her silhouetted at the left edge', 'low_angle'), '21': ('the fire filling the right half, her against it on the left third', 'low_angle'), '22': ('lights filling the frame, her small and low in the centre bottom', 'high_angle'), '23': ('bikes streaking across the bottom, her still in the upper left third', 'low_angle'), '24': ('her face on the right third, crowd falling out of focus left', 'eye_level'), '25': ('dead centre, perfectly symmetrical, nothing to either side', 'eye_level'), '26': ('dead centre, symmetrical, a single shape barely resolving', 'eye_level'), '27': ('her face filling the left half of frame, dust clearing off to the right', 'low_angle'), '28': ('the crowd filling the lower two thirds, her entering from the right edge', 'high_angle'), '29': ('the ring wrapping the full width, her small in the lower left third', 'high_angle'), '30': ('dead centre, ten thousand faces filling every part of frame', 'eye_level'), '31': ('her face on the left third, fire glow filling the right', 'low_angle'), '32': ('fire rising up the right third, her small at the bottom left', 'low_angle'), '33': ('fire filling the whole frame edge to edge', 'low_angle'), '34': ('horizon low, empty sky filling the top two thirds, identical to 01', 'eye_level')}

ANGLE_TEXT = {'eye_level': 'shot from standing height', 'low_angle': 'shot from low down looking up at them, the sky behind', 'high_angle': 'shot from high up looking down across it'}



#: Ground for shots whose action needs something the location plate does not
#: contain. Six of the original ten flags cleared when the action moved ahead of
#: the setting; these could not, because "empty flat alkali desert playa"
#: actively contradicts "at the foot of a hundred-foot effigy" and "visibility
#: gone". A ground clause cannot be compressed into something it never had.
GROUND_OVERRIDE = {
    "08": "at the base of an enormous hundred-foot wooden effigy standing on open playa, its full height going up out of frame",
    "09": "at the base of an enormous hundred-foot wooden effigy standing on open playa, lit from within, its full height going up out of frame",
    # First attempt gave these NO ground, on the theory that any ground
    # contradicts a whiteout. With nothing to anchor them the model invented:
    # 25 came back an abstract blue gradient and 26 a red boat on an ocean.
    # Absence is not a description. A whiteout has to be stated as a thing that
    # is present - airborne dust - not as the absence of everything else.
    # No figure in either. A shape in the whiteout reads as the watcher, and he
    # is never in frame - the film is shot from him, not of him. My first pass
    # put "a single dark shape at the limit of visibility" into 26 and it came
    # back looking like a person standing there.
    "25": "engulfed in a wall of blowing white alkali dust filling the entire frame, no people, no figures, nothing but dust and a few feet of pale cracked ground underfoot",
    "26": "deep inside blowing white dust, completely empty, no people, no figures, no structures, only dust and a hint of pale cracked ground below",
}


def load(path: Path):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def character_shots(project: Path) -> set[str]:
    """The shots that carry the character, read from the plan's own dependency
    section rather than hard-coded here.

    Anchored to the sentence: find "carry REF_A", walk back to the nearest
    "Shots", and read the numbers between. Two earlier versions failed silently
    in opposite directions - one required a single bold run around the whole
    list and returned nobody the moment the formatting changed; the other
    reached back to the first "Shots" in the document and swallowed a table and
    the string "60 px". Returning the wrong set here drops her out of every
    scene description without an error.
    """
    try:
        text = (project / "plan" / "02-shot-list.md").read_text(encoding="utf-8")
    except OSError:
        return set()
    idx = text.find("carry REF_A")
    if idx < 0:
        return set()
    window = text[max(0, idx - 400):idx]
    pos = window.rfind("Shots")
    if pos < 0:
        return set()
    return {n.zfill(2) for n in re.findall(r"\d{1,2}", window[pos:])}


def location_settings(project: Path, picks: list[dict]) -> dict[str, str]:
    """The chosen plate's own prompt, per location.

    Two things this has to get right, both of which it got wrong first:

    A pick's round is named for the round, not the location - "l3-final", not
    "l3" - and a shot's location is "L3". Keying on the raw round name meant the
    current pick never matched and the *superseded* one did, so every L3 scene
    was quietly built from a plate that was rejected hours earlier. Superseded
    picks are skipped, and the round name is reduced to its location.

    The forty-foot elevated framing is stripped: it is baked into every plate
    prompt and stopped being the film's rule on 2026-08-30. The plates are still
    the look; only the camera changed.
    """
    # Strips both the dead POV rule and the flat documentary treatment. Both
    # are baked into plates rendered under the old concept, and both would
    # otherwise survive in every scene built on those locations.
    elevation = re.compile(
        r"(?:Elevated\s+(?:night\s+)?view\s+from\s+forty\s+feet(?:\s+(?:up|above))?"
        r"|[Ss]een\s+from\s+forty\s+feet(?:\s+(?:up|above))?"
        r"|(?:from\s+)?elevated\s+forty\s+feet"
        r"|from\s+forty\s+feet(?:\s+(?:up|above))?"
        r"|documentary\s+(?:night\s+)?photograph(?:y)?"
        r"|locked\s+off,?\s*no\s+tilt"
        r"|natural\s+colour)\s*,?\s*", re.I)

    out: dict[str, str] = {}
    for pick in picks:
        if pick.get("superseded_by"):
            continue
        # "l3-final" -> "L3", "night-v3" -> "NIGHT", "l2" -> "L2"
        loc = re.split(r"-(?:v\d+|final)$", pick["round"])[0].upper()
        rnd = load(project / "scene_look" / pick["round"] / "round.json")
        if not isinstance(rnd, dict):
            continue
        cand = next((c for c in rnd.get("candidates") or []
                     if c.get("id") == pick["picked"]), None)
        if not (cand and cand.get("prompt")):
            continue
        prompt = cand["prompt"].split(". Far from camera")[0].strip().rstrip(",.")
        prompt = elevation.sub("", prompt).strip()
        if prompt:
            prompt = prompt[0].upper() + prompt[1:]
        out[loc] = prompt
    return out


def cast_line(project: Path) -> str:
    cast = load(project / "artifacts" / "cast_record.json") or {}
    if cast.get("brief"):
        return str(cast["brief"])
    return ("a woman with long dark hair, a faux fur shrug, ornate goggles up on "
            "her head, and one long deep red scarf")


def weathering(project: Path, density: str) -> str:
    """How worn she is in this shot, keyed to the density column.

    Raul chose to weather her across the week while keeping the look. Density is
    already the film's timelapse clock - empty through packed - so the state is
    derived from it rather than tracked separately. Two clocks would disagree by
    the end of the week; one cannot.
    """
    cast = load(project / "artifacts" / "cast_record.json") or {}
    states = ((cast.get("metadata") or {}).get("weathering") or {}).get("states") or {}
    for key, text in states.items():
        if density.strip().lower() in [k.strip() for k in key.split("/")]:
            return text
    return ""


def snap_to_beats(cuts: list[float], beats: list[float], first: float,
                  last: float, min_seconds: float) -> list[float]:
    """Move interior cut points onto beats, keeping order and the floor.

    `cuts` are the interior boundaries of one section - the section's own start
    and end are fixed and are passed as `first`/`last`, because those came from
    the aligned song and are already right.

    Each cut goes to the nearest beat that is strictly after the previous
    boundary plus `min_seconds`, and leaves room for the shots after it. A beat
    grid at 86 BPM is 0.70 s, so a 1.5 s floor is roughly three beats - there is
    normally plenty of room, and where there is not the cut simply does not move
    as far as it wanted to.
    """
    inside = [b for b in beats if first < b < last]
    if not inside:
        return cuts

    out: list[float] = []
    prev = first
    for i, want in enumerate(cuts):
        remaining = len(cuts) - i - 1
        # Leave room for every shot still to come, plus the last one.
        ceiling = last - (remaining + 1) * min_seconds
        options = [b for b in inside if b >= prev + min_seconds and b <= ceiling]
        if not options:
            out.append(want)
            prev = want
            continue
        best = min(options, key=lambda b: abs(b - want))
        out.append(best)
        prev = best
    return out


def build(project: Path, min_seconds: float) -> tuple[dict, list[dict]]:
    song = load(project / "artifacts" / "song.json")
    if not song:
        raise SystemExit("no artifacts/song.json - lock the song first")
    beat_map = load(project / "artifacts" / "beat_map.json") or {}
    beats = [float(b) for b in (beat_map.get("beats") or [])]
    picks = (load(project / "artifacts" / "picks.json") or {}).get("picks") or []
    shots = parse_shots(project)
    if not shots:
        raise SystemExit("no shots parsed from plan/02-shot-list.md")

    groups = group_by_section(shots)
    sections = song["sections"]
    if len(groups) != len(sections):
        raise SystemExit(
            f"{len(groups)} shot-list sections but {len(sections)} song sections. "
            "They map one to one by order; fix the shot list's banners first.\n"
            f"  banners: {[g[0] for g in groups]}\n"
            f"  song:    {[s['label'] for s in sections]}")

    settings = location_settings(project, picks)
    her = cast_line(project)
    carries = character_shots(project)

    scenes: list[dict] = []
    findings: list[dict] = []

    for (banner, group), section in zip(groups, sections):
        real = section["end_seconds"] - section["start_seconds"]
        planned = sum(s["duration"] or 0 for s in group) or len(group)
        weights = [(s["duration"] or planned / len(group)) for s in group]
        drift = real - planned
        if abs(drift) >= 2.0:
            findings.append({
                "kind": "section drift", "section": banner,
                "detail": (f"planned {planned:.0f} s, delivered {real:.2f} s "
                           f"({drift:+.2f} s across {len(group)} shots)")})

        # Proportional cuts first - they carry the rhythm the shot list asked
        # for - then moved onto the nearest usable beat. The section's own
        # start and end never move: they came from the aligned song.
        raw: list[float] = []
        t = section["start_seconds"]
        for w in weights[:-1]:
            t += real * w / planned
            raw.append(t)
        snapped = snap_to_beats(raw, beats, section["start_seconds"],
                               section["end_seconds"], min_seconds) if beats else raw
        bounds = [section["start_seconds"], *snapped, section["end_seconds"]]

        for i, shot in enumerate(group):
            start, end = bounds[i], bounds[i + 1]
            dur = end - start

            if dur < min_seconds:
                findings.append({
                    "kind": "too short", "shot": shot["id"],
                    "detail": f"{dur:.2f} s, under the {min_seconds} s floor"})
            if dur > LONGEST_RENDERED_S:
                findings.append({
                    "kind": "longer than anything rendered", "shot": shot["id"],
                    "detail": (f"{dur:.2f} s, against {LONGEST_RENDERED_S} s max "
                               "rendered here - needs more frames, and cost "
                               "scales with frames")})

            setting = settings.get(shot["loc"], "")
            # The ground only - the first clause of the plate. The full plate is
            # a paragraph and it drowns the action; see this module's history and
            # wiki/character/placing-her.md for the two earlier times this exact
            # ratio decided the output.
            ground = setting.split(",")[0].strip() if setting else ""
            # Cut the plate's own time of day off the ground clause. L1's plate
            # says "...playa at first light", which then fights the whiteout in
            # 25/26 and the burn in 33 - the shot's own lighting_key is the
            # authority, not the plate the ground came from.
            for cut in (" at first light", " at dawn", " at midday", " at night",
                        " at sunset", " in the afternoon", " at golden hour"):
                ground = ground.replace(cut, "")
            if shot["id"] in GROUND_OVERRIDE:
                ground = GROUND_OVERRIDE[shot["id"]]

            # A description must state the character, never point at a slot -
            # "the same X" measured 0.34 identity against 0.55 for a restatement
            # (DECISIONS #29, #33). REF_A is exactly such a pointer.
            action = shot["action"]
            names_her = "REF_A" in action
            if names_her:
                action = action.replace("REF_A", her)

            size, move, lens, light, dof = CAMERA.get(
                shot["id"], ("wide", "static", 50, "natural", "medium"))
            placement, angle = COMP.get(shot["id"], ("", "eye_level"))

            # ACTION FIRST. Everything else is context for it.
            parts = [action]
            if shot["id"] in carries and not names_her:
                parts.append(f"In the frame, {her}")
            if ground:
                parts.append(ground)
            if placement:
                parts.append(placement.capitalize())
            parts.append(ANGLE_TEXT.get(angle, ""))
            parts.append(LIGHT_TEXT.get(light, ""))
            parts.append(MOVEMENT_TEXT.get(move, "locked off camera"))
            parts.append(f"shot on a {lens}mm lens, anamorphic cinematic film "
                         "still, 2.39:1, 35mm grain, volumetric light, deep "
                         "filmic contrast")
            if names_her or shot["id"] in carries:
                worn = weathering(project, shot["density"])
                if worn:
                    parts.append(worn.split(" - ", 1)[-1].capitalize())
            parts.append(f"Density: {shot['density']}")

            scenes.append({
                "id": f"sc{shot['id']}",
                "type": (CHARACTER_SCENE_TYPE
                         if (names_her or shot["id"] in carries) else SCENE_TYPE),
                "description": ". ".join(p.rstrip(".") for p in parts) + ".",
                "start_seconds": round(start, 3),
                "end_seconds": round(end, 3),
                "script_section_id": section["label"],
                "framing": shot["loc"],
                "movement": move,
                "shot_intent": shot["action"],
                "hero_moment": shot["tier"].upper() == "CORE",
                "shot_language": {
                    "shot_size": size,
                    "camera_movement": move,
                    "lens_mm": lens,
                    "lighting_key": light,
                    "depth_of_field": dof,
                },
                "texture_keywords": [shot["motion"].lower() + "-motion",
                                     shot["density"], shot["tier"].lower()],
            })

    plan = {
        "version": "1.0",
        "scenes": scenes,
        "metadata": {
            "retimed_against": "artifacts/song.json",
            "source": "plan/02-shot-list.md",
            "duration_seconds": sections[-1]["end_seconds"],
            "min_seconds_gate": min_seconds,
            "longest_rendered_seconds": LONGEST_RENDERED_S,
            "findings": findings,
            "note": ("Section boundaries come from the measured track, never from "
                     "the requested tempo. Relative durations inside a section are "
                     "the shot list's; the absolute clock is the song's."),
        },
    }
    return plan, findings


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--project", default=None)
    ap.add_argument("--min-seconds", type=float, default=1.5)
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    project = project_dir(args.project)
    plan, findings = build(project, args.min_seconds)

    print(f"{len(plan['scenes'])} scenes, "
          f"{plan['metadata']['duration_seconds']} s\n")
    for s in plan["scenes"]:
        print(f"  {s['id']}  {s['start_seconds']:7.2f} - {s['end_seconds']:7.2f}"
              f"  {s['end_seconds'] - s['start_seconds']:5.2f}s  {s['framing']:3}"
              f"  {s['script_section_id']}")

    if findings:
        print(f"\n{len(findings)} finding(s):")
        for f in findings:
            where = f.get("shot") or f.get("section")
            print(f"  [{f['kind']:34}] {where:12} {f['detail']}")
    else:
        print("\nno findings")

    if args.dry_run:
        print("\n--dry-run, nothing written")
        return 0

    dest = project / "artifacts" / "scene_plan.json"
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(json.dumps(plan, indent=2), encoding="utf-8")
    print(f"\nwritten: {dest}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
