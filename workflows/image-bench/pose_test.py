"""Pose control on the bystander problem - the version that should actually work.

Canny ControlNet failed at this for a reason worth stating: canny encodes EVERY
edge in the control image, so a festival scene hands the model its background
crowd along with the subject. Measured 2026-08-29: realismIllustrious went 7
people -> 3, not 7 -> 1.

Pose control is different in kind. A pose map contains only skeletons, and
RTDETR_detect takes `max_detections` - so the control image can be forced to
describe exactly one person, and the crowd cannot come along.

    python workflows/image-bench/pose_test.py

The chain is: detect people -> keep N of them -> extract keypoints -> draw a
pose map -> condition on it. The shipped 'Pose to Image (Z-Image-Turbo)'
blueprint is only the last step; it takes a finished pose map and contains no
detector, which is why SDPose has to be wired in front of it.
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

SDPOSE = "sdpose_wholebody_fp16.safetensors"
RTDETR = "rt_detr_v4-x-hgnet_fp16.safetensors"
Z_CONTROLNET = "Z-Image-Turbo-Fun-Controlnet-Union-2.1-lite-2602-8steps.safetensors"
SDXL_CONTROLNET = "controlnet-union-sdxl-1.0-promax.safetensors"
W, H = 1280, 720


def _pose_chain(control_image: str, max_people: int = 1, first_node: int = 30) -> dict:
    """Detect -> limit -> keypoints -> pose map. Returns nodes; the drawn map is
    at node str(first_node + 4).

    `max_detections` is the whole point: it is where "exactly one person" is
    enforced, before the diffusion model ever sees anything.
    """
    n = first_node
    return {
        str(n): {"class_type": "LoadImage", "inputs": {"image": control_image},
                 "_meta": {"title": "structure source"}},
        str(n + 1): {"class_type": "ImageScale",
                     "inputs": {"image": [str(n), 0], "upscale_method": "lanczos",
                                "width": W, "height": H, "crop": "center"},
                     "_meta": {"title": "fit"}},
        str(n + 2): {"class_type": "CheckpointLoaderSimple", "inputs": {"ckpt_name": SDPOSE},
                     "_meta": {"title": "sdpose"}},
        str(n + 5): {"class_type": "UNETLoader", "inputs": {"unet_name": RTDETR,
                     "weight_dtype": "default"}, "_meta": {"title": "person detector"}},
        str(n + 6): {"class_type": "RTDETR_detect",
                     "inputs": {"model": [str(n + 5), 0], "image": [str(n + 1), 0],
                                "threshold": 0.35, "class_name": "person",
                                "max_detections": max_people},
                     "_meta": {"title": f"keep {max_people} person(s)"}},
        str(n + 3): {"class_type": "SDPoseKeypointExtractor",
                     "inputs": {"model": [str(n + 2), 0], "vae": [str(n + 2), 2],
                                "image": [str(n + 1), 0], "batch_size": 1,
                                "bboxes": [str(n + 6), 0]},
                     "_meta": {"title": "keypoints"}},
        str(n + 4): {"class_type": "SDPoseDrawKeypoints",
                     "inputs": {"keypoints": [str(n + 3), 0], "draw_body": True,
                                "draw_hands": True, "draw_face": True, "draw_feet": True,
                                "stick_width": 4, "face_point_size": 3,
                                "score_threshold": 0.3, "draw_head": True},
                     "_meta": {"title": "pose map"}},
    }


def zimage_pose(control_image: str, prompt: str, seed: int, unet: str,
                strength: float = 0.7, steps: int = 8, max_people: int = 1) -> dict:
    pose = _pose_chain(control_image, max_people)
    g = {
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
        "23": {"class_type": "ModelPatchLoader", "inputs": {"name": Z_CONTROLNET},
               "_meta": {"title": "controlnet patch"}},
        "24": {"class_type": "QwenImageDiffsynthControlnet",
               "inputs": {"model": ["1", 0], "model_patch": ["23", 0], "vae": ["3", 0],
                          "image": ["34", 0], "strength": strength},
               "_meta": {"title": "apply pose control"}},
        "7": {"class_type": "ModelSamplingAuraFlow", "inputs": {"model": ["24", 0], "shift": 3.0},
              "_meta": {"title": "shift"}},
        "8": {"class_type": "KSampler",
              "inputs": {"model": ["7", 0], "positive": ["4", 0], "negative": ["5", 0],
                         "latent_image": ["6", 0], "seed": seed, "steps": steps, "cfg": 1.0,
                         "sampler_name": "res_multistep", "scheduler": "simple", "denoise": 1.0},
              "_meta": {"title": "sampler"}},
        "9": {"class_type": "VAEDecode", "inputs": {"samples": ["8", 0], "vae": ["3", 0]}},
        "10": {"class_type": "SaveImage", "inputs": {"images": ["9", 0],
               "filename_prefix": "pose/zimage"}, "_meta": {"title": "save"}},
        # keep the pose map itself, so a failure is diagnosable as "the map was
        # wrong" rather than "the model ignored it"
        "11": {"class_type": "SaveImage", "inputs": {"images": ["34", 0],
               "filename_prefix": "pose/map"}, "_meta": {"title": "save pose map"}},
    }
    g.update(pose)
    return g


def sdxl_pose(control_image: str, prompt: str, seed: int, ckpt: str, strength: float = 0.7,
              steps: int = 27, cfg: float = 4.5, max_people: int = 1) -> dict:
    pose = _pose_chain(control_image, max_people)
    g = {
        "1": {"class_type": "CheckpointLoaderSimple", "inputs": {"ckpt_name": ckpt},
              "_meta": {"title": "model"}},
        "2": {"class_type": "CLIPTextEncode", "inputs": {"text": prompt, "clip": ["1", 1]},
              "_meta": {"title": "positive"}},
        "3": {"class_type": "CLIPTextEncode", "inputs": {"text": NEGATIVE, "clip": ["1", 1]},
              "_meta": {"title": "negative"}},
        "23": {"class_type": "ControlNetLoader", "inputs": {"control_net_name": SDXL_CONTROLNET},
               "_meta": {"title": "controlnet"}},
        "24": {"class_type": "SetUnionControlNetType",
               "inputs": {"control_net": ["23", 0], "type": "openpose"},
               "_meta": {"title": "control type: openpose"}},
        "25": {"class_type": "ControlNetApplyAdvanced",
               "inputs": {"positive": ["2", 0], "negative": ["3", 0], "control_net": ["24", 0],
                          "image": ["34", 0], "strength": strength,
                          "start_percent": 0.0, "end_percent": 0.8, "vae": ["1", 2]},
               "_meta": {"title": "apply pose control"}},
        "4": {"class_type": "EmptyLatentImage",
              "inputs": {"width": W, "height": H, "batch_size": 1}, "_meta": {"title": "latent"}},
        "5": {"class_type": "KSampler",
              "inputs": {"model": ["1", 0], "positive": ["25", 0], "negative": ["25", 1],
                         "latent_image": ["4", 0], "seed": seed, "steps": steps, "cfg": cfg,
                         "sampler_name": "dpmpp_2m_sde", "scheduler": "karras", "denoise": 1.0},
              "_meta": {"title": "sampler"}},
        "6": {"class_type": "VAEDecode", "inputs": {"samples": ["5", 0], "vae": ["1", 2]}},
        "7": {"class_type": "SaveImage", "inputs": {"images": ["6", 0],
              "filename_prefix": "pose/sdxl"}, "_meta": {"title": "save"}},
        "11": {"class_type": "SaveImage", "inputs": {"images": ["34", 0],
               "filename_prefix": "pose/map"}, "_meta": {"title": "save pose map"}},
    }
    g.update(pose)
    return g


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--out", default="projects/burningman/pose")
    ap.add_argument("--control", default="projects/burningman/model-bench-fullbody/flux1_dev.png",
                    help="a full-body image with a crowd in it - the hard case")
    ap.add_argument("--seed", type=int, default=8300)
    ap.add_argument("--strength", type=float, default=0.7)
    args = ap.parse_args()

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    staged = "pose_control.png"
    shutil.copy2(Path(args.control), COMFY_INPUT / staged)
    prompt = f"{SUBJECT}. {FRAMINGS['fullbody']}"

    jobs = [
        ("pose_zimage_darkbeast", "darkBeast30 + pose (canny gave 2)",
         zimage_pose(staged, prompt, args.seed,
                     "darkBeast30BF16INT8_dbzit9DIMRclaw.safetensors", args.strength)),
        ("pose_sdxl_realismill", "realismIllustrious + pose (canny gave 3)",
         sdxl_pose(staged, prompt, args.seed,
                   "realismIllustriousBy_v50FP16.safetensors", args.strength, 27, 5.0)),
        ("pose_sdxl_babesill", "babesIllustrious + pose (canny gave 1)",
         sdxl_pose(staged, prompt, args.seed,
                   "babesIllustriousBy_v50BF16.safetensors", args.strength, 27, 4.5)),
    ]

    print(f"control: {args.control}\nstrength {args.strength}, max_detections 1\n")
    for key, label, graph in jobs:
        dest = out / f"{key}.png"
        print(f"  {label}")
        secs = submit(graph, dest)
        if secs is None:
            print("    FAILED")
            continue
        c = check_shot(dest, "fullbody")
        print(f"    {secs:7.1f}s   {c.faces} face(s)   {c.verdict}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
