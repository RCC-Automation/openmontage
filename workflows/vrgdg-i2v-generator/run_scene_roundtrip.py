"""Submit one generated VRGDG scene workflow and restore its result.

This deliberately uses only ComfyUI and VRGDG's HTTP contracts.  It does not
reach into ComfyUI's Python process or guess its internal output directory.
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import time
import urllib.error
import urllib.request
import uuid


def request_json(base_url: str, method: str, route: str, payload=None, timeout=60):
    body = None if payload is None else json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(
        f"{base_url.rstrip('/')}{route}",
        data=body,
        method=method,
        headers={"Content-Type": "application/json"} if body is not None else {},
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"{method} {route} failed ({exc.code}): {detail}") from exc


def find_completed_video(project: Path, base_name: str, started: float) -> Path:
    candidates: list[tuple[int, float, Path]] = []
    prefixes = (
        "image_to_video_clips",
        "text_to_video_clips",
        "reference_to_video_clips",
        "ingredients_to_video_clips",
    )
    for folder in project.iterdir():
        if not folder.is_dir() or not folder.name.startswith(prefixes):
            continue
        for path in folder.rglob("*.mp4"):
            try:
                modified = path.stat().st_mtime
                size = path.stat().st_size
            except OSError:
                continue
            if modified < started - 5 or size <= 0 or not path.name.startswith(base_name):
                continue
            audio_score = 2 if path.name.lower().endswith("-audio.mp4") else 0
            candidates.append((audio_score, modified, path))
    if not candidates:
        raise RuntimeError(
            f"ComfyUI completed but no non-empty MP4 beginning with '{base_name}' "
            f"was found below {project}."
        )
    return max(candidates, key=lambda item: (item[0], item[1]))[2]


def update_builder_session(base_url: str, project: Path, scene: int, restored: dict) -> Path:
    session_path = project / "vrgdg_builder_session.json"
    session = json.loads(session_path.read_text(encoding="utf-8-sig"))
    segments = session.get("segments") or []
    if scene < 1 or scene > len(segments):
        raise RuntimeError(f"Scene {scene} is outside the Builder session range 1..{len(segments)}.")
    segment = segments[scene - 1]
    video_path = str(restored["video_path"])
    thumbnail_path = str(restored.get("thumbnail_path") or "")
    segment["video_path"] = video_path
    segment["video_folder"] = str(restored.get("video_folder") or Path(video_path).parent)
    segment["video_thumbnail_path"] = thumbnail_path
    segment["video_status"] = "done"
    segment["preview_mode"] = "video"
    history = segment.setdefault("video_history", [])
    if video_path not in history:
        history.append(video_path)
    thumbnail_history = segment.setdefault("video_thumbnail_history", [])
    if thumbnail_path and thumbnail_path not in thumbnail_history:
        thumbnail_history.append(thumbnail_path)
    segment["video_history_index"] = history.index(video_path)
    backup_path = str(restored.get("backup_path") or "")
    if backup_path:
        backups = segment.setdefault("video_backup_paths", [])
        if backup_path not in backups:
            backups.append(backup_path)
    backup_thumbnail = str(restored.get("backup_thumbnail_path") or "")
    if backup_thumbnail:
        backup_thumbnails = segment.setdefault("video_backup_thumbnail_paths", [])
        if backup_thumbnail not in backup_thumbnails:
            backup_thumbnails.append(backup_thumbnail)
    session["updated"] = time.strftime("%Y-%m-%dT%H:%M:%S")
    saved = request_json(
        base_url,
        "POST",
        "/vrgdg/music_builder/save_session",
        {
            "audio_path": session.get("audio_path", ""),
            "project_folder": str(project),
            "session": session,
        },
        timeout=120,
    )
    return Path(saved.get("session_path") or session_path)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--project", required=True)
    parser.add_argument("--scene", required=True, type=int)
    parser.add_argument("--workflow", required=True)
    parser.add_argument("--server", default="http://127.0.0.1:8188")
    parser.add_argument("--timeout", type=int, default=7200)
    args = parser.parse_args()

    project = Path(args.project).expanduser().resolve()
    workflow_path = Path(args.workflow).expanduser().resolve()
    workflow = json.loads(workflow_path.read_text(encoding="utf-8-sig"))
    base_name = str(workflow["634"]["inputs"]["base_name"])

    request_json(args.server, "GET", "/system_stats", timeout=10)
    queue = request_json(args.server, "GET", "/queue", timeout=10)
    if queue.get("queue_running") or queue.get("queue_pending"):
        raise RuntimeError("ComfyUI already has a running or pending job; refusing to mix outputs.")

    started = time.time()
    submitted = request_json(
        args.server,
        "POST",
        "/prompt",
        {"prompt": workflow, "client_id": str(uuid.uuid4())},
        timeout=60,
    )
    prompt_id = str(submitted.get("prompt_id") or "")
    if not prompt_id:
        raise RuntimeError(f"ComfyUI did not return a prompt_id: {submitted}")
    print(f"Submitted scene {args.scene}; prompt_id={prompt_id}", flush=True)

    deadline = started + args.timeout
    history_entry = None
    while time.time() < deadline:
        history = request_json(args.server, "GET", f"/history/{prompt_id}", timeout=30)
        history_entry = history.get(prompt_id)
        if history_entry is not None:
            break
        time.sleep(5)
    if history_entry is None:
        raise TimeoutError(
            f"Scene {args.scene} did not finish within {args.timeout} seconds. "
            f"The existing ComfyUI job is {prompt_id}; do not submit a duplicate."
        )
    status = history_entry.get("status") or {}
    if status.get("status_str") == "error" or status.get("completed") is False:
        raise RuntimeError(f"ComfyUI scene {args.scene} failed: {json.dumps(status, ensure_ascii=False)}")

    source = find_completed_video(project, base_name, started)
    session = json.loads((project / "vrgdg_builder_session.json").read_text(encoding="utf-8-sig"))
    segment = (session.get("segments") or [])[args.scene - 1]
    expected_duration = max(0.1, float(segment.get("end", 0)) - float(segment.get("start", 0)))
    restored = request_json(
        args.server,
        "POST",
        "/vrgdg/music_builder/restore_scene_video",
        {
            "project_folder": str(project),
            "scene_number": args.scene,
            "source_path": str(source),
            "expected_duration": expected_duration,
            "duration_tolerance": 0.5,
            "confirm_duration_mismatch": True,
        },
        timeout=120,
    )
    session_path = update_builder_session(args.server, project, args.scene, restored)
    result = {
        "scene": args.scene,
        "prompt_id": prompt_id,
        "workflow": str(workflow_path),
        "generated_video": str(source),
        "installed_video": restored.get("video_path"),
        "thumbnail": restored.get("thumbnail_path"),
        "session": str(session_path),
    }
    print(json.dumps(result, indent=2, ensure_ascii=False), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
