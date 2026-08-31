"""Attach rendered clips to a VRGDG Builder timeline so they actually show.

    .venv/Scripts/python.exe scripts/attach_clips.py --project the-man-watches \
        --folder "C:\\...\\output\\TheManWatches"

Copying an mp4 into `rendered_scene_videos/` puts the file where the Builder
keeps its clips and the Builder still shows nothing, because the timeline reads
paths out of the session, not the folder. A segment with `video_path: ""` and
`video_status: "none"` is an empty scene however many files sit beside it.

The field shape here is copied from a session the Builder itself wrote (film
one), not invented: `video_path`, a matching `.jpg` thumbnail, both repeated
into `video_history` / `video_thumbnail_history` with `video_history_index: 0`,
`video_status: "done"`, and `video_folder`. The Builder's own naming is
`video_NNNN-audio.mp4`, so that is what these are named.

**audio_path must be passed on every save.** The route overrides the session's
own value with that field and blanks it when absent - so a save that forgets it
silently drops the track. That happened once already on this film.
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
from lib.vrgdg_bridge import stable_segment_id  # noqa: E402


def thumbnail(clip: Path, dest: Path) -> bool:
    """One frame, a second in. The Builder shows this in the timeline."""
    try:
        subprocess.run(["ffmpeg", "-y", "-v", "error", "-ss", "1", "-i", str(clip),
                        "-frames:v", "1", "-q:v", "3", str(dest)],
                       check=True, timeout=120)
        return dest.exists()
    except Exception:
        return False


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--project", default=None)
    ap.add_argument("--folder", required=True, help="the Builder project folder")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    project = project_dir(args.project)
    plan = json.loads((project / "artifacts" / "scene_plan.json").read_text(encoding="utf-8"))
    order = [s["id"] for s in plan["scenes"]]
    clips = project / "assets" / "video"
    folder = Path(args.folder)
    videos = folder / "rendered_scene_videos"
    videos.mkdir(parents=True, exist_ok=True)

    have = [(sid, clips / f"{sid}.mp4") for sid in order
            if (clips / f"{sid}.mp4").exists()]
    print(f"{len(have)} clip(s) to attach\n")
    if not have:
        return 0

    # Read the session file directly. save_session is only needed for what the
    # ROUTE does - snapshotting audio into the project - and that happened at
    # export. Attaching a clip writes known keys on a session VRGDG authored,
    # which is what the bridge does too (DECISIONS #2). No server required, so
    # this works with ComfyUI closed.
    session_path = folder / "vrgdg_builder_session.json"
    if not session_path.is_file():
        print(f"no Builder session at {session_path}")
        return 1
    session = json.loads(session_path.read_text(encoding="utf-8"))
    segments = session.get("segments") or []

    staged: dict[str, tuple[str, str]] = {}
    for sid, src in have:
        n = order.index(sid) + 1
        # The Builder's own naming, so its timeline recognises them.
        mp4 = videos / f"video_{n:04d}-audio.mp4"
        jpg = videos / f"video_{n:04d}-audio.jpg"
        if args.dry_run:
            print(f"  {sid} -> {mp4.name}")
            continue
        shutil.copyfile(src, mp4)
        ok = thumbnail(mp4, jpg)
        staged[sid] = (str(mp4), str(jpg) if ok else "")
        print(f"  {sid} -> {mp4.name}" + ("" if ok else "  (no thumbnail)"))

    if args.dry_run:
        return 0

    by_segment = {stable_segment_id(sid): v for sid, v in staged.items()}
    touched = 0
    for seg in segments:
        hit = by_segment.get(str(seg.get("id") or ""))
        if not hit:
            continue
        mp4, jpg = hit
        seg["video_path"] = mp4
        seg["video_thumbnail_path"] = jpg
        seg["video_history"] = [mp4]
        seg["video_thumbnail_history"] = [jpg]
        seg["video_history_index"] = 0
        seg["video_status"] = "done"
        seg["video_folder"] = str(videos)
        touched += 1

    backups = folder / "session_backups"
    backups.mkdir(parents=True, exist_ok=True)
    stamp = str(int(session_path.stat().st_mtime))
    shutil.copyfile(session_path, backups / f"session_before_clips_{stamp}.json")
    session_path.write_text(json.dumps(session, indent=2), encoding="utf-8")

    audio = session.get("audio_path")
    print(f"\n{touched} segment(s) now point at a clip")
    print(f"audio_path: {'set' if audio else 'MISSING'}")
    print(f"backup: {backups / f'session_before_clips_{stamp}.json'}")
    print("Reload the project in the Builder to see them.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
