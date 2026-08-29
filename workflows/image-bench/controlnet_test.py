"""Does ControlNet fix the bystander problem?

The measured failure across this pool is not framing - all 18 models obeyed
"full body" - it is SUBJECT COUNT. 13 of 36 renders contained people nobody
asked for, up to seven in one frame. And because identity is scored on the
largest face, some of those scores may have been measuring a stranger.

ControlNet is the obvious fix, because a control image contains exactly one
person and the model is conditioned on that structure rather than asked politely
for it. This tests it on the two families that actually failed, using each
family's own ControlNet:

  Z-Image  -> ModelPatchLoader + QwenImageDiffsynthControlnet (a model patch)
  SDXL     -> ControlNetLoader + SetUnionControlNetType + ControlNetApplyAdvanced

    python workflows/image-bench/controlnet_test.py

Verdict is the face count, not a taste judgement.
"""

from __future__ import annotations

import argparse
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from lib.shot_size import check_shot  # noqa: E402
from run_character import COMFY_INPUT, FRAMINGS, NEGATIVE, SUBJECT, submit  # noqa: E402

Z_CONTROLNET = "Z-Image-Turbo-Fun-Controlnet-Union-2.1-lite-2602-8steps.safetensors"
SDXL_CONTROLNET = "controlnet-union-sdxl-1.0-promax.safetensors"
W, H = 1280, 720


def _canny(image_node: str, low: float = 0.2, high: float = 0.6) -> dict:
    return {"class_type": "Canny", "inputs": {"image": [image_node, 0],
            "low_threshold": low, "high_threshold": high}, "_meta": {"title": "canny"}}


def zimage_controlnet(control_image: str, prompt: str, seed: int, unet: str,
                      strength: float = 0.7, steps: int = 8) -> dict:
    """Z-Image ControlNet is a MODEL PATCH, not a conditioning branch: the
    control enters through QwenImageDiffsynthControlnet, which returns a patched
    MODEL. That is why it lives in model_patches/ and not controlnet/."""
    return {
        "1": {"class_type": "UNETLoader", "inputs": {"unet_name": unet, "weight_dtype": "default"},
              "_meta": {"title": "model"}},
        "2": {"class_type": "CLIPLoader", "inputs": {"clip_name": "qwen3_4b_fp8_scaled.safetensors",
              "type": "lumina2", "device": "default"}, "_meta": {"title": "encoder"}},
        "3": {"class_type": "VAELoader", "inputs": {"vae_name": "ae.safetensors"},
              "_meta": {"title": "vae"}},
        "4": {"class_type": "CLIPTextEncode", "inputs": {"text": prompt, "clip": ["2", 0]},
              "_meta": {"title": "positive"}},
        "5": {"class_type": "ConditioningZeroOut", "inputs": {"conditioning": ["4", 0]},
              "_meta": {"title": "negative (zeroed)"}},
        "6": {"class_type": "EmptySD3LatentImage",
              "inputs": {"width": W, "height": H, "batch_size": 1}, "_meta": {"title": "latent"}},
        "20": {"class_type": "LoadImage", "inputs": {"image": control_image},
               "_meta": {"title": "structure source"}},
        "21": {"class_type": "ImageScale", "inputs": {"image": ["20", 0], "upscale_method": "lanczos",
               "width": W, "height": H, "crop": "center"}, "_meta": {"title": "fit"}},
        "22": _canny("21"),
        "23": {"class_type": "ModelPatchLoader", "inputs": {"name": Z_CONTROLNET},
               "_meta": {"title": "controlnet patch"}},
        "24": {"class_type": "QwenImageDiffsynthControlnet",
               "inputs": {"model": ["1", 0], "model_patch": ["23", 0], "vae": ["3", 0],
                          "image": ["22", 0], "strength": strength},
               "_meta": {"title": "apply controlnet"}},
        "7": {"class_type": "ModelSamplingAuraFlow", "inputs": {"model": ["24", 0], "shift": 3.0},
              "_meta": {"title": "shift"}},
        "8": {"class_type": "KSampler",
              "inputs": {"model": ["7", 0], "positive": ["4", 0], "negative": ["5", 0],
                         "latent_image": ["6", 0], "seed": seed, "steps": steps, "cfg": 1.0,
                         "sampler_name": "res_multistep", "scheduler": "simple", "denoise": 1.0},
              "_meta": {"title": "sampler"}},
        "9": {"class_type": "VAEDecode", "inputs": {"samples": ["8", 0], "vae": ["3", 0]}},
        "10": {"class_type": "SaveImage", "inputs": {"images": ["9", 0],
               "filename_prefix": "cn/zimage"}, "_meta": {"title": "save"}},
    }


def sdxl_controlnet(control_image: str, prompt: str, seed: int, ckpt: str,
                    strength: float = 0.7, steps: int = 27, cfg: float = 4.5) -> dict:
    """SDXL takes the classic conditioning-branch route. SetUnionControlNetType
    tells the union model which of its eight control types this is."""
    return {
        "1": {"class_type": "CheckpointLoaderSimple", "inputs": {"ckpt_name": ckpt},
              "_meta": {"title": "model"}},
        "2": {"class_type": "CLIPTextEncode", "inputs": {"text": prompt, "clip": ["1", 1]},
              "_meta": {"title": "positive"}},
        "3": {"class_type": "CLIPTextEncode", "inputs": {"text": NEGATIVE, "clip": ["1", 1]},
              "_meta": {"title": "negative"}},
        "20": {"class_type": "LoadImage", "inputs": {"image": control_image},
               "_meta": {"title": "structure source"}},
        "21": {"class_type": "ImageScale", "inputs": {"image": ["20", 0], "upscale_method": "lanczos",
               "width": W, "height": H, "crop": "center"}, "_meta": {"title": "fit"}},
        "22": _canny("21"),
        "23": {"class_type": "ControlNetLoader", "inputs": {"control_net_name": SDXL_CONTROLNET},
               "_meta": {"title": "controlnet"}},
        "24": {"class_type": "SetUnionControlNetType",
               "inputs": {"control_net": ["23", 0], "type": "canny/lineart/anime_lineart/mlsd"},
               "_meta": {"title": "control type"}},
        "25": {"class_type": "ControlNetApplyAdvanced",
               "inputs": {"positive": ["2", 0], "negative": ["3", 0], "control_net": ["24", 0],
                          "image": ["22", 0], "strength": strength,
                          "start_percent": 0.0, "end_percent": 0.8, "vae": ["1", 2]},
               "_meta": {"title": "apply controlnet"}},
        "4": {"class_type": "EmptyLatentImage",
              "inputs": {"width": W, "height": H, "batch_size": 1}, "_meta": {"title": "latent"}},
        "5": {"class_type": "KSampler",
              "inputs": {"model": ["1", 0], "positive": ["25", 0], "negative": ["25", 1],
                         "latent_image": ["4", 0], "seed": seed, "steps": steps, "cfg": cfg,
                         "sampler_name": "dpmpp_2m_sde", "scheduler": "karras", "denoise": 1.0},
              "_meta": {"title": "sampler"}},
        "6": {"class_type": "VAEDecode", "inputs": {"samples": ["5", 0], "vae": ["1", 2]}},
        "7": {"class_type": "SaveImage", "inputs": {"images": ["6", 0],
              "filename_prefix": "cn/sdxl"}, "_meta": {"title": "save"}},
    }


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--out", default="projects/burningman/controlnet")
    ap.add_argument("--control", default="projects/burningman/anchor/anchor.png",
                    help="the single-subject image whose structure is imposed")
    ap.add_argument("--seed", type=int, default=8100)
    ap.add_argument("--strength", type=float, default=0.7)
    args = ap.parse_args()

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    staged = "cn_control.png"
    shutil.copy2(Path(args.control), COMFY_INPUT / staged)
    prompt = f"{SUBJECT}. {FRAMINGS['fullbody']}"

    # The two worst offenders that have a ControlNet for their family.
    jobs = [
        ("cn_zimage_darkbeast", "darkBeast30 + Z-Image ControlNet (was 2 people)",
         zimage_controlnet(staged, prompt, args.seed,
                           "darkBeast30BF16INT8_dbzit9DIMRclaw.safetensors", args.strength)),
        ("cn_sdxl_realismill", "realismIllustrious + SDXL ControlNet (was 7 people)",
         sdxl_controlnet(staged, prompt, args.seed,
                         "realismIllustriousBy_v50FP16.safetensors", args.strength, steps=27, cfg=5.0)),
        ("cn_sdxl_babesill", "babesIllustrious + SDXL ControlNet (was 4 people)",
         sdxl_controlnet(staged, prompt, args.seed,
                         "babesIllustriousBy_v50BF16.safetensors", args.strength, steps=27, cfg=4.5)),
    ]

    print(f"control image: {args.control}  strength {args.strength}\n")
    results = []
    for key, label, graph in jobs:
        dest = out / f"{key}.png"
        print(f"  {label}")
        secs = submit(graph, dest)
        if secs is None:
            print("    FAILED")
            continue
        c = check_shot(dest, "fullbody")
        print(f"    {secs:7.1f}s   {c.faces} face(s)   {c.verdict}")
        results.append((label, c, secs))

    print("\n  before -> after, people in frame:")
    for label, c, _s in results:
        was = label.split("was ")[-1].rstrip(")")
        print(f"    {label.split(' +')[0]:22} {was:10} -> {c.faces}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
