"""Keep the frames a video model actually obeyed, and spend them over the slot.

    .venv/Scripts/python.exe scripts/stretch_clip.py --project the-man-watches --only sc02
    .venv/Scripts/python.exe scripts/stretch_clip.py --project the-man-watches --only sc31 --keep 81 --dry-run

Why this exists
---------------

Wan 2.2 i2v obeys a motion cue for about **81 frames** - one training window.
Past it the cue is spent and the model generates plausible new motion, which for
a subject with an obvious axis means going back the way it came. `The Man
Watches` sc02 approached cleanly to frame ~80, then U-turned, receded to frame
~144, turned again and came back. Nothing errored; the clip was the right
length, correctly graded and dead (QUESTIONS.md Q9).

No prompt reaches this. Stating one direction, locking the camera off and naming
the reversal in the negative all helped the first 80 frames and changed nothing
after them. So instead of asking for a long clip, keep the window that obeyed
and stretch it to fill the slot.

The trade is real and worth saying: the motion becomes slower than life. On a
long lens at distance that reads as distance and is often the better shot - a
truck taking 13 s to cross what it crossed in 5. On a shot whose speed carries
meaning it will read as slow motion, and the right answer there is a shorter
slot, not this.

Two things that cost time when this was done by hand
----------------------------------------------------

`minterpolate` cannot extrapolate past its last input frame. Ask for exactly the
frames you need and it returns a few short - a gap in the film, silently. So
overshoot the factor and trim to an exact count.

The clip this replaces is never deleted. It goes to `scene_look/` next to the
window it came from, because a shot that has been through this is no longer a
straight render and the ledger has to be able to say so.
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from lib.machine_paths import project_dir  # noqa: E402

FPS = 16
KEEP = 81          # Wan 2.2's training window
OVERSHOOT = 1.054  # ask for ~5% more than needed, then trim. See the docstring.


def probe(clip: Path) -> tuple[int, float]:
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-select_streams", "v:0",
         "-show_entries", "stream=nb_frames", "-show_entries", "format=duration",
         "-of", "json", str(clip)], capture_output=True, text=True, check=True)
    d = json.loads(out.stdout)
    return int(d["streams"][0]["nb_frames"]), float(d["format"]["duration"])


def run(cmd: list[str]) -> None:
    subprocess.run(cmd, check=True, capture_output=True)


def stretch(src: Path, dest: Path, keep: int, want_frames: int, tmp: Path) -> None:
    """Take `keep` frames off the front of src and spread them over want_frames."""
    run(["ffmpeg", "-y", "-v", "error", "-i", str(src),
         "-vf", f"select='lt(n\\,{keep})',setpts=N/{FPS}/TB",
         "-frames:v", str(keep), "-c:v", "libx264", "-crf", "12",
         "-pix_fmt", "yuv420p", str(tmp)])
    factor = want_frames / keep * OVERSHOOT
    run(["ffmpeg", "-y", "-v", "error", "-i", str(tmp),
         "-vf", f"setpts={factor:.5f}*PTS,minterpolate=fps={FPS}:mi_mode=mci:"
                "mc_mode=aobmc:me_mode=bidir:vsbmc=1",
         "-frames:v", str(want_frames), "-c:v", "libx264", "-crf", "12",
         "-pix_fmt", "yuv420p", str(dest)])


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--project", default=None)
    ap.add_argument("--only", nargs="+", required=True, help="scene ids")
    ap.add_argument("--keep", type=int, default=KEEP,
                    help=f"frames to keep off the front (default {KEEP}, "
                         "Wan 2.2's training window)")
    ap.add_argument("--force", action="store_true",
                    help="stretch a clip that has already been stretched once")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    project = project_dir(args.project)
    plan = json.loads((project / "artifacts" / "scene_plan.json").read_text(encoding="utf-8"))
    by_id = {s["id"]: s for s in plan["scenes"]}
    video = project / "assets" / "video"
    keepdir = project / "scene_look"
    ledger = project / "artifacts" / "shoot_log.jsonl"

    # Which scenes have been through this already. Stretching a stretched clip
    # takes the first 81 frames of footage that is ALREADY slowed - about two
    # seconds of original motion smeared over the whole slot - and the result
    # looks plausible, which is what makes it dangerous. The ledger is the only
    # record that a clip is derived rather than rendered.
    stretched = set()
    if ledger.is_file():
        for line in ledger.read_text(encoding="utf-8").splitlines():
            try:
                row = json.loads(line)
            except ValueError:
                continue
            if row.get("derived_from"):
                stretched.add(row.get("id"))

    rc = 0
    for sid in args.only:
        s = by_id.get(sid)
        if not s:
            print(f"{sid}: not in the plan")
            rc = 1
            continue
        clip = video / f"{sid}.mp4"
        if not clip.is_file():
            print(f"{sid}: no clip at {clip}")
            rc = 1
            continue

        if sid in stretched and not args.force:
            print(f"{sid}: the ledger says this clip is already derived from a "
                  "stretched window - refusing. Re-render it first, or pass "
                  "--force if you know the ledger is wrong.")
            continue

        have, _ = probe(clip)
        want_s = s["end_seconds"] - s["start_seconds"]
        # Snap up, exactly as render_shots does: a clip short of its slot is a
        # hole in the film, a frame over is trimmed by the timeline.
        want_frames = int(want_s * FPS + 1)
        want_frames += (-(want_frames - 1)) % 4

        if have < args.keep:
            print(f"{sid}: only {have} frames, fewer than the {args.keep} to keep "
                  "- nothing to do")
            continue
        if args.keep >= want_frames:
            print(f"{sid}: {args.keep} frames already covers the "
                  f"{want_s:.2f} s slot - nothing to do")
            continue

        factor = want_frames / args.keep
        print(f"{sid}: {have}f -> keep {args.keep}f, stretch x{factor:.2f} "
              f"-> {want_frames}f = {want_frames / FPS:.2f} s "
              f"(slot {want_s:.2f} s)")
        if args.dry_run:
            continue

        source = keepdir / f"{sid}_window{args.keep}_source.mp4"
        before = keepdir / f"{sid}_before_stretch.mp4"
        shutil.copyfile(clip, before)
        stretch(clip, video / f"{sid}.tmp.mp4", args.keep, want_frames, source)
        (video / f"{sid}.tmp.mp4").replace(clip)

        got, dur = probe(clip)
        ok = got == want_frames and dur >= want_s
        print(f"   -> {got}f, {dur:.2f} s" + ("" if ok else "   !! SHORT OF SLOT"))
        if not ok:
            rc = 1

        with ledger.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps({
                "ok": ok, "id": sid, "engine": "wan_i2v + ffmpeg minterpolate",
                "platform": "wsl + cpu", "frames": got,
                "clip_seconds": round(dur, 2), "shot_seconds": round(want_s, 2),
                "derived_from": f"the first {args.keep} frames of a {have}-frame render",
                "note": "Wan's motion cue expires at about one training window; "
                        "the window that obeyed was stretched to fill the slot "
                        "(QUESTIONS.md Q9).",
                "source_clip": str(source.relative_to(project)),
                "reference_clip": str(before.relative_to(project)),
            }) + "\n")
    return rc


if __name__ == "__main__":
    raise SystemExit(main())
