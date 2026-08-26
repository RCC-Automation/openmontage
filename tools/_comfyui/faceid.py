"""An SDXL graph conditioned on a face, for building a character dataset.

The bundled `juggernaut-xl-ragnarok-txt2img` workflow is plain text-to-image:
checkpoint into one KSampler. Phase 3 needs the same sampler driven by a
*reference face*, which means two nodes between the checkpoint and the sampler:

    CheckpointLoaderSimple
      -> IPAdapterUnifiedLoaderFaceID   loads the adapter, the CLIP-vision
      |                                 encoder and the FaceID LoRA, and returns
      |                                 a model with that LoRA already applied
      -> IPAdapterFaceID                attends to the anchor's ArcFace vector
      -> KSampler

Why the embedding path rather than the latent one: we measured a latent/pixel
reference collapse from 0.932 to 0.301 when the framing changed (DECISIONS #30).
FaceID conditions on a *pose-normalised* ArcFace vector instead of image tokens,
which the research says should survive that. Phase 3's wide family is where the
claim gets tested on this machine.

Three things here are load-bearing and none are obvious:

**`provider` must be CPU.** The picker offers CUDA and ROCM, and this machine's
ComfyUI venv carries `onnxruntime-gpu`, which cheerfully advertises
`CUDAExecutionProvider` and `TensorrtExecutionProvider` on a box with no CUDA.
Only `CPUExecutionProvider` actually runs (HANDOFF; runbook Phase 1). Choosing
by what the dropdown offers is how that becomes a runtime error deep in a batch.

**The reference is loaded by absolute path.** Core `LoadImage` reads from
ComfyUI's own `input/` directory and takes a *filename from an enum*, so using it
would mean copying every anchor into ComfyUI's tree and re-reading `object_info`
to see it appear. `VHS_LoadImagePath` takes a path string, so the anchor can stay
in the project where the evidence lives.

**The CLIP-vision file needs its long name.** The loader matches on filename;
`clip_vision_h.safetensors` will not be found, which is why Phase 1 copied it to
`CLIP-ViT-H-14-laion2B-s32B-b79K.safetensors`. The unified loader picks it up by
that name on its own.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

__all__ = [
    "DEFAULT_NEGATIVE",
    "FACEID_PRESET",
    "OUTPUT_NODE",
    "build_faceid_graph",
]

#: SDXL FaceID PlusV2 - matches the adapter Phase 1 installed
#: (`ip-adapter-faceid-plusv2_sdxl.bin` plus its LoRA).
FACEID_PRESET = "FACEID PLUS V2"

#: The SaveImage node, for `ComfyUIClient.generate(..., output_node=...)`.
OUTPUT_NODE = "7"

#: Aimed at what actually spoils a training set rather than at generic "quality"
#: tokens. `multiple people` matters most: the pipeline rejects any render
#: without exactly one detected face, so a second person in frame is a wasted
#: render, and asking for one person up front is cheaper than rejecting it after.
DEFAULT_NEGATIVE = (
    "multiple people, crowd, second face, text, watermark, signature, "
    "deformed hands, extra fingers, extra limbs, blurry, low resolution"
)

#: The bundled SDXL workflow's sampler, unchanged. juggernautXL states no
#: recipe of its own in its metadata (the registry reads `sampler_recipe: null`),
#: so these are the settings it was being driven at through casting - keeping
#: them means Phase 3 renders are comparable with the Phase 2 population.
DEFAULT_SAMPLER = {
    "steps": 35,
    "cfg": 4.5,
    "sampler_name": "dpmpp_2m_sde",
    "scheduler": "karras",
}


def build_faceid_graph(
    *,
    prompt: str,
    reference_image: Path | str | None = None,
    reference_dir: Path | str | None = None,
    seed: int,
    checkpoint: str = "juggernautXL_ragnarok.safetensors",
    negative_prompt: str = DEFAULT_NEGATIVE,
    width: int = 832,
    height: int = 1216,
    steps: int | None = None,
    cfg: float | None = None,
    sampler_name: str | None = None,
    scheduler: str | None = None,
    lora_strength: float = 0.6,
    weight: float = 1.0,
    weight_faceidv2: float = 1.6,
    weight_type: str = "linear",
    combine_embeds: str = "concat",
    start_at: float = 0.0,
    end_at: float = 1.0,
    embeds_scaling: str = "V only",
    provider: str = "CPU",
    filename_prefix: str = "image/CharacterDataset",
) -> dict[str, Any]:
    """The API-format graph. Node ids mirror the bundled workflow where they can.

    `weight_faceidv2` defaults above 1.0 deliberately: PlusV2's shortcut path is
    what carries the identity, and at the node default of 1.0 the face reads as
    a suggestion. It is the first dial to move if the accept rate is poor, and
    the last one to blame if the renders stop looking like the prompt.

    Pass `reference_dir` instead of `reference_image` to condition on a whole
    folder. One reference gives the adapter one view of a face, including
    whatever that render got wrong; several views of the same person let
    `combine_embeds` average toward what they share, which is the identity.
    Phase 2's promoted cluster is exactly such a folder, and it is the reason
    the cluster is worth finding rather than just the single best image.
    """
    if (reference_image is None) == (reference_dir is None):
        raise ValueError("pass exactly one of reference_image or reference_dir")
    sampler = {
        "steps": steps if steps is not None else DEFAULT_SAMPLER["steps"],
        "cfg": cfg if cfg is not None else DEFAULT_SAMPLER["cfg"],
        "sampler_name": sampler_name or DEFAULT_SAMPLER["sampler_name"],
        "scheduler": scheduler or DEFAULT_SAMPLER["scheduler"],
    }

    return {
        "1": {
            "class_type": "CheckpointLoaderSimple",
            "inputs": {"ckpt_name": checkpoint},
        },
        "2": {
            "class_type": "CLIPTextEncode",
            "inputs": {"text": prompt, "clip": ["1", 1]},
        },
        "3": {
            "class_type": "CLIPTextEncode",
            "inputs": {"text": negative_prompt, "clip": ["1", 1]},
        },
        "4": {
            "class_type": "EmptyLatentImage",
            "inputs": {"width": width, "height": height, "batch_size": 1},
        },
        "5": {
            "class_type": "KSampler",
            "inputs": {
                "seed": int(seed),
                "steps": sampler["steps"],
                "cfg": sampler["cfg"],
                "sampler_name": sampler["sampler_name"],
                "scheduler": sampler["scheduler"],
                "denoise": 1,
                # The model comes from the FaceID node, not the checkpoint - that
                # is the whole point of the graph, and wiring it to ["1", 0] by
                # habit yields a normal txt2img render with no error to notice.
                "model": ["8", 0],
                "positive": ["2", 0],
                "negative": ["3", 0],
                "latent_image": ["4", 0],
            },
        },
        "6": {
            "class_type": "VAEDecode",
            "inputs": {"samples": ["5", 0], "vae": ["1", 2]},
        },
        "7": {
            "class_type": "SaveImage",
            "inputs": {"filename_prefix": filename_prefix, "images": ["6", 0]},
        },
        "8": {
            "class_type": "IPAdapterFaceID",
            "inputs": {
                "model": ["9", 0],
                "ipadapter": ["9", 1],
                "image": ["10", 0],
                "weight": weight,
                "weight_faceidv2": weight_faceidv2,
                "weight_type": weight_type,
                "combine_embeds": combine_embeds,
                "start_at": start_at,
                "end_at": end_at,
                "embeds_scaling": embeds_scaling,
            },
        },
        "9": {
            "class_type": "IPAdapterUnifiedLoaderFaceID",
            "inputs": {
                "model": ["1", 0],
                "preset": FACEID_PRESET,
                "lora_strength": lora_strength,
                "provider": provider,
            },
        },
        "10": (
            {
                "class_type": "VHS_LoadImagePath",
                "inputs": {
                    "image": str(Path(reference_image).resolve()),
                    "custom_width": 0,
                    "custom_height": 0,
                },
            }
            if reference_image is not None
            else {
                "class_type": "VHS_LoadImagesPath",
                "inputs": {"directory": str(Path(reference_dir).resolve())},
            }
        ),
    }
