"""Does the film's timing actually hold, from the song through to the Builder?

    .venv/Scripts/python.exe scripts/audit_timing.py --project the-man-watches \
        --folder "C:\\...\\output\\TheManWatches"

Three layers have to agree and each was written by a different step:

    beat_map      measured from the delivered track
    song          section boundaries, aligned to that track
    scene_plan    34 scenes, retimed onto those boundaries
    session       what the Builder will actually cut to

A disagreement anywhere puts every later shot out by a growing margin - which is
the defect that put three invisible shots in the first film. This checks each
join rather than trusting that the step before did it right.

It reports and changes nothing.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from lib.machine_paths import project_dir  # noqa: E402

TOL = 0.02          # seconds; below this is float noise, not drift
BEAT_TOL = 0.12     # a cut this close to a beat reads as on it


def load(p: Path):
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return None


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--project", default=None)
    ap.add_argument("--folder", help="Builder project folder, to check the session too")
    args = ap.parse_args()

    project = project_dir(args.project)
    song = load(project / "artifacts" / "song.json") or {}
    beats = load(project / "artifacts" / "beat_map.json") or {}
    plan = load(project / "artifacts" / "scene_plan.json") or {}
    scenes = plan.get("scenes") or []
    sections = song.get("sections") or []
    grid = beats.get("beats") or []

    problems: list[str] = []
    print(f"track {beats.get('duration_seconds')} s, {beats.get('tempo_bpm')} BPM "
          f"measured, {len(grid)} beats\n")

    # --- 1. the plan covers the track, with no gaps and no overlaps --------
    print("1. scene plan continuity")
    if scenes:
        if abs(scenes[0]["start_seconds"]) > TOL:
            problems.append(f"the film starts at {scenes[0]['start_seconds']}, not 0")
        end = scenes[-1]["end_seconds"]
        want = beats.get("duration_seconds")
        if want and abs(end - want) > TOL:
            problems.append(f"the film ends at {end}, the track at {want}")
        gaps = 0
        for a, b in zip(scenes, scenes[1:]):
            d = b["start_seconds"] - a["end_seconds"]
            if abs(d) > TOL:
                gaps += 1
                problems.append(f"{a['id']} ends {a['end_seconds']:.2f}, "
                                f"{b['id']} starts {b['start_seconds']:.2f} ({d:+.2f})")
        print(f"   {len(scenes)} scenes, 0.00 -> {end:.2f} s, {gaps} gap(s)")
    print()

    # --- 2. each section's scenes fill exactly that section ---------------
    print("2. scenes against song sections")
    by_section: dict[str, list] = {}
    for s in scenes:
        by_section.setdefault(s.get("script_section_id"), []).append(s)
    used = []
    for sec in sections:
        label = sec["label"]
        group = [s for s in scenes
                 if s["start_seconds"] >= sec["start_seconds"] - TOL
                 and s["end_seconds"] <= sec["end_seconds"] + TOL]
        span = (group[-1]["end_seconds"] - group[0]["start_seconds"]) if group else 0
        real = sec["end_seconds"] - sec["start_seconds"]
        ok = abs(span - real) <= TOL and group
        used.append(len(group))
        mark = "  " if ok else "!!"
        print(f"   {mark} {label:12} {sec['start_seconds']:7.2f}-{sec['end_seconds']:7.2f} "
              f"({real:5.2f}s)  {len(group):2} scenes covering {span:5.2f}s")
        if not ok:
            problems.append(f"section {label}: scenes cover {span:.2f}s of {real:.2f}s")
    if sum(used) != len(scenes):
        problems.append(f"{len(scenes) - sum(used)} scene(s) fall outside every section")
    print()

    # --- 3. do the cuts land on beats -------------------------------------
    print("3. cuts against the beat grid")
    if grid:
        offs = []
        for s in scenes[1:]:
            t = s["start_seconds"]
            near = min(grid, key=lambda b: abs(b - t))
            offs.append(abs(near - t))
        on = sum(1 for o in offs if o <= BEAT_TOL)
        print(f"   {on}/{len(offs)} cuts within {BEAT_TOL}s of a beat, "
              f"worst {max(offs):.2f}s, median {sorted(offs)[len(offs)//2]:.2f}s")
        if on < len(offs) * 0.5:
            problems.append(f"only {on} of {len(offs)} cuts land on a beat - the plan "
                            "was scaled to section lengths, not snapped to beats")
    print()

    # --- 4. the Builder agrees --------------------------------------------
    if args.folder:
        print("4. Builder session against the plan")
        sess = load(Path(args.folder) / "vrgdg_builder_session.json") or {}
        segs = sess.get("segments") or []
        print(f"   {len(segs)} segments, audio_duration {sess.get('audio_duration')}")
        bad = 0
        for s, seg in zip(scenes, segs):
            for key, want in (("start", s["start_seconds"]), ("end", s["end_seconds"])):
                got = seg.get(key)
                if got is None or abs(float(got) - want) > TOL:
                    bad += 1
                    if bad <= 5:
                        print(f"   !! {s['id']} {key}: plan {want:.2f}, session {got}")
        if bad:
            problems.append(f"{bad} segment boundary/ies disagree with the plan")
        else:
            print("   every segment matches the plan")
        print()

    print("=" * 62)
    if problems:
        print(f"{len(problems)} problem(s):")
        for p in problems[:12]:
            print(f"  - {p}")
    else:
        print("timing holds: plan covers the track, sections are filled, "
              "the Builder agrees.")
    return 1 if problems else 0


if __name__ == "__main__":
    raise SystemExit(main())
