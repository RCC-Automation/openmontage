"""Run a shoot to completion, detached and scene by scene.

    Start-Process .venv\\Scripts\\python.exe scripts\\shoot_batch.py -- \\
        --project the-man-watches --stills sc03 --videos sc01 sc02 sc03 --builder "..."

Long shoots outlive the shell that starts them. Three runners were killed
mid-render during the first three shots of this film, and the only reason
nothing was lost is that the work was already on the server. This is the piece
meant to be launched detached and left alone.

Everything is per scene: one still at a time, one clip at a time, each in its
own subprocess, each result written as it lands. A failure costs that scene and
nothing after it, and re-running skips whatever already exists.
"""

from __future__ import annotations

import argparse
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from lib.machine_paths import project_dir, repo_root  # noqa: E402


def run(cmd: list[str]) -> int:
    print(f"\n$ {' '.join(cmd[1:])}", flush=True)
    return subprocess.run(cmd, cwd=str(repo_root())).returncode


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--project", default=None)
    ap.add_argument("--stills", nargs="*", default=[],
                    help="scene ids whose hero still to re-render first")
    ap.add_argument("--videos", nargs="*", default=[],
                    help="scene ids to render; omit for all that are missing")
    ap.add_argument("--builder", default=None)
    ap.add_argument("--swap", action="store_true",
                    help="face-swap after re-rendering stills")
    args = ap.parse_args()

    project = project_dir(args.project)
    py = sys.executable
    S = repo_root() / "scripts"
    started = time.time()

    for sid in args.stills:
        # A re-rendered still loses its swap, so the original is dropped too.
        for p in (project / "scene_look" / "heroes" / f"{sid}.png",
                  project / "scene_look" / "heroes" / "original" / f"{sid}.png"):
            p.unlink(missing_ok=True)
        run([py, str(S / "hero_stills.py"), "--project", project.name, "--only", sid])

    if args.stills and args.swap:
        run([py, str(S / "lock_identity.py"), "--project", project.name])

    for sid in args.videos:
        (project / "assets" / "video" / f"{sid}.mp4").unlink(missing_ok=True)

    cmd = [py, str(S / "render_shots.py"), "--project", project.name, "--isolate"]
    if args.videos:
        cmd += ["--only", *args.videos]
    if args.builder:
        cmd += ["--builder", args.builder]
    run(cmd)

    if args.builder:
        run([py, str(S / "attach_clips.py"), "--project", project.name,
             "--folder", args.builder])

    print(f"\nbatch finished in {(time.time() - started) / 60:.0f} min", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
