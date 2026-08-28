"""Recast the character in an existing VRGDG project's scene images.

    python scripts/recast_vrgdg_project.py --project BurningManGirl --dry-run
    python scripts/recast_vrgdg_project.py --project BurningManGirl

The scenes are written, composed and timed. Only the person in them is wrong.
So this keeps every prompt's shot, action, location and mood, rewrites the
character description inside it, regenerates on the same engine the project
already uses, and swaps our anchor's face on afterwards.

**Why rewriting the prompt is the work, not the face swap.** These are wide
shots: the face is 0.2-1.3% of the frame. At that scale a person is recognised
by hair, silhouette and costume, and a face swap touches none of those - it
changes the one part nobody can see. The description is what carries the
character here, so the description is what has to change. The swap then fixes
identity for the close-ups and for anything the video stage crops in on.

Nothing is overwritten. New images land in `openmontage_recast/` inside the
project, and the session is only touched when `--write-session` is passed -
which appends to each scene's `image_history` rather than replacing it, so the
originals stay one click away in the Builder.
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
import sys
import time
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from lib.face_identity import faces_in  # noqa: E402
from lib.sheets import ACCENTS, SheetItem, labelled_sheet  # noqa: E402
from scripts.masters import KLEIN, _reference_guard  # noqa: E402
from tools._comfyui.client import ComfyUIClient  # noqa: E402
from tools._comfyui.faceswap import OUTPUT_NODE as SWAP_OUT, build_faceswap_graph  # noqa: E402
from tools._comfyui.vrgdg import VRGDGClient, node_class_types  # noqa: E402

VRGDG_OUTPUT = Path(r"C:\Users\Barrul\AppData\Local\Comfy-Desktop\ComfyUI-Shared\output")

#: The outgoing character, as the prompts describe her. Matched case-insensitively
#: and tolerant of the small wording drifts between scenes.
OLD_PATTERNS: tuple[str, ...] = (
    r"an adult woman in her late twenties with shoulder-length dark curly hair",
    r"a woman in her late twenties with shoulder-length dark curly hair",
    r"shoulder-length dark curly hair",
    r"dark curly hair",
    r"rust-red scarf",
    r"hand-painted silver jacket",
    r"textured silver jacket",
    r"silver jacket",
    r"dusty cream cargo trousers",
    r"cream cargo trousers",
    r"weathered boots",
)

#: What each of the above becomes. Same grammatical slot, so the sentences stay
#: readable and the shot description around them is untouched.
NEW_TERMS: dict[str, str] = {
    r"an adult woman in her late twenties with shoulder-length dark curly hair":
        "an adult woman in her late twenties with long blonde hair in two braids",
    r"a woman in her late twenties with shoulder-length dark curly hair":
        "a woman in her late twenties with long blonde hair in two braids",
    r"shoulder-length dark curly hair": "long blonde hair in two braids",
    r"dark curly hair": "long blonde hair in two braids",
    r"rust-red scarf": "loose white tied top",
    r"hand-painted silver jacket": "bare shoulders",
    # The prompts also say "textured silver jacket" and bare "silver jacket".
    # Ordered longest-first above so the specific forms match before the bare one.
    r"textured silver jacket": "bare shoulders",
    r"silver jacket": "bare shoulders",
    r"dusty cream cargo trousers": "denim shorts",
    r"cream cargo trousers": "denim shorts",
    r"weathered boots": "dusty boots",
}


def recast_prompt(prompt: str, name: str, new_name: str | None = None) -> tuple[str, int]:
    """Swap the character description out of a scene prompt. Returns (text, edits)."""
    edits = 0
    out = prompt
    for pattern in OLD_PATTERNS:
        replacement = NEW_TERMS[pattern]
        out, n = re.subn(pattern, replacement, out, flags=re.IGNORECASE)
        edits += n
    if new_name:
        out, n = re.subn(rf"\b{re.escape(name)}\b", new_name, out)
        edits += n
    return out, edits


def _face(path: Path) -> tuple[np.ndarray | None, float]:
    found = faces_in(path)
    if not found:
        return None, 0.0
    try:
        from PIL import Image

        with Image.open(path) as handle:
            frame = float(handle.width * handle.height)
        x1, y1, x2, y2 = found[0].bbox
        # float() matters: the bbox is numpy float32 and json.dumps refuses it.
        share = float(abs((x2 - x1) * (y2 - y1)) / frame) if frame else 0.0
    except Exception:
        share = 0.0
    v = getattr(found[0], "normed_embedding", None)
    return (None if v is None else np.asarray(v, dtype=np.float64)), share


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project", required=True, help="VRGDG project folder name.")
    parser.add_argument("--character", default="Mara", help="Name in the prompts.")
    parser.add_argument("--rename", default=None, help="Optional new name for her.")
    parser.add_argument("--masters", default="projects/burningman/masters/masters.json")
    parser.add_argument("--width", type=int, default=1280)
    parser.add_argument("--height", type=int, default=720)
    parser.add_argument("--swap-above", type=float, default=0.004,
                        help="Only swap when the face is at least this share of frame.")
    parser.add_argument("--dry-run", action="store_true", help="Show the prompt rewrites, render nothing.")
    parser.add_argument("--write-session", action="store_true",
                        help="Append the new images to each scene's image_history.")
    parser.add_argument("--scenes", default=None, help="e.g. 1,4,12. Default: all.")
    parser.add_argument("--rerender", action="store_true",
                        help="Render the prompts as they already are, without rewriting.")
    args = parser.parse_args()

    project = VRGDG_OUTPUT / args.project
    session_path = project / "vrgdg_builder_session.json"
    if not session_path.is_file():
        print(f"FAIL: no session at {session_path}")
        return 1
    session = json.loads(session_path.read_text(encoding="utf-8"))
    segments = session.get("segments", [])
    masters = json.loads(Path(args.masters).read_text(encoding="utf-8"))
    anchor = Path(masters["face"])
    body = Path(masters["body_front"])

    wanted = None
    if args.scenes:
        wanted = {int(x) for x in args.scenes.split(",") if x.strip()}

    # ------------------------------------------------------------ dry run
    edits_total = 0
    plans = []
    for i, seg in enumerate(segments, 1):
        if wanted and i not in wanted:
            continue
        old = seg.get("t2i_prompt") or seg.get("flux_prompt") or ""
        new, n = recast_prompt(old, args.character, args.rename)
        edits_total += n
        plans.append((i, seg, old, new, n))
        if args.dry_run:
            print(f"=== scene {i}: {n} edits ===")
            print("  BEFORE:", old[:200].replace("\n", " "))
            print("  AFTER :", new[:200].replace("\n", " "))
            print()
    print(f"{len(plans)} scenes, {edits_total} description edits")
    if args.dry_run:
        return 0
    if edits_total == 0 and not args.rerender:
        # Zero edits means either the patterns are wrong, or the session was
        # already recast and only the images need regenerating. The first is a
        # bug worth stopping for; the second is routine, hence the flag.
        print("FAIL: nothing matched - the prompts may already be recast; pass --rerender to")
        print("      render them as they stand, or check --character and OLD_PATTERNS.")
        return 1

    out_dir = project / "openmontage_recast"
    out_dir.mkdir(parents=True, exist_ok=True)
    vrgdg, client = VRGDGClient(), ComfyUIClient()
    if not vrgdg.is_available():
        print("FAIL:", vrgdg.unavailable_reason())
        return 1
    added = _reference_guard(vrgdg, "a woman standing", anchor, args.width, args.height)
    if not added:
        print("FAIL: the Klein reference was dropped; see HANDOFF")
        return 1
    mv, _ = _face(anchor)

    rows = []
    started = time.time()
    for i, seg, old, new, n in plans:
        raw = out_dir / f"scene_{i:04d}_raw.png"
        final = out_dir / f"scene_{i:04d}.png"
        if not raw.is_file():
            payload = {
                **KLEIN, "prompt": new, "seed": 1000 + i, "seed_mode": "fixed",
                "width": args.width, "height": args.height,
                "images": [{"path": str(anchor.resolve())}, {"path": str(body.resolve())}],
            }
            graph = vrgdg.build("flux_klein", payload)
            if not (node_class_types(graph.prompt) & added):
                print(f"  scene {i:>2}: reference dropped; skipped")
                continue
            node = graph.output_node(prefer="image")
            graph.prune(node)
            t = time.time()
            try:
                client.generate(graph.prompt, output_node=node, dest=raw, timeout=900)
            except Exception as exc:
                print(f"  scene {i:>2}: render FAILED {str(exc)[:90]}")
                continue
            took = time.time() - t
        else:
            took = 0.0

        _, share = _face(raw)
        swapped = False
        if share >= args.swap_above and not final.is_file():
            g = build_faceswap_graph(source_face=anchor, target_image=raw,
                                     boost_model="codeformer-v0.1.0.pth",
                                     boost_codeformer_weight=0.7, face_restore_visibility=0.5)
            try:
                client.generate(g, output_node=SWAP_OUT, dest=final, timeout=600)
                swapped = True
            except Exception as exc:
                print(f"  scene {i:>2}: swap failed ({str(exc)[:60]}), keeping the render")
                shutil.copyfile(raw, final)
        elif not final.is_file():
            shutil.copyfile(raw, final)

        v, share2 = _face(final)
        cos = None if (v is None or mv is None) else float(np.dot(mv, v))
        rows.append({"scene": i, "path": str(final), "edits": n, "swapped": swapped,
                     "face_fraction": round(float(share2), 5),
                     "cos": None if cos is None else round(cos, 4), "seconds": round(took, 1)})
        print(f"  scene {i:>2}  {took:5.1f}s  {n} edits  face {share2*100:4.1f}%  "
              f"{'swapped' if swapped else 'render only'}  cos {cos:.3f}" if cos is not None
              else f"  scene {i:>2}: no face")

    minutes = (time.time() - started) / 60
    sheet = labelled_sheet(
        [SheetItem(Path(r["path"]), f"scene {r['scene']}",
                   f"cos {r['cos']:.2f}" if r["cos"] is not None else "no face",
                   ACCENTS[0] if r["swapped"] else ACCENTS[3]) for r in rows],
        project.parent.parent / "recast_sheet.png" if False else ROOT / "projects/burningman/vrgdg_recast.png",
        columns=5, cell=340, title=f"{args.project} - recast with her, {len(rows)} scenes")
    (out_dir / "recast_report.json").write_text(json.dumps({
        "project": args.project, "character": args.character, "rename": args.rename,
        "masters": {k: masters[k] for k in ("face", "body_front", "body_three_quarter")},
        "minutes": round(minutes, 1), "scenes": rows,
    }, indent=2), encoding="utf-8")

    if args.write_session:
        backup = project / f"vrgdg_builder_session.recast_backup.json"
        if not backup.is_file():
            shutil.copyfile(session_path, backup)
        for r in rows:
            seg = segments[r["scene"] - 1]
            hist = list(seg.get("image_history") or [])
            hist.append(str(Path(r["path"]).resolve()))
            seg["image_history"] = hist
            seg["image_history_index"] = len(hist) - 1
        session_path.write_text(json.dumps(session, indent=2), encoding="utf-8")
        print(f"\nsession updated (backup at {backup.name}).")
        print("Reload the project in the Builder before touching anything - it does not watch the file.")

    print(f"\n{len(rows)} scenes in {minutes:.0f} min")
    print(f"report: {out_dir / 'recast_report.json'}")
    print(f"sheet : {sheet}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
