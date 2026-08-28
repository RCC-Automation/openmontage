---
title: Video generation engines
status: researched
updated: 2026-08-28
sources: [https://github.com/vrgamegirl19/comfyui-vrgamedevgirl, https://docs.comfy.org/tutorials/video/ltx/ltx-2-3, https://huggingface.co/Comfy-Org/MiniMax-H3/tree/main, https://docs.comfy.org/tutorials/video/wan/wan2_2, https://docs.comfy.org/tutorials/video/wan/wan2-2-s2v, https://docs.comfy.org/tutorials/video/hunyuan/hunyuan-video-1-5]
---

VRGDG is the project and scene cockpit, while a video engine is the model-backed ComfyUI graph that renders a scene. The installed Builder directly understands LTX 2.3 and MiniMax H3; other engines can still consume VRGDG scene data through an OpenMontage workflow adapter, but they do not automatically become Builder-native engines.

## What we know

### Engines exposed by VRGDG

The installed Builder exposes two engine families:

| Engine | Builder modes | Best fit |
|---|---|---|
| LTX 2.3 | text-to-video, image-to-video, first/last-frame, reference-to-video, ingredients, ID-LoRA | fast iteration, synchronized audio, continuity and the deepest Builder integration |
| MiniMax H3 | text-to-video, image-to-video, reference-to-video, video-to-video | reference-driven generation, audio-driven performance and joint audio/video generation |

An LTX mode is not a different engine. Switching from I2V to FLF or ID-LoRA changes the conditioning route while retaining the LTX model family.

Official ComfyUI support for LTX 2.3 covers T2V, I2V, first/last-frame interpolation, image-and-audio-to-video, IC-LoRA structural control and ID-LoRA personalization. See the [official LTX 2.3 workflow guide](https://docs.comfy.org/tutorials/video/ltx/ltx-2-3).

MiniMax H3 has native ComfyUI weights for diffusion, text encoding, video/audio VAE and Turbo LoRAs. Its complete upstream repository is very large, so a configured Builder UI does not prove that the selected H3 weight set is installed locally. See the [Comfy-Org MiniMax H3 repository](https://huggingface.co/Comfy-Org/MiniMax-H3/tree/main).

### Custom-workflow substitutes

#### Wan 2.2 — first choice for an alternate adapter

Wan 2.2 provides T2V, I2V and first/last-frame workflows. The 5B hybrid model supports both T2V and I2V and is documented by ComfyUI as fitting around 8 GB VRAM with native offloading; the 14B I2V and T2V variants trade more resources for quality. See the [official Wan 2.2 workflows](https://docs.comfy.org/tutorials/video/wan/wan2_2).

Wan 2.2 S2V is a separate audio-driven route that turns an image plus audio into synchronized performance video, including dialogue and singing. It is particularly relevant to music-video scenes. See the [official Wan S2V workflow](https://docs.comfy.org/tutorials/video/wan/wan2-2-s2v).

Wan is the practical first substitute for OpenMontage because the repository already contains Wan 2.2 workflows and routing support. That is implementation readiness, not a claim that the required models have been rendered successfully on this AMD host.

#### HunyuanVideo 1.5 — quality-oriented experiment

HunyuanVideo 1.5 is an 8.3B T2V/I2V model with native 720p workflows and nominal 5–10 second clips. Official guidance targets a 24 GB consumer GPU. It is promising for camera motion, physical movement and detailed cinematic prompts, but it is not Builder-native and still requires an AMD/ROCm compatibility and memory test here. See the [official HunyuanVideo 1.5 guide](https://docs.comfy.org/tutorials/video/hunyuan/hunyuan-video-1-5).

#### Hosted engines

An OpenMontage adapter could submit scenes to hosted providers such as Kling or Runway and retrieve the clips. This avoids local VRAM limits but introduces per-render cost, credentials, upload/privacy constraints and provider-specific duration rules. It remains an OpenMontage provider unless VRGDG itself gains a matching engine route.

### The adapter boundary

A general custom workflow can preserve VRGDG's project, storyboard, prompt, timing, references, timeline and assembly while replacing the generation graph:

```text
VRGDG project and selected scene
  -> prompt, source media, timing and seed
  -> engine-specific ComfyUI workflow
  -> generated scene clip
  -> project output and final assembly
```

An arbitrary workflow JSON is not self-describing. Each engine adapter must identify the nodes and inputs for:

- positive and negative prompts;
- source image, final image, reference video and/or audio;
- width, height, frame count and FPS;
- seed, sampler and model selection;
- output filename and destination;
- engine-specific frame-count or resolution constraints.

The reusable design is therefore a common scene selector and output layer plus one binding profile per engine. The present tiled scene generator is LTX-specific rather than fully engine-neutral.

## What it costs

- LTX is already the lowest-friction path because its weights and Builder routes are the path currently exercised on this machine.
- MiniMax H3 requires a large optional model group; UI availability alone is not model readiness.
- Wan 2.2 5B is the lowest-memory researched alternative. Wan 14B and Hunyuan 1.5 require substantially more model storage and memory/offloading.
- Engines without joint audio/video generation need the project audio retained and muxed during OpenMontage/VRGDG assembly.
- Every new engine needs a binding profile plus one-scene validation before batch use.

## Recommended order

1. Keep LTX 2.3 as the default Builder-native engine.
2. Add Wan 2.2 I2V as the first general-purpose OpenMontage adapter.
3. Add Wan S2V as a specialized singing and performance route.
4. Enable MiniMax H3 after its selected weights are installed and a one-scene AMD test passes.
5. Treat HunyuanVideo 1.5 as an experimental quality route until measured locally.

The generator interface should eventually offer `ltx`, `wan22_i2v`, `wan22_flf`, `wan22_s2v` and `custom-profile`, while keeping project discovery, scene selection, SRT timing and output naming common.

## Traps

- “Supported by ComfyUI” does not mean “selectable in VRGDG.” Builder-native support requires VRGDG UI and route integration.
- A model option visible in the interface does not prove that all corresponding weight files are installed.
- Audio capability differs by engine. Replacing LTX with a silent workflow without preserving the project audio changes the production result.
- Frame rules, resolutions and node IDs are engine-specific; blindly patching an LTX workflow into another model family will produce invalid or misleading graphs.
- Hardware claims in upstream NVIDIA-oriented documentation are not measurements for this AMD/ROCm machine.

## Open questions

- Which Wan 2.2 model files are presently installed and loadable in the shared ComfyUI model tree?
- Does MiniMax H3 complete a representative scene on this AMD/ROCm host without native-process failure?
- What binding-profile schema is sufficient for both local ComfyUI graphs and hosted providers without embedding engine logic in the common generator?
