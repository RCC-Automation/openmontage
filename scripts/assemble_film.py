"""Cut the film: every clip trimmed to its slot, joined, and the track laid over.

    .venv/Scripts/python.exe scripts/assemble_film.py --project the-man-watches

Each scene's length comes from the **plan's own boundaries**, not from the clip:
`round(end*fps) - round(start*fps)`. Taking the difference of two rounded
boundaries rather than rounding each duration is what makes the parts sum to the
whole - the cuts land exactly where the song says, and the last frame of the
film lands on the last frame of the track.

Clips are rendered a few frames longer than their slot on purpose (a clip short
of its slot is a hole; a few frames over are trimmed here), so this is where the
overshoot is taken back off.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from lib.machine_paths import project_dir  # noqa: E402

FPS = 16


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--project", default=None)
    ap.add_argument("--audio", default=None)
    ap.add_argument("--out", default=None)
    ap.add_argument("--crf", type=int, default=16)
    args = ap.parse_args()

    project = project_dir(args.project)
    plan = json.loads((project / "artifacts" / "scene_plan.json").read_text(encoding="utf-8"))
    video = project / "assets" / "video"
    audio = Path(args.audio) if args.audio else project / "assets" / "music" / "project_audio.mp3"
    out = Path(args.out) if args.out else project / "renders" / "final.mp4"
    out.parent.mkdir(parents=True, exist_ok=True)

    missing = [s["id"] for s in plan["scenes"] if not (video / f"{s['id']}.mp4").is_file()]
    if missing:
        print(f"missing clips: {missing}")
        return 1

    with tempfile.TemporaryDirectory() as td:
        td = Path(td)
        parts, total = [], 0
        print(f"{'scene':6} {'frames':>7} {'slot':>8}")
        for s in plan["scenes"]:
            want = round(s["end_seconds"] * FPS) - round(s["start_seconds"] * FPS)
            part = td / f"{s['id']}.mp4"
            subprocess.run(
                ["ffmpeg", "-y", "-v", "error", "-i", str(video / f"{s['id']}.mp4"),
                 "-frames:v", str(want), "-vf", f"setpts=N/{FPS}/TB",
                 "-c:v", "libx264", "-crf", str(args.crf), "-pix_fmt", "yuv420p",
                 "-an", str(part)], check=True)
            have = int(subprocess.run(
                ["ffprobe", "-v", "error", "-select_streams", "v:0", "-count_frames",
                 "-show_entries", "stream=nb_read_frames", "-of", "csv=p=0", str(part)],
                capture_output=True, text=True).stdout.strip() or 0)
            flag = "" if have == want else f"  !! got {have}"
            print(f"{s['id']:6} {want:7d} {want / FPS:7.2f}s{flag}")
            parts.append(part)
            total += want

        lst = td / "concat.txt"
        lst.write_text("".join(f"file '{p.name}'\n" for p in parts), encoding="utf-8")
        silent = td / "silent.mp4"
        subprocess.run(["ffmpeg", "-y", "-v", "error", "-f", "concat", "-safe", "0",
                        "-i", str(lst), "-c", "copy", str(silent)],
                       check=True, cwd=str(td))

        cmd = ["ffmpeg", "-y", "-v", "error", "-i", str(silent)]
        if audio.is_file():
            cmd += ["-i", str(audio), "-map", "0:v", "-map", "1:a",
                    "-c:a", "aac", "-b:a", "192k", "-shortest"]
        else:
            print(f"\nno audio at {audio} - the cut will be silent")
        cmd += ["-c:v", "libx264", "-crf", str(args.crf), "-pix_fmt", "yuv420p",
                "-movflags", "+faststart", str(out)]
        subprocess.run(cmd, check=True)

    d = json.loads(subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-show_entries", "stream=nb_frames,width,height", "-of", "json", str(out)],
        capture_output=True, text=True).stdout)
    dur = float(d["format"]["duration"])
    print(f"\n{len(parts)} scenes, {total} frames, {total / FPS:.2f}s planned")
    print(f"written: {out}  ({dur:.2f}s, {out.stat().st_size / 1e6:.1f} MB)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
