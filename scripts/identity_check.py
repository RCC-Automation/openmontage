"""Is it the same woman in all 34 stills?

    .venv/Scripts/python.exe scripts/identity_check.py --project the-man-watches

Run this BEFORE animating anything. A drift found here costs one still to fix;
found after the shoot it costs a clip, and after the cut it costs the film. The
first film let text-to-video re-invent the face on every clip, which is the
whole reason identity is locked in an image first.

It measures the face and nothing else
-------------------------------------

ArcFace via InsightFace: the face is detected, warped to canonical landmarks and
embedded by a recogniser trained so the same person scores high across pose,
expression and light. The alignment is what makes a three-quarter wide
comparable with a front-on close-up.

It says nothing about wardrobe, hair or grade - a render can hold the face and
lose the character, and the reverse. `lib/face_identity` carries that caveat in
full.

Missing is not the same as wrong
--------------------------------

Most of these 34 are wides where she is small, turned away, or absent by design.
No detectable face is **missing data**, not evidence of drift, and it is
reported separately. Scoring it zero would punish the film for its own framing.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from lib.face_identity import embeddings_available, face_embeddings  # noqa: E402
from lib.machine_paths import project_dir  # noqa: E402

#: Below this against the cast reference, treat it as a different person and
#: re-render. 0.35-0.40 is the usual ArcFace boundary between "same" and
#: "different"; 0.45 leaves margin because these are generated faces at varying
#: sizes, not photographs of one person.
DRIFT_FLOOR = 0.45


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--project", default=None)
    ap.add_argument("--floor", type=float, default=DRIFT_FLOOR)
    args = ap.parse_args()

    if not embeddings_available():
        print("InsightFace is not available - cannot measure identity.\n"
              "Nothing is reported rather than something guessed.")
        return 1

    project = project_dir(args.project)
    cast = json.loads((project / "artifacts" / "cast_record.json").read_text(encoding="utf-8"))
    ref_rel = (cast.get("references") or {}).get("close_up")
    if not ref_rel:
        print("The cast record has no close_up reference to measure against.")
        return 1
    ref = project / ref_rel

    plan = json.loads((project / "artifacts" / "scene_plan.json").read_text(encoding="utf-8"))
    heroes = project / "scene_look" / "heroes"
    scenes = [s for s in plan["scenes"] if (heroes / f"{s['id']}.png").exists()]

    paths = [ref] + [heroes / f"{s['id']}.png" for s in scenes]
    print(f"reference: {ref_rel}\nmeasuring {len(scenes)} stills ...\n")
    vecs = face_embeddings(paths)

    ref_vec, shot_vecs = vecs[0], vecs[1:]
    if ref_vec is None:
        print("No face found in the reference itself - nothing to measure against.")
        return 1

    import numpy as np
    rows, no_face = [], []
    for s, v in zip(scenes, shot_vecs):
        if v is None:
            no_face.append(s)
            continue
        rows.append((s, float(np.dot(ref_vec, v))))

    rows.sort(key=lambda r: r[1])
    drifted = [r for r in rows if r[1] < args.floor]

    print(f"{len(rows)} stills have a detectable face, "
          f"{len(no_face)} do not (wide, turned away, or she is absent).\n")
    for s, score in rows:
        size = s.get("shot_language", {}).get("shot_size", "?")
        mark = "DRIFT" if score < args.floor else "     "
        print(f"  {mark} {s['id']}  {score:.3f}  {size:13} {s['framing']}")

    if no_face:
        print("\nno face detected (not a failure):")
        print("  " + ", ".join(s["id"] for s in no_face))

    if rows:
        scores = [r[1] for r in rows]
        print(f"\nmean {sum(scores)/len(scores):.3f}   "
              f"lowest {min(scores):.3f}   highest {max(scores):.3f}")
    print(f"\n{len(drifted)} below the {args.floor} floor"
          + (": " + ", ".join(s["id"] for s, _ in drifted) if drifted else ""))

    out = project / "artifacts" / "identity_check.json"
    out.write_text(json.dumps({
        "reference": ref_rel,
        "floor": args.floor,
        "measured": [{"id": s["id"], "similarity": round(sc, 4),
                      "shot_size": s.get("shot_language", {}).get("shot_size"),
                      "location": s["framing"]} for s, sc in rows],
        "no_face": [s["id"] for s in no_face],
        "drifted": [s["id"] for s, _ in drifted],
        "note": ("ArcFace cosine against the cast record's close_up reference. "
                 "Measures the face only - not wardrobe, hair or grade. A "
                 "missing face is missing data, not drift."),
    }, indent=2), encoding="utf-8")
    print(f"written: {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
