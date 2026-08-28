"""Commit a recast into a VRGDG project: the images, and every prompt that names her.

    python scripts/commit_recast.py --project BurningManGirl --dry-run
    python scripts/commit_recast.py --project BurningManGirl

Regenerating the scene images is half the job. The old character's description
lives in **seven prompt fields per scene** - `t2i_prompt`, `flux_prompt`,
`nb_prompt`, `enhance_prompt`, `flow_gpt_prompt`, `i2v_prompt` and `story_beat` -
and in four more files beside the session. Leave any of them and the next render,
the video stage or the storyboard puts the old character back.

What this writes:

  * each scene's new image appended to `image_history`, with the index moved to
    it. Appending rather than replacing keeps the originals one click away in
    the Builder, and `image_history` is the first thing the Builder's render
    prep reads, so it is what actually takes effect (HANDOFF).
  * every prompt field rewritten through the same substitution table that made
    the images, so text and picture agree.
  * `storyboard.json`, `wizard_draft.json`, `prompts/t2i_prompts.txt` and
    `prompts/i2v_prompts.txt` rewritten too.

Everything is backed up first, next to the original with a `.recast_backup`
suffix. Nothing is deleted.

**The Builder does not watch the session file.** Reload the project before
touching anything, or a save from a stale UI overwrites this.
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.recast_vrgdg_project import recast_prompt  # noqa: E402

VRGDG_OUTPUT = Path(r"C:\Users\Barrul\AppData\Local\Comfy-Desktop\ComfyUI-Shared\output")

#: Every per-scene field that carries the character. Found by scanning the
#: session rather than assumed - see the module docstring.
PROMPT_FIELDS = (
    "t2i_prompt", "flux_prompt", "nb_prompt", "enhance_prompt",
    "flow_gpt_prompt", "i2v_prompt", "story_beat",
    "minimax_h3_prompt", "flf_end_frame_prompt", "notes", "timeline_note",
)

#: Other files in the project that repeat the description.
SIDE_FILES = (
    "storyboard/storyboard.json",
    "wizard/wizard_draft.json",
    "prompts/t2i_prompts.txt",
    "prompts/i2v_prompts.txt",
)


def _backup(path: Path) -> Path:
    target = path.with_suffix(path.suffix + ".recast_backup")
    if not target.is_file():
        shutil.copyfile(path, target)
    return target


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project", required=True)
    parser.add_argument("--character", default="Mara")
    parser.add_argument("--rename", default=None)
    parser.add_argument("--images", default=None, help="Default: <project>/openmontage_recast")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--no-images", action="store_true", help="Rewrite prompts only.")
    args = parser.parse_args()

    project = VRGDG_OUTPUT / args.project
    session_path = project / "vrgdg_builder_session.json"
    images_dir = Path(args.images) if args.images else project / "openmontage_recast"
    if not session_path.is_file():
        print(f"FAIL: no session at {session_path}")
        return 1
    session = json.loads(session_path.read_text(encoding="utf-8"))
    segments = session.get("segments", [])

    # ------------------------------------------------------------ images
    image_plan = []
    if not args.no_images:
        for i in range(1, len(segments) + 1):
            p = images_dir / f"scene_{i:04d}.png"
            if p.is_file():
                image_plan.append((i, p))
        missing = [i for i in range(1, len(segments) + 1)
                   if not (images_dir / f"scene_{i:04d}.png").is_file()]
        print(f"images: {len(image_plan)} of {len(segments)} scenes"
              + (f"; missing {missing}" if missing else ""))
        if missing and not args.dry_run:
            print("FAIL: refusing to commit a partial recast. Generate the missing scenes first.")
            return 1

    # ----------------------------------------------------------- prompts
    edits = {}
    for i, seg in enumerate(segments, 1):
        for field in PROMPT_FIELDS:
            old = seg.get(field)
            if not isinstance(old, str) or not old.strip():
                continue
            new, n = recast_prompt(old, args.character, args.rename)
            if n:
                edits.setdefault(field, 0)
                edits[field] += n
                if not args.dry_run:
                    seg[field] = new
    print("prompt edits by field:")
    for f, n in sorted(edits.items(), key=lambda kv: -kv[1]):
        print(f"  {f:22s} {n}")
    print(f"  {'TOTAL':22s} {sum(edits.values())}")

    # -------------------------------------------------------- side files
    side = {}
    for rel in SIDE_FILES:
        p = project / rel
        if not p.is_file():
            continue
        text = p.read_text(encoding="utf-8", errors="ignore")
        new, n = recast_prompt(text, args.character, args.rename)
        side[rel] = n
        if n and not args.dry_run:
            _backup(p)
            p.write_text(new, encoding="utf-8")
    print("side files:")
    for rel, n in side.items():
        print(f"  {rel:34s} {n} edits")

    if args.dry_run:
        print("\ndry run - nothing written")
        return 0

    # ------------------------------------------------------------- write
    _backup(session_path)
    for i, p in image_plan:
        seg = segments[i - 1]
        hist = list(seg.get("image_history") or [])
        resolved = str(p.resolve())
        if not hist or hist[-1] != resolved:
            hist.append(resolved)
        seg["image_history"] = hist
        seg["image_history_index"] = len(hist) - 1
        # custom_image_path is what the Builder's render prep falls back to, and
        # pointing it at our own folder keeps the approved slot as VRGDG's
        # separate copy - never the same file, or render prep copies it onto
        # itself and dies with WinError 32 (HANDOFF).
        seg["custom_image_path"] = resolved
        seg["custom_image_name"] = p.name
    session_path.write_text(json.dumps(session, indent=2), encoding="utf-8")

    print(f"\nwritten. backups: {session_path.name}.recast_backup and one per side file.")
    print("Reload the project in the Builder before touching anything - it does not watch the file.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
