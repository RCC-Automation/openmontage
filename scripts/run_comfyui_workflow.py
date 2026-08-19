"""Run a profile-bound ComfyUI video workflow through OpenMontage.

This is an integration/diagnostic entry point. Full productions should still
use an OpenMontage pipeline and its checkpoint workflow.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools.video.comfyui_video import ComfyUIVideo  # noqa: E402


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run a custom ComfyUI video workflow with a binding profile."
    )
    parser.add_argument("--workflow", required=True, help="API-format workflow JSON")
    parser.add_argument("--profile", required=True, help="Workflow profile JSON")
    parser.add_argument("--prompt", required=True)
    parser.add_argument("--output", required=True, help="Destination MP4")
    parser.add_argument("--negative-prompt")
    parser.add_argument("--pose-prompt")
    parser.add_argument(
        "--operation",
        choices=("text_to_video", "image_to_video"),
        default="image_to_video",
    )
    parser.add_argument("--reference-image")
    parser.add_argument("--first-frame")
    parser.add_argument("--last-frame")
    parser.add_argument("--driving-video")
    parser.add_argument("--width", type=int)
    parser.add_argument("--height", type=int)
    parser.add_argument("--frames", type=int)
    parser.add_argument("--duration", type=float, dest="duration_seconds")
    parser.add_argument("--fps", type=float)
    parser.add_argument("--seed", type=int)
    parser.add_argument("--timeout", type=int, default=7200)
    parser.add_argument("--workflow-name")
    parser.add_argument("--workflow-model")
    parser.add_argument("--filename-prefix")
    return parser


def main() -> int:
    args = _parser().parse_args()
    inputs = {
        "prompt": args.prompt,
        "operation": args.operation,
        "workflow_path": str(Path(args.workflow).resolve()),
        "workflow_profile_path": str(Path(args.profile).resolve()),
        "output_path": str(Path(args.output).resolve()),
        "timeout_seconds": args.timeout,
    }
    optional = {
        "negative_prompt": args.negative_prompt,
        "pose_prompt": args.pose_prompt,
        "reference_image_path": args.reference_image,
        "first_frame_path": args.first_frame,
        "last_frame_path": args.last_frame,
        "driving_video_path": args.driving_video,
        "width": args.width,
        "height": args.height,
        "num_frames": args.frames,
        "duration_seconds": args.duration_seconds,
        "fps": args.fps,
        "seed": args.seed,
        "workflow_name": args.workflow_name,
        "workflow_model": args.workflow_model,
        "filename_prefix": args.filename_prefix,
    }
    inputs.update({key: value for key, value in optional.items() if value is not None})

    result = ComfyUIVideo().execute(inputs)
    print(
        json.dumps(
            {
                "success": result.success,
                "error": result.error,
                "data": result.data,
                "artifacts": result.artifacts,
                "seed": result.seed,
                "runtime_seconds": result.duration_seconds,
            },
            indent=2,
            default=str,
        )
    )
    return 0 if result.success else 1


if __name__ == "__main__":
    raise SystemExit(main())
