"""Push the hero stills into a VRGDG Builder project, across the WSL boundary.

    .venv/Scripts/python.exe scripts/push_stills.py --project the-man-watches \
        --folder /home/barrul/ComfyUI/output/the-man-watches

`vrgdg_project_sync --operation export` writes the timeline correctly and pushes
**zero** stills when the Builder is the WSL install, for two reasons that are
both the same cross-platform trap:

    the staging path   it does `Path(project_folder) / "openmontage_stills"`,
                       and on Windows a POSIX folder becomes a WindowsPath, so
                       "/home/barrul/..." is sent as "\\home\\barrul\\..." and
                       the server prepends its own root to it.
    the source images  they live on the Windows filesystem. The WSL server
                       cannot open `C:\\Users\\...`; it needs `/mnt/c/Users/...`.

So this pushes them directly, translating the source path and letting the server
decide where it lands. The same translation `lib.comfy_routing.to_wsl_paths`
does for graphs - which exists because a model name with a backslash silently
selects a *different* file on Linux.

The session is then told where each still landed, in both the slots the Builder
reads: `custom_image_path` (its own copy) and `approved_image_path`. Render prep
reads custom before approved and re-copies, and `save_scene_image` has no
same-file guard - so pointing both at one file makes the Builder copy it onto
itself and die. Two distinct paths, no collision.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from lib.comfy_routing import which_platform  # noqa: E402
from lib.machine_paths import project_dir, wsl_path  # noqa: E402
from lib.vrgdg_bridge import SceneMap, stable_segment_id  # noqa: E402
from tools._comfyui.vrgdg import VRGDGClient, VRGDGError  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--project", default=None)
    ap.add_argument("--folder", required=True,
                    help="the VRGDG project folder, as the SERVER sees it")
    ap.add_argument("--server", default="http://127.0.0.1:8189")
    ap.add_argument("--audio", default=None,
                    help="track as the SERVER sees it. Required on every save: "
                         "the route blanks the session's audio when it is absent")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    import os
    os.environ["COMFYUI_VRGDG_SERVER_URL"] = args.server
    os.environ["COMFYUI_SERVER_URL"] = args.server

    project = project_dir(args.project)
    manifest = json.loads(
        (project / "artifacts" / "asset_manifest.json").read_text(encoding="utf-8"))
    plan = json.loads(
        (project / "artifacts" / "scene_plan.json").read_text(encoding="utf-8"))
    order = [s["id"] for s in plan["scenes"]]

    stills = {a["scene_id"]: project / a["path"]
              for a in manifest["assets"] if a["type"] == "image"}

    client = VRGDGClient()
    if not client.is_available():
        print(client.unavailable_reason())
        return 1

    # Only translate to /mnt/c when the server is actually WSL. Sending a
    # /mnt/c path to a Windows ComfyUI fails exactly as sending C:\ to WSL does.
    plat = which_platform(args.server)
    to_server = wsl_path if plat == "wsl" else (lambda p: str(p))
    print(f"server reports itself as {plat}")


    session = client.load_session(args.folder).get("session") or {}
    segments = session.get("segments") or []
    print(f"{len(stills)} stills, {len(segments)} segments in the session\n")

    # The Builder numbers scenes from 1 in timeline order.
    scene_number = {sid: i for i, sid in enumerate(order, start=1)}

    landed: dict[str, str] = {}
    failed: list[str] = []
    for sid in order:
        src = stills.get(sid)
        if not src or not src.exists():
            continue
        posix = to_server(src)
        n = scene_number[sid]
        if args.dry_run:
            print(f"  {sid} -> scene {n}  {posix}")
            continue
        try:
            res = client.save_scene_image(args.folder, n, posix)
            path = res.get("saved_path") or res.get("image_path")
            if path:
                landed[sid] = str(path)
                print(f"  {sid} -> scene {n}  {path}")
            else:
                failed.append(sid)
                print(f"  {sid}: route returned no path")
        except VRGDGError as exc:
            failed.append(sid)
            print(f"  {sid}: {str(exc)[:120]}")

    if args.dry_run:
        return 0

    # Tell the session where they landed. The two slots must point at DIFFERENT
    # files: render prep reads custom_image_path before approved_image_path and
    # re-copies it into the approved slot, and save_scene_image has no same-file
    # guard - so one path in both slots makes the Builder copy a file onto
    # itself and die. custom stays on our side of the mount, approved is the
    # Builder's own copy.
    by_segment = {stable_segment_id(sid): (landed[sid], to_server(stills[sid]))
                  for sid in landed}
    touched = 0
    for seg in segments:
        hit = by_segment.get(str(seg.get("id") or ""))
        if not hit:
            continue
        approved, source = hit
        seg["approved_image_path"] = approved
        seg["custom_image_path"] = source
        seg["custom_image_name"] = Path(source).name
        seg["image"] = source
        touched += 1

    # audio_path MUST be passed on every save. The server overrides the
    # session's own value with this field and BLANKS it when absent - so a save
    # that forgets it silently drops the track, which is what happened on the
    # first run of this script.
    audio = session.get("audio_path") or args.audio
    if touched:
        client.save_session(args.folder, session, audio_path=audio or None)
        if not audio:
            print("  !! no audio_path - the session track will be blank")
    print(f"\n{len(landed)} pushed, {touched} segments updated"
          + (f", {len(failed)} failed" if failed else ""))
    if failed:
        print("failed: " + ", ".join(failed))
    return 0 if not failed else 1


if __name__ == "__main__":
    raise SystemExit(main())
