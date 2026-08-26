"""Graphs for training an SDXL character LoRA with ComfyUI's native nodes.

Two graphs, because a LoRA is only evidence once it has been loaded back:

    build_sdxl_lora_train_graph   folder of image+caption pairs -> .safetensors
    build_sdxl_lora_render_graph  the same checkpoint with that LoRA applied

Why the native nodes and not Kohya or AI Toolkit: neither is installed, both
assume CUDA, and this is an AMD gfx1151 box with no Triton or xformers. The
native `TrainLoraNode` is the only trainer here with a verified optimizer path
(HANDOFF section 2). Whether it *completes* on ROCm is QUESTIONS.md Q7, and the
smoke script that uses these graphs is how that gets answered.

Two things about the native node that differ from every online recipe:

**The learning rate is 5e-4, not 1e-4.** Kohya's 1e-4 assumes alpha = rank
(typically 32). The native node pins alpha at 1.0, which scales the effective
update by 1/rank, so the same 1e-4 would train at a fraction of the intended
rate. 5e-4 is the node's own default and the runbook's recommendation.

**The optimizer choice is `AdamW`, plain.** The node offers AdamW / Adam / SGD /
RMSprop and nothing 8-bit; `bitsandbytes` working here matters for VRGDG's
bundled kohya trainer, not this path. With ~90 GB of unified memory the 8-bit
state saving is not needed anyway.

Dataset layout: a subfolder of ComfyUI's **input** directory holding
`NNN.png` + `NNN.txt` pairs. `LoadImageTextDataSetFromFolder` lists input
subfolders in a dropdown, so a folder staged while ComfyUI is running has to
show up in `object_info` before the graph will validate - the caller checks.
"""

from __future__ import annotations

from typing import Any

__all__ = [
    "DEFAULT_LEARNING_RATE",
    "build_sdxl_lora_render_graph",
    "build_sdxl_lora_train_graph",
]

#: **Rank is not capacity here, it is strength.** `nodes_train.py` hardcodes
#: `alpha=1.0` when it creates the adapter, and `comfy/weight_adapter/lora.py`
#: applies `scale = alpha / rank`. So rank sets the scale directly:
#:
#:     rank  1 -> scale 1.000   (the "alpha = rank" convention)
#:     rank  2 -> scale 0.500   (the "alpha = rank/2" convention, most common)
#:     rank  4 -> scale 0.250
#:     rank 32 -> scale 0.031   <- 16x weaker than standard practice
#:
#: Every guide written for kohya assumes alpha is a separate dial set to rank or
#: rank/2, so "rank 32, alpha 16, lr 1e-4" transplanted here trains at a
#: sixteenth of the intended strength. Our first 1500-step run did exactly that:
#: identity barely moved (0.087 -> 0.210) while the images degraded, because the
#: optimiser has to drive the raw B*A weights enormous to have any effect
#: through a 0.031 scale.
#:
#: So: keep rank LOW. rank 4 is a quarter of standard scale with real capacity;
#: the remaining gap is closed with the learning rate below.
DEFAULT_RANK = 4

#: 2e-4, which is 2x the 1e-4 that kohya guides pair with alpha=rank/2 - closing
#: the last 2x of the scale gap at rank 4. The earlier 5e-4 was chosen to
#: compensate alpha=1.0 without knowing the size of the gap; at rank 32 it
#: undercompensated by roughly 3x, and at rank 4 it would overshoot.
DEFAULT_LEARNING_RATE = 2e-4


def build_sdxl_lora_train_graph(
    *,
    checkpoint: str,
    dataset_folder: str,
    prefix: str,
    steps: int,
    learning_rate: float = DEFAULT_LEARNING_RATE,
    rank: int = DEFAULT_RANK,
    batch_size: int = 1,
    grad_accumulation_steps: int = 1,
    optimizer: str = "AdamW",
    loss_function: str = "MSE",
    seed: int = 0,
    training_dtype: str = "bf16",
    lora_dtype: str = "bf16",
    algorithm: str = "LoRA",
    gradient_checkpointing: bool = True,
    checkpoint_depth: int = 1,
    offloading: bool = False,
    quantized_backward: bool = False,
    existing_lora: str = "[None]",
    bucket_mode: bool = False,
    bypass_mode: bool = False,
) -> dict[str, Any]:
    """API-format graph: checkpoint + dataset folder -> trained LoRA on disk.

    `prefix` is relative to ComfyUI's output directory, e.g.
    `loras/character/wrenx_smoke`; `SaveLoRA` appends the step count.
    """
    return {
        "1": {
            "class_type": "CheckpointLoaderSimple",
            "inputs": {"ckpt_name": checkpoint},
        },
        "2": {
            "class_type": "LoadImageTextDataSetFromFolder",
            "inputs": {"folder": dataset_folder},
        },
        "3": {
            "class_type": "MakeTrainingDataset",
            "inputs": {
                "images": ["2", 0],
                "vae": ["1", 2],
                "clip": ["1", 1],
                "texts": ["2", 1],
            },
        },
        "4": {
            "class_type": "TrainLoraNode",
            "inputs": {
                "model": ["1", 0],
                "latents": ["3", 0],
                "positive": ["3", 1],
                "batch_size": int(batch_size),
                "grad_accumulation_steps": int(grad_accumulation_steps),
                "steps": int(steps),
                "learning_rate": float(learning_rate),
                "rank": int(rank),
                "optimizer": optimizer,
                "loss_function": loss_function,
                "seed": int(seed),
                "training_dtype": training_dtype,
                "lora_dtype": lora_dtype,
                "quantized_backward": bool(quantized_backward),
                "algorithm": algorithm,
                "gradient_checkpointing": bool(gradient_checkpointing),
                "checkpoint_depth": int(checkpoint_depth),
                "offloading": bool(offloading),
                "existing_lora": existing_lora,
                "bucket_mode": bool(bucket_mode),
                "bypass_mode": bool(bypass_mode),
            },
        },
        "5": {
            "class_type": "SaveLoRA",
            "inputs": {"lora": ["4", 0], "prefix": prefix, "steps": ["4", 2]},
        },
    }


def build_sdxl_lora_render_graph(
    *,
    checkpoint: str,
    prompt: str,
    seed: int,
    lora_name: str | None,
    strength_model: float = 0.8,
    strength_clip: float = 0.8,
    negative_prompt: str = "",
    width: int = 832,
    height: int = 1216,
    steps: int = 35,
    cfg: float = 4.5,
    sampler_name: str = "dpmpp_2m_sde",
    scheduler: str = "karras",
    filename_prefix: str = "image/LoraTest",
) -> dict[str, Any]:
    """The bundled SDXL graph with a `LoraLoader` between checkpoint and sampler.

    `lora_name=None` yields the identical graph without the loader - the
    control render. Same seed, same everything, so the only thing that differs
    between the two images is the LoRA, which is the comparison the gate needs.
    """
    model_src, clip_src = (["1", 0], ["1", 1])
    graph: dict[str, Any] = {
        "1": {
            "class_type": "CheckpointLoaderSimple",
            "inputs": {"ckpt_name": checkpoint},
        },
    }
    if lora_name:
        graph["8"] = {
            "class_type": "LoraLoader",
            "inputs": {
                "model": ["1", 0],
                "clip": ["1", 1],
                "lora_name": lora_name,
                "strength_model": float(strength_model),
                "strength_clip": float(strength_clip),
            },
        }
        model_src, clip_src = (["8", 0], ["8", 1])
    graph.update(
        {
            "2": {"class_type": "CLIPTextEncode", "inputs": {"text": prompt, "clip": clip_src}},
            "3": {"class_type": "CLIPTextEncode", "inputs": {"text": negative_prompt, "clip": clip_src}},
            "4": {
                "class_type": "EmptyLatentImage",
                "inputs": {"width": width, "height": height, "batch_size": 1},
            },
            "5": {
                "class_type": "KSampler",
                "inputs": {
                    "seed": int(seed),
                    "steps": int(steps),
                    "cfg": float(cfg),
                    "sampler_name": sampler_name,
                    "scheduler": scheduler,
                    "denoise": 1,
                    "model": model_src,
                    "positive": ["2", 0],
                    "negative": ["3", 0],
                    "latent_image": ["4", 0],
                },
            },
            "6": {"class_type": "VAEDecode", "inputs": {"samples": ["5", 0], "vae": ["1", 2]}},
            "7": {"class_type": "SaveImage", "inputs": {"filename_prefix": filename_prefix, "images": ["6", 0]}},
        }
    )
    return graph
