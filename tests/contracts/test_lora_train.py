"""Contracts for the native-trainer graphs.

A training graph that is wired wrong fails an hour in, with an error that
names a tensor shape and not a node. These pin the wiring so that failure
cannot come from here.
"""

from __future__ import annotations

from tools._comfyui.lora_train import (
    DEFAULT_LEARNING_RATE,
    DEFAULT_RANK,
    build_sdxl_lora_render_graph,
    build_sdxl_lora_train_graph,
)


def _train(**overrides):
    base = dict(checkpoint="ckpt.safetensors", dataset_folder="ds", prefix="loras/x", steps=10)
    base.update(overrides)
    return build_sdxl_lora_train_graph(**base)


class TestTrainGraph:
    def test_dataset_feeds_trainer_and_trainer_feeds_saver(self):
        g = _train()
        assert g["3"]["inputs"]["images"] == ["2", 0]
        assert g["3"]["inputs"]["texts"] == ["2", 1]
        assert g["3"]["inputs"]["vae"] == ["1", 2]
        assert g["3"]["inputs"]["clip"] == ["1", 1]
        assert g["4"]["inputs"]["model"] == ["1", 0]
        assert g["4"]["inputs"]["latents"] == ["3", 0]
        assert g["4"]["inputs"]["positive"] == ["3", 1]
        assert g["5"]["inputs"]["lora"] == ["4", 0]
        assert g["5"]["inputs"]["steps"] == ["4", 2]

    def test_uses_the_native_saver_not_the_diff_extractor(self):
        # LoraSave wants a MODEL diff; the trainer emits LORA_MODEL, which only
        # SaveLoRA and LoraModelLoader accept.
        assert _train()["5"]["class_type"] == "SaveLoRA"

    def test_rank_is_low_because_it_sets_the_scale(self):
        # nodes_train.py hardcodes alpha=1.0 and lora.py applies
        # scale = alpha / rank, so rank IS the strength dial. Standard practice
        # (alpha = rank/2) is scale 0.5; rank 32 here would be 0.031, a 16x
        # weaker LoRA. The first run did that and barely learned the face while
        # degrading the image.
        assert DEFAULT_RANK <= 8, "rank above 8 means scale below 0.125"
        scale = 1.0 / DEFAULT_RANK
        assert 0.125 <= scale <= 1.0
        assert _train()["4"]["inputs"]["rank"] == DEFAULT_RANK

    def test_learning_rate_pairs_with_that_scale(self):
        # 2e-4 is 2x kohya's 1e-4, closing the remaining 2x gap between rank 4's
        # scale (0.25) and the standard 0.5. A rate chosen for a different rank
        # is a rate for a different LoRA strength.
        assert DEFAULT_LEARNING_RATE == 2e-4
        assert _train()["4"]["inputs"]["learning_rate"] == DEFAULT_LEARNING_RATE

    def test_every_required_trainer_input_is_present(self):
        required = {
            "model", "latents", "positive", "batch_size", "grad_accumulation_steps",
            "steps", "learning_rate", "rank", "optimizer", "loss_function", "seed",
            "training_dtype", "lora_dtype", "quantized_backward", "algorithm",
            "gradient_checkpointing", "checkpoint_depth", "offloading",
            "existing_lora", "bucket_mode", "bypass_mode",
        }
        assert required <= set(_train()["4"]["inputs"])

    def test_optimizer_is_one_the_node_offers(self):
        assert _train()["4"]["inputs"]["optimizer"] in {"AdamW", "Adam", "SGD", "RMSprop"}


class TestRenderGraph:
    def test_without_lora_is_the_bundled_sdxl_shape(self):
        g = build_sdxl_lora_render_graph(checkpoint="c", prompt="p", seed=1, lora_name=None)
        assert "8" not in g
        assert g["5"]["inputs"]["model"] == ["1", 0]
        assert g["2"]["inputs"]["clip"] == ["1", 1]

    def test_with_lora_routes_model_and_clip_through_the_loader(self):
        g = build_sdxl_lora_render_graph(
            checkpoint="c", prompt="p", seed=1, lora_name="character/x.safetensors",
            strength_model=0.8, strength_clip=0.8,
        )
        assert g["8"]["class_type"] == "LoraLoader"
        assert g["8"]["inputs"]["lora_name"] == "character/x.safetensors"
        assert g["5"]["inputs"]["model"] == ["8", 0]
        assert g["2"]["inputs"]["clip"] == ["8", 1]
        assert g["3"]["inputs"]["clip"] == ["8", 1]

    def test_the_pair_differs_only_by_the_lora(self):
        # The gate compares two renders; anything else that differs would be a
        # confound. Same seed, sampler, size, prompt - only the wiring changes.
        a = build_sdxl_lora_render_graph(checkpoint="c", prompt="p", seed=9, lora_name=None)
        b = build_sdxl_lora_render_graph(checkpoint="c", prompt="p", seed=9, lora_name="l")
        for node in ("1", "4", "6", "7"):
            assert a[node] == b[node]
        for key in ("seed", "steps", "cfg", "sampler_name", "scheduler", "denoise"):
            assert a["5"]["inputs"][key] == b["5"]["inputs"][key]
