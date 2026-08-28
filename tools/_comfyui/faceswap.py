"""Transplant a chosen face onto a render, with ReActor.

The third identity mechanism, and the one that does not re-imagine the face.

    Klein / SDXL reference  generates a plausible person from a hint. Measured
                            0.53-0.68 here: a family resemblance.
    IP-Adapter FaceID       conditions on a pose-normalised ArcFace vector.
                            Measured 0.75-0.84 - but it normalises TOWARD its
                            training distribution, which on this character
                            reshaped an adult woman into a teenager. Consistent,
                            and consistently the wrong person.
    ReActor / inswapper     copies the source face onto the target and blends.
                            No generation, so no re-imagining.

So the pipeline splits in two: render freely for the body, wardrobe, pose and
scene, then put the anchor's actual face on it. Whatever the base model does
with "athletic, sweaty, festival" is preserved, because the swap only touches
the face region.

`face_restore_model` matters more than it looks. inswapper works at 128x128, so
a bare swap is soft against a 1216px frame. GFPGAN or CodeFormer re-detail it -
and `face_restore_visibility` blends restored against raw, so the plastic look
that sank the FaceID route can be dialled down rather than accepted.

**Licence:** InsightFace's pre-trained models, `inswapper_128` included, are
released for non-commercial research use only. Flagged in the caller, not
enforced here.

**Path trap:** ReActor globs `folder_paths.models_dir/insightface/*.onnx`
directly rather than going through the registered folder paths, and on ComfyUI
Desktop `models_dir` is the *install* tree, not the Shared one that holds the
checkpoints. The model has to sit in `<install>/models/insightface/`.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

__all__ = ["OUTPUT_NODE", "build_faceswap_graph"]

#: SaveImage, for `ComfyUIClient.generate(..., output_node=...)`.
OUTPUT_NODE = "20"


def build_faceswap_graph(
    *,
    source_face: Path | str,
    target_image: Path | str,
    swap_model: str = "inswapper_128.onnx",
    facedetection: str = "retinaface_resnet50",
    face_restore_model: str = "GFPGANv1.4.pth",
    face_restore_visibility: float = 0.8,
    codeformer_weight: float = 0.5,
    detect_gender_source: str = "no",
    detect_gender_input: str = "no",
    source_faces_index: str = "0",
    input_faces_index: str = "0",
    boost_model: str | None = None,
    boost_visibility: float = 1.0,
    boost_interpolation: str = "Lanczos",
    boost_codeformer_weight: float = 0.5,
    boost_restore_with_main_after: bool = False,
    filename_prefix: str = "image/Swapped",
) -> dict[str, Any]:
    """Put `source_face`'s face onto `target_image`.

    `face_restore_visibility` is the dial worth moving: 1.0 is fully restored
    and can read as airbrushed, 0.1 leaves the raw 128px swap soft. Both images
    load by absolute path, so nothing has to be copied into ComfyUI's input
    directory first.

    `boost_model` attacks the softness at its source. inswapper produces a
    128x128 face, and pasting that into a 1216px frame is a resolution mismatch
    no amount of post-restore fully hides - the face reads blurred against a
    sharp body, which a LoRA would then learn as her texture. FaceBoost
    upscales and restores the face *before* it is blended back, so the detail is
    reconstructed at working resolution rather than smeared up from 128px.
    """
    graph: dict[str, Any] = {}
    swap_inputs: dict[str, Any] = {}
    if boost_model and boost_model != "none":
        graph["13"] = {
            "class_type": "ReActorFaceBoost",
            "inputs": {
                "enabled": True,
                "boost_model": boost_model,
                "interpolation": boost_interpolation,
                "visibility": float(boost_visibility),
                "codeformer_weight": float(boost_codeformer_weight),
                "restore_with_main_after": bool(boost_restore_with_main_after),
            },
        }
        swap_inputs["face_boost"] = ["13", 0]
    graph.update({
        "10": {
            "class_type": "VHS_LoadImagePath",
            "inputs": {
                "image": str(Path(target_image).resolve()),
                "custom_width": 0,
                "custom_height": 0,
            },
        },
        "11": {
            "class_type": "VHS_LoadImagePath",
            "inputs": {
                "image": str(Path(source_face).resolve()),
                "custom_width": 0,
                "custom_height": 0,
            },
        },
        "12": {
            "class_type": "ReActorFaceSwap",
            "inputs": {
                "enabled": True,
                "input_image": ["10", 0],
                "source_image": ["11", 0],
                "swap_model": swap_model,
                "facedetection": facedetection,
                "face_restore_model": face_restore_model,
                "face_restore_visibility": float(face_restore_visibility),
                "codeformer_weight": float(codeformer_weight),
                "detect_gender_input": detect_gender_input,
                "detect_gender_source": detect_gender_source,
                "input_faces_index": input_faces_index,
                "source_faces_index": source_faces_index,
                "console_log_level": 1,
                **swap_inputs,
            },
        },
        "20": {
            "class_type": "SaveImage",
            "inputs": {"filename_prefix": filename_prefix, "images": ["12", 0]},
        },
    })
    return graph
