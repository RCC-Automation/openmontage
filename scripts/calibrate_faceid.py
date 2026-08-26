"""Measure what FaceID strength actually buys, before spending hours on it.

    python scripts/calibrate_faceid.py

`weight_faceidv2` is the dial that decides whether a render is the anchor's face
or merely her type, and the node ships defaulting to 1.0 with no guidance. This
repo's record on guessed constants is four for four wrong (DECISIONS #27), so
the value that drives Phase 3 is measured here instead.

Two axes, because they answer different questions:

    weight_faceidv2   how hard the face is pushed. Too low and identity drifts;
                      too high and the prompt stops being obeyed - the failure
                      mode is a portrait that ignores the shot size you asked for.
    shot size         close-up vs wide. Our latent-reference measurement collapsed
                      0.932 -> 0.493 across exactly this change (DECISIONS #30).
                      Whether the embedding path survives it is the open question
                      Phase 3 rests on, and it is cheaper to answer in eight
                      renders than to discover in the wide family's budget.

**Identity alone is not the score.** The first pass here swept weight_faceidv2
and reported that wide shots held identity as well as close-ups - which was true
and meaningless, because at every weight tested the "wide" renders came back as
portraits. FaceID had overridden the framing, so nothing about a wide shot was
being measured. A conditioning strength that wins on cosine by refusing to obey
the prompt is not a win, and a sweep that only measures cosine cannot see it.

So every render is scored twice:

    cos_anchor      raw ArcFace cosine to the anchor. Is it her?
    face_fraction   the detected face box as a share of the frame. Did the
                    requested shot size actually happen? A close-up puts a face
                    across several percent of the frame; a full-figure wide puts
                    it under one. This is cheap, needs no extra model, and is
                    exactly the axis the runbook says matters most for captions.

`start_at` is swept for the same reason. Composition is decided in the first
fraction of the denoising trajectory, so holding the face conditioning off until
after it lets the prompt choose the framing and the adapter choose the face.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from lib.face_identity import faces_in  # noqa: E402
from lib.sheets import ACCENTS, SheetItem, labelled_sheet  # noqa: E402
from tools._comfyui.client import ComfyUIClient  # noqa: E402
from tools._comfyui.faceid import OUTPUT_NODE, build_faceid_graph  # noqa: E402

BRIEF = (
    "A clockwork heroine with luminous pink hair and a brass filigree collar, "
    "brass and copper plating at the shoulders, cinematic photograph, intricate detail"
)
SHOTS = {
    "close_up": "close-up portrait, head and shoulders",
    "wide": "wide shot, full figure standing in the environment",
}
BACKGROUND = "in a cluttered clockmaker's workshop, brass gears racked on the wall behind"


def _vector(path: Path) -> tuple[int, np.ndarray | None]:
    found = faces_in(path)
    if len(found) != 1:
        return len(found), None
    vector = getattr(found[0], "normed_embedding", None)
    if vector is None:
        return 0, None
    return 1, np.asarray(vector, dtype=np.float32)


def _face_fraction(path: Path) -> float | None:
    """Detected face box as a share of the frame. The shot-size witness.

    None when there is no single face - which for a wide shot is itself a
    finding, not a gap: a figure small enough that the detector loses the face
    is a figure too small to contribute identity to a training set.
    """
    found = faces_in(path)
    if len(found) != 1:
        return None
    try:
        from PIL import Image

        with Image.open(path) as handle:
            frame = float(handle.width * handle.height)
    except Exception:
        return None
    x1, y1, x2, y2 = found[0].bbox
    return float(abs((x2 - x1) * (y2 - y1)) / frame) if frame else None


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project", default="character-lora")
    parser.add_argument("--anchor", default=None)
    parser.add_argument("--weights", type=float, nargs="*", default=[1.0, 2.0, 3.0, 4.0])
    parser.add_argument(
        "--start-at", type=float, nargs="*", default=[0.0],
        help="Fraction of the trajectory to withhold face conditioning for.",
    )
    parser.add_argument("--lora-strength", type=float, default=0.6)
    parser.add_argument("--seed", type=int, default=770077)
    parser.add_argument("--tag", default="", help="Suffix for this run's outputs.")
    args = parser.parse_args()

    project_root = ROOT / "projects" / args.project
    anchor = Path(args.anchor) if args.anchor else project_root / "anchor" / "anchor.png"
    out_root = project_root / "calibration"
    out_root.mkdir(parents=True, exist_ok=True)

    faces, anchor_vector = _vector(anchor)
    if anchor_vector is None:
        print(f"FAIL: anchor has {faces} faces, need exactly 1: {anchor}")
        return 1
    print(f"anchor: {anchor}\n")

    client = ComfyUIClient()
    rows: list[dict] = []
    started = time.time()

    # A no-reference render of the same prompt is the framing control: it is what
    # the model does when nothing is fighting the shot size, and every FaceID
    # face_fraction has to be read against it rather than against intuition.
    baseline: dict[str, float | None] = {}
    for shot_name, shot_phrase in SHOTS.items():
        path = out_root / f"baseline_{shot_name}.png"
        prompt = ". ".join([BRIEF, shot_phrase, BACKGROUND])
        if not path.is_file():
            from tools.graphics.comfyui_image import ComfyUIImage

            ComfyUIImage().execute(
                {
                    "prompt": prompt,
                    "workflow_variant": "juggernaut_xl_ragnarok",
                    "checkpoint_name": "juggernautXL_ragnarok.safetensors",
                    "seed": args.seed,
                    "output_path": str(path),
                }
            )
        baseline[shot_name] = _face_fraction(path)
        share = baseline[shot_name]
        print(
            f"  baseline  {shot_name:9s} no reference   "
            f"face {'n/a' if share is None else format(share * 100, '.2f') + '%'}"
        )
    print()

    for shot_name, shot_phrase in SHOTS.items():
        for start_at in args.start_at:
            for weight in args.weights:
                suffix = f"_s{start_at:g}" if start_at else ""
                path = out_root / f"{shot_name}_w{weight:g}{suffix}{args.tag}.png"
                prompt = ". ".join([BRIEF, shot_phrase, BACKGROUND])
                if not path.is_file():
                    graph = build_faceid_graph(
                        prompt=prompt,
                        reference_image=anchor,
                        seed=args.seed,
                        weight_faceidv2=weight,
                        lora_strength=args.lora_strength,
                        start_at=start_at,
                    )
                    render_started = time.time()
                    try:
                        client.generate(
                            graph, output_node=OUTPUT_NODE, dest=path, timeout=600
                        )
                    except Exception as exc:
                        print(f"  {shot_name:9s} w={weight:<4g} FAILED: {str(exc)[:120]}")
                        rows.append(
                            {"shot": shot_name, "weight": weight, "error": str(exc)[:300]}
                        )
                        continue
                    elapsed = time.time() - render_started
                else:
                    elapsed = 0.0

                count, vector = _vector(path)
                cosine = None if vector is None else float(np.dot(anchor_vector, vector))
                share = _face_fraction(path)
                control = baseline.get(shot_name)
                # How far the framing was pulled from what the prompt alone did.
                # >1 means the face was enlarged, i.e. the shot size was overridden.
                drift = (
                    None
                    if share is None or not control
                    else round(share / control, 2)
                )
                rows.append(
                    {
                        "shot": shot_name,
                        "weight": weight,
                        "start_at": start_at,
                        "path": str(path),
                        "faces": count,
                        "cos_anchor": None if cosine is None else round(cosine, 4),
                        "face_fraction": None if share is None else round(share, 5),
                        "framing_drift_vs_baseline": drift,
                        "seconds": round(elapsed, 1),
                    }
                )
                text = "no face" if cosine is None else f"{cosine:.4f}"
                share_text = "n/a" if share is None else f"{share * 100:5.2f}%"
                drift_text = "n/a" if drift is None else f"{drift:4.2f}x"
                print(
                    f"  {shot_name:9s} w={weight:<4g} start={start_at:<4g} "
                    f"{elapsed:5.1f}s  cos {text}  face {share_text}  drift {drift_text}"
                )

    sheet = labelled_sheet(
        [
            SheetItem(
                Path(row["path"]),
                f"{row['shot']} w{row['weight']:g} s{row.get('start_at', 0):g}",
                (
                    "no face"
                    if row.get("cos_anchor") is None
                    else f"cos {row['cos_anchor']:.3f}  "
                    f"{(row.get('face_fraction') or 0) * 100:.1f}%"
                ),
                ACCENTS[0] if (row.get("cos_anchor") or 0) >= 0.70 else ACCENTS[3],
            )
            for row in rows
            if row.get("path")
        ],
        out_root / f"faceid_weights{args.tag}.png",
        columns=max(1, len(args.weights)),
        cell=340,
        title=(
            f"FaceID PlusV2 - weight x start_at at lora_strength {args.lora_strength}, "
            f"seed {args.seed}. cos = ArcFace vs anchor; % = face share of frame "
            "(the shot-size witness)."
        ),
    )

    report = {
        "version": "1.1",
        "anchor": str(anchor),
        "lora_strength": args.lora_strength,
        "seed": args.seed,
        "brief": BRIEF,
        "shots": SHOTS,
        "baseline_face_fraction": {
            name: None if share is None else round(share, 5)
            for name, share in baseline.items()
        },
        "measures": {
            "cos_anchor": "raw ArcFace cosine to the anchor - is it her",
            "face_fraction": "face box / frame area - did the requested shot size happen",
            "framing_drift_vs_baseline": (
                "face_fraction divided by the no-reference render's. >1 means "
                "FaceID enlarged the subject and overrode the prompt's shot size."
            ),
        },
        "rows": rows,
        "sheet": None if sheet is None else str(sheet),
        "minutes": round((time.time() - started) / 60, 2),
    }
    (out_root / f"faceid_calibration{args.tag}.json").write_text(
        json.dumps(report, indent=2), encoding="utf-8"
    )

    print(f"\nsheet : {sheet}")
    print(f"report: {out_root / f'faceid_calibration{args.tag}.json'}")

    # The operating point has to win on both axes. Ranked by identity among the
    # settings that did not blow the framing, so a high-cosine portrait that was
    # asked to be a wide shot cannot be reported as the best setting.
    honest = [
        r
        for r in rows
        if r.get("cos_anchor") is not None
        and (r.get("framing_drift_vs_baseline") or 99) <= 1.5
    ]
    if honest:
        top = max(honest, key=lambda r: r["cos_anchor"])
        print(
            f"\nbest setting that kept its framing: {top['shot']} "
            f"weight {top['weight']:g} start_at {top.get('start_at', 0):g} -> "
            f"cos {top['cos_anchor']:.4f}, framing drift "
            f"{top['framing_drift_vs_baseline']}x"
        )
    else:
        print("\n! no setting held identity without distorting the framing")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
