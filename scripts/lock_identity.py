"""Put the cast's actual face onto every still that shows one.

    .venv/Scripts/python.exe scripts/lock_identity.py --project the-man-watches
    .venv/Scripts/python.exe scripts/lock_identity.py --project the-man-watches --dry-run

Why this stage has to exist
---------------------------

A prompt describes a *look*, not a *face*. "Long dark hair, faux fur shrug,
ornate goggles, glitter, one long deep red scarf" dresses a different woman
every render, and measurement says exactly that: the 34 stills of `The Man
Watches` scored a mean **0.057** ArcFace against their own cast reference, where
0.35-0.40 is the boundary between the same person and a stranger. Twenty-eight
unrelated people in one costume.

Holding a seed does not fix it either - a seed fixes the ground, and the same
seed with a different prompt gives a different face.

So the pipeline splits: render freely for body, wardrobe, pose and scene, then
transplant the anchor's face. ReActor copies rather than re-imagines, which is
why it beats the alternatives measured here - SDXL reference gives 0.53-0.68, a
family resemblance; IP-Adapter FaceID gives 0.75-0.84 but normalises toward its
training distribution and turned an adult woman into a teenager. ReActor
measured 0.80-0.88.

The floor is real
-----------------

inswapper works at 128x128 and needs a face of roughly **0.4% of frame** to have
anything to work with. Below that a still is skipped rather than degraded - in a
wide her face is a few pixels and the red scarf is what carries her, which the
casting round measured directly.

Originals are kept
------------------

Every untouched still is copied to `heroes/original/` before it is replaced, so
a bad swap costs nothing and the two can be compared.
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from lib.comfy_routing import to_wsl_paths  # noqa: E402
from lib.face_identity import faces_in  # noqa: E402
from lib.machine_paths import project_dir  # noqa: E402
from tools._comfyui.faceswap import build_faceswap_graph  # noqa: E402

#: inswapper needs roughly this much face to work with. Measured floor, from
#: wiki/character - below it the swap degrades the still instead of fixing it.
FACE_FLOOR_PCT = 0.4


def face_fraction(path: Path) -> float:
    """The largest face's share of the frame, as a percentage."""
    from PIL import Image
    faces = faces_in(path)
    if not faces:
        return 0.0
    w, h = Image.open(path).size
    x1, y1, x2, y2 = faces[0].bbox
    return 100.0 * ((x2 - x1) * (y2 - y1)) / (w * h)


def run(server: str, graph: dict, dest: Path, minutes: float = 20.0) -> float | None:
    graph, _ = to_wsl_paths(graph)
    start = time.time()
    req = urllib.request.Request(f"{server}/prompt",
                                 data=json.dumps({"prompt": graph}).encode(),
                                 headers={"Content-Type": "application/json"})
    try:
        pid = json.loads(urllib.request.urlopen(req, timeout=120).read())["prompt_id"]
    except urllib.error.HTTPError as exc:
        body = exc.read().decode(errors="replace")
        try:
            d = json.loads(body)
            errs = [f"node {n} ({v.get('class_type')}): {e.get('details') or e.get('message')}"
                    for n, v in (d.get("node_errors") or {}).items()
                    for e in v.get("errors") or []]
            body = "; ".join(errs) or body
        except Exception:
            pass
        print(f" HTTP {exc.code}: {body[:200]}")
        return None

    while time.time() - start < minutes * 60:
        try:
            hist = json.loads(urllib.request.urlopen(
                f"{server}/history/{pid}", timeout=60).read())
            if pid in hist:
                break
        except Exception:
            pass
        time.sleep(2)
    else:
        print(f" no result after {minutes:.0f} min")
        return None

    for node in (hist[pid].get("outputs") or {}).values():
        for item in node.get("images") or []:
            q = urllib.parse.urlencode({
                "filename": item["filename"], "subfolder": item.get("subfolder", ""),
                "type": item.get("type", "output")})
            dest.write_bytes(urllib.request.urlopen(f"{server}/view?{q}", timeout=900).read())
            return round(time.time() - start, 1)
    print(" completed but wrote no image")
    return None


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--project", default=None)
    ap.add_argument("--server", default="http://127.0.0.1:8189")
    ap.add_argument("--floor", type=float, default=FACE_FLOOR_PCT)
    ap.add_argument("--visibility", type=float, default=0.75,
                    help="face_restore_visibility: 1.0 reads airbrushed, "
                         "0.1 leaves the raw 128px swap soft")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    project = project_dir(args.project)
    cast = json.loads((project / "artifacts" / "cast_record.json").read_text(encoding="utf-8"))
    ref = project / (cast.get("references") or {})["close_up"]
    if not ref.exists():
        print(f"no cast reference at {ref}")
        return 1

    heroes = project / "scene_look" / "heroes"
    originals = heroes / "original"
    originals.mkdir(parents=True, exist_ok=True)
    stills = sorted(heroes.glob("sc*.png"))

    print(f"reference: {ref.name}\nchecking {len(stills)} stills for a "
          f"swappable face (>= {args.floor}% of frame)\n")

    todo, skipped = [], []
    for s in stills:
        frac = face_fraction(originals / s.name if (originals / s.name).exists() else s)
        (todo if frac >= args.floor else skipped).append((s, frac))

    for s, frac in todo:
        print(f"  swap  {s.stem}  face {frac:.2f}%")
    print()
    for s, frac in skipped:
        why = "no face" if frac == 0 else f"face only {frac:.2f}%"
        print(f"  skip  {s.stem}  {why}")
    print(f"\n{len(todo)} to swap, {len(skipped)} skipped")
    if args.dry_run:
        return 0

    done, failed = 0, []
    for i, (s, frac) in enumerate(todo, 1):
        # Keep the original once, and always swap FROM it, so re-running does
        # not swap a swap.
        src = originals / s.name
        if not src.exists():
            shutil.copyfile(s, src)
        graph = build_faceswap_graph(
            source_face=ref, target_image=src,
            face_restore_visibility=args.visibility,
            filename_prefix=f"idlock/{s.stem}")
        print(f"  [{i:2}/{len(todo)}] {s.stem} ...", end="", flush=True)
        secs = run(args.server, graph, s)
        print(f" {secs}s" if secs else "")
        if secs:
            done += 1
        else:
            failed.append(s.stem)

    print(f"\n{done} swapped, originals kept in {originals}")
    if failed:
        print(f"failed: {', '.join(failed)}")
    print("\nRe-measure with scripts/identity_check.py")
    return 0 if not failed else 1


if __name__ == "__main__":
    raise SystemExit(main())
