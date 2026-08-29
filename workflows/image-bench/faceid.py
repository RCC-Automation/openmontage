"""IP-Adapter FaceID - the last identity mechanism with no number here.

Fills the gap in the character bench. FaceID conditions on a pose-normalised
ArcFace embedding rather than on image tokens, so in principle it should survive
a framing change where reference-latent conditioning collapses. This measures
whether it does, at both shot sizes, against the same anchor.

    python workflows/image-bench/faceid.py --project projects/burningman

Settings come from wiki/character/faceid-on-this-machine.md, which was measured
here: lora_strength is the strongest dial (0.6 -> 1.0 moved identity
0.685 -> 0.750), and `start_at` 0.4 exists because FaceID applied from step zero
overrides the prompt's shot size and turns every wide into a portrait.
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import numpy as np  # noqa: E402

from lib.face_identity import face_embeddings  # noqa: E402
from run_character import (  # noqa: E402
    COMFY_INPUT, FRAMINGS, H, MEASURABLE_FACE_FRACTION, NEGATIVE, SUBJECT, W,
    face_fraction, submit,
)

BASE_CKPT = "juggernautXL_ragnarok.safetensors"


def faceid_graph(face_image: str, prompt: str, seed: int, *, lora_strength: float = 0.9,
                 weight: float = 1.0, weight_v2: float = 1.0, start_at: float = 0.0,
                 steps: int = 30, cfg: float = 4.5) -> dict:
    """CheckpointLoader -> IPAdapterUnifiedLoaderFaceID -> IPAdapterFaceID -> KSampler.

    `provider` is CPU and must stay CPU: the dropdown offers CUDA and ROCM and
    neither works on this machine (wiki/character/faceid-on-this-machine.md).
    """
    return {
        "1": {"class_type": "CheckpointLoaderSimple", "inputs": {"ckpt_name": BASE_CKPT},
              "_meta": {"title": "model"}},
        "20": {"class_type": "LoadImage", "inputs": {"image": face_image},
               "_meta": {"title": "her face"}},
        "21": {"class_type": "IPAdapterUnifiedLoaderFaceID",
               "inputs": {"model": ["1", 0], "preset": "FACEID PLUS V2",
                          "lora_strength": lora_strength, "provider": "CPU"},
               "_meta": {"title": "faceid loader"}},
        "22": {"class_type": "IPAdapterFaceID",
               "inputs": {"model": ["21", 0], "ipadapter": ["21", 1], "image": ["20", 0],
                          "weight": weight, "weight_faceidv2": weight_v2,
                          "weight_type": "linear", "combine_embeds": "concat",
                          "start_at": start_at, "end_at": 1.0, "embeds_scaling": "V only"},
               "_meta": {"title": "faceid"}},
        "2": {"class_type": "CLIPTextEncode", "inputs": {"text": prompt, "clip": ["1", 1]},
              "_meta": {"title": "positive"}},
        "3": {"class_type": "CLIPTextEncode", "inputs": {"text": NEGATIVE, "clip": ["1", 1]},
              "_meta": {"title": "negative"}},
        "4": {"class_type": "EmptyLatentImage",
              "inputs": {"width": W, "height": H, "batch_size": 1}, "_meta": {"title": "latent"}},
        "5": {"class_type": "KSampler",
              "inputs": {"model": ["22", 0], "positive": ["2", 0], "negative": ["3", 0],
                         "latent_image": ["4", 0], "seed": seed, "steps": steps, "cfg": cfg,
                         "sampler_name": "dpmpp_2m_sde", "scheduler": "karras", "denoise": 1.0},
              "_meta": {"title": "sampler"}},
        "6": {"class_type": "VAEDecode", "inputs": {"samples": ["5", 0], "vae": ["1", 2]}},
        "7": {"class_type": "SaveImage", "inputs": {"images": ["6", 0],
              "filename_prefix": "char/faceid"}, "_meta": {"title": "save"}},
    }


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--project", default="projects/burningman")
    ap.add_argument("--seed", type=int, default=7900)
    args = ap.parse_args()

    project = Path(args.project)
    anchor = project / "anchor" / "anchor.png"
    face = project / "anchor" / "anchor_face.png"
    staged = "char_anchor_face.png"
    shutil.copy2(face, COMFY_INPUT / staged)

    runs = []
    for framing in ("closeup", "fullbody"):
        prompt = f"{SUBJECT}. {FRAMINGS[framing]}"
        out = project / ("model-bench" if framing == "closeup" else "model-bench-fullbody")
        # start_at 0 is the strongest identity; 0.4 is the setting that lets the
        # prompt keep its shot size. On a close-up they should agree, on a full
        # body they should not - which is the whole question.
        for start_at, tag in ((0.0, "s0"), (0.4, "s04")):
            runs.append((framing, out / f"id_faceid_{tag}.png",
                         f"FaceID start_at {start_at}",
                         faceid_graph(staged, prompt, args.seed + int(start_at * 10),
                                      start_at=start_at)))

    made = []
    for framing, dest, label, graph in runs:
        print(f"  {framing:9} {label}")
        secs = submit(graph, dest)
        print(f"    {'FAILED' if secs is None else f'{secs:7.1f}s'}")
        if secs is not None:
            made.append((framing, dest, label, secs))

    if not made or not anchor.is_file():
        return 1
    vectors = face_embeddings([anchor] + [d for _f, d, _l, _s in made])
    ref = vectors[0]
    print(f"\n{'framing':10} {'setting':22} {'identity':>9} {'face':>7}")
    for (framing, dest, label, secs), vec in zip(made, vectors[1:]):
        frac = face_fraction(dest)
        cos = None if (ref is None or vec is None) else round(float(np.dot(ref, vec)), 3)
        trusted = frac is not None and frac >= MEASURABLE_FACE_FRACTION
        shown = "no face" if cos is None else (f"{cos:.3f}" if trusted else f"({cos:.3f})*")
        print(f"{framing:10} {label:22} {shown:>9} {'' if frac is None else f'{frac*100:6.2f}%'}")
        # fold into that framing's results.json so the sheets pick it up
        rf = dest.parent / "results.json"
        rows = json.loads(rf.read_text(encoding="utf-8")) if rf.is_file() else []
        rows = [r for r in rows if r.get("key") != dest.stem]
        rows.append({"key": dest.stem, "label": f"IP-Adapter {label}", "family": "identity",
                     "mode": "conditioned", "seconds": secs, "identity": cos,
                     "face_fraction": frac, "measurable": bool(trusted)})
        rf.write_text(json.dumps(rows, indent=1), encoding="utf-8")
    print("\n  * parenthesised = face too small for the number to mean anything")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
