"""Write the scene plan's timing into the Builder session.

    .venv/Scripts/python.exe scripts/sync_timing.py --project the-man-watches \
        --folder "C:\\...\\output\\TheManWatches"

The export writes segment `start`/`end` once. Any later change to the plan - a
retime, a beat snap, a re-cut - leaves the Builder cutting to the old clock, and
nothing warns: the timeline still looks complete, it is just wrong.

This is the narrow update: boundaries only, on a session VRGDG authored, leaving
prompts, stills, clips and cast settings alone. Re-exporting would do it too,
but it rewrites the whole timeline and needs the server up.

Run `audit_timing.py` afterwards; it checks this join.
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from lib.machine_paths import project_dir  # noqa: E402
from lib.vrgdg_bridge import stable_segment_id  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--project", default=None)
    ap.add_argument("--folder", required=True)
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    project = project_dir(args.project)
    plan = json.loads((project / "artifacts" / "scene_plan.json").read_text(encoding="utf-8"))
    folder = Path(args.folder)
    session_path = folder / "vrgdg_builder_session.json"
    session = json.loads(session_path.read_text(encoding="utf-8"))
    segments = session.get("segments") or []

    want = {stable_segment_id(s["id"]): (s["id"], s["start_seconds"], s["end_seconds"])
            for s in plan["scenes"]}

    changed = []
    for seg in segments:
        hit = want.get(str(seg.get("id") or ""))
        if not hit:
            continue
        sid, start, end = hit
        was = (seg.get("start"), seg.get("end"))
        if was != (start, end):
            changed.append((sid, was, (start, end)))
            if not args.dry_run:
                seg["start"] = start
                seg["end"] = end
                # A clip cut to the old length no longer fits the new slot.
                if seg.get("video_path"):
                    seg["video_status"] = "stale"

    for sid, was, now in changed[:40]:
        w = (was[1] - was[0]) if None not in was else None
        n = now[1] - now[0]
        print(f"  {sid}  {was[0]}-{was[1]} -> {now[0]:.2f}-{now[1]:.2f}"
              + (f"   ({w:.2f}s -> {n:.2f}s)" if w is not None else ""))
    print(f"\n{len(changed)} segment(s) differ from the plan")

    if args.dry_run or not changed:
        return 0

    backups = folder / "session_backups"
    backups.mkdir(parents=True, exist_ok=True)
    stamp = str(int(session_path.stat().st_mtime))
    shutil.copyfile(session_path, backups / f"session_before_timing_{stamp}.json")
    session_path.write_text(json.dumps(session, indent=2), encoding="utf-8")
    stale = [s for s in segments if s.get("video_status") == "stale"]
    print(f"written. {len(stale)} existing clip(s) marked stale - they were cut "
          "to the old length.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
