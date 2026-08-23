---
name: comfyui
description: Use when working with ComfyUI workflows in OpenMontage, including comfyui_image/comfyui_video/comfyui_music/comfyui_tts, custom workflow inputs, output_node selection, missing model setup, LoRAs, low-VRAM workflow choices, and community workflow imports.
---

# ComfyUI Workflows in OpenMontage

Use this skill before calling `comfyui_image`, `comfyui_video`, or `comfyui_music`, and when converting a community ComfyUI workflow into an OpenMontage tool call.

## Server Contract

- ComfyUI must be running before the tool can generate. The default server is `http://localhost:8188`; override it with `COMFYUI_SERVER_URL`.
- Running separate ComfyUI instances per capability (different GPU, different model set)? `COMFYUI_IMAGE_SERVER_URL` / `COMFYUI_VIDEO_SERVER_URL` / `COMFYUI_MUSIC_SERVER_URL` / `COMFYUI_TTS_SERVER_URL` each override `COMFYUI_SERVER_URL` for that one tool only. Optional -- a single-server setup needs none of these.
- Health and hardware status come from `GET /system_stats`.
- Jobs are submitted to `POST /prompt`, completed outputs are read from `GET /history/{prompt_id}`, and artifact bytes are downloaded with `GET /view`.
- Long waits (video, music) prefer ComfyUI's websocket feed for immediate completion/error detection and transparently fall back to REST polling if `websocket-client` isn't installed. Either way, a timeout is recoverable: pass the error's `prompt_id` back in as `resume_prompt_id` to resume waiting on the same job instead of resubmitting it.
- Export workflows with ComfyUI's API-format JSON, not the UI layout format. If a downloaded workflow will not submit, re-export it from ComfyUI with API format enabled.

### Partner Nodes are hosted

- `gemini_omni_flash`, `seedance_2.5`, and `minimax_h3_api` in
  `comfyui_video` are official ComfyUI Partner Nodes. They call hosted APIs and
  require network access, a logged-in Comfy account, and prepaid credits.
- Do not describe Partner Nodes as local, offline, or free merely because the
  graph runs in a local ComfyUI process.
- `minimax_h3_local` is a separate open-weight path. It requires the official
  MiniMax H3 workflow exported in API format, its `output_node`, and the model
  stack reported by the tool.

## Choosing a Workflow

- Use bundled workflows when the requested operation matches and the local machine has the required models and VRAM.
- Use a custom `workflow_json` or `workflow_path` when the user needs a community recipe, a lower-VRAM model, a different style family, or custom nodes.
- For 8GB-12GB GPUs, prefer lower-footprint workflows such as Wan 2.1 1.3B, LTXV FP8 or quantized workflows, or Wan 2.2 GGUF/quantized community workflows. The bundled Wan 2.2 14B FP8 video workflows are a 16GB-class path, not a provider-wide floor.
- Do not promise that arbitrary custom workflows will fit a machine. The workflow, quantization, resolution, frame count, and offload settings determine the real resource envelope.
- `comfyui_image` includes `workflow_variant="juggernaut_xl_ragnarok"` as a bundled SDXL alternative to FLUX 2. Its tracked graph uses the installed `juggernautXL_ragnarok.safetensors` checkpoint, baked VAE, DPM++ 2M SDE/Karras, and profile-bound prompt, negative prompt, dimensions, seed, steps, CFG, and filename. `workflow_variant="auto"` prefers FLUX 2 when its full stack is installed and otherwise selects Juggernaut when available.

## Graph Sources

A ComfyUI graph can reach the tool three ways. They are mutually exclusive.

1. **Bundled** — no workflow input. `comfyui_image` picks a `workflow_variant`; `comfyui_video` uses the WAN 2.2 graphs. Models are checked up front and reported through `data.missing_models`.
2. **Custom** — `workflow_json` / `workflow_path`, optionally with a workflow profile. You own the node IDs; a re-export from ComfyUI can invalidate the profile.
3. **VRGDG builder** — `vrgdg_build`. The VRGDG node pack patches its own API template and returns a ready-to-queue graph. Node lookup is by `class_type` with a numeric fallback, so template edits do not break the caller and there is no binding profile to maintain.

### `vrgdg_build`

```json
{"vrgdg_build": {"kind": "zimage", "payload": {"prompt": "...", "unet_name": "...", "clip_name": "...", "vae_name": "..."}}}
```

- Requires the `comfyui-vrgamedevgirl` pack on the ComfyUI server. `VRGDGClient.is_available()` probes `GET /vrgdg/workflow_runner/model_root`; the failure message distinguishes "ComfyUI is down" from "the pack is not loaded".
- **Model filenames come from the payload, not the template.** The shipped templates carry the pack author's filenames; always pass `unet_name` / `clip_name` / `vae_name` for the files that actually exist on this server. `GET /vrgdg/music_builder/model_defaults` returns the user's saved choices — use it as the base payload.
- `output_node` is resolved from the returned graph by saver class (`VRGDG_CreateFinalVideo`, `VHS_VideoCombine`, `SaveVideo`, `SaveAudioMP3`, `SaveImage`), skipping preview and comparison nodes. Pass `output_node` explicitly to override.
- **Image kinds are standalone**: `zimage`, `krea2`, `krea2_2pass`, `ernie_image`, `flux_klein`, `nb_image`, `z_upscale_enhance`. Parameters are enough.
- **Video kinds are project-bound**: `i2v`, `t2v`, `flf`, `rtv`, `ingredients`, `id_lora`, `minimax_h3`. They read a VRGDG project folder and need `project_folder`, `audio_path`, `srt_path`, and for `i2v` an `image_folder`. They save through VRGDG's own writer into the project, so when `/view` exposes nothing the tool copies the newest clip out of the returned `output_folder`. Scaffold a project with `VRGDGClient.new_project()` + `create_silent_audio()` + `save_project_srt()` before calling one.
- Provenance records the route, the template path VRGDG used, the seed it chose, and a hash of the **submitted graph** — a stronger reproducibility contract than a profile name, because it pins what actually ran.
- Routes that open a native OS dialog or launch a browser (`pick_path`, `browser_image/*`, `lora_dataset/pick_folder`) are refused by the client rather than left to hang an unattended run.
- `tool.get_info()["vrgdg_build_kinds"]` lists the kinds this tool supports, with the project-bound flag and required keys.

## Output Node Contract

- Custom workflows must pass `output_node`.
- A validated workflow profile may declare `output_node` instead; an explicit
  tool input still overrides the profile value.
- Pick the node that writes the artifact, usually `SaveImage`, `SaveVideo`, `VHS_VideoCombine`, or another terminal saver node.
- Pass the node ID as a string, for example `"108"`. Do not pass the class name.
- If a workflow has multiple savers, choose the final deliverable node, not previews or intermediates.

## Templated vs Fixed Nodes

- Identify templated nodes before execution: prompt text, seed, dimensions, frame count, source image, sampler settings, and output filename prefix.
- Fixed nodes are model loaders, VAEs, text encoders, LoRA loaders, schedulers, and graph wiring. Do not mutate those unless the workflow author intended that customization.
- For `comfyui_video`, a workflow profile can bind `reference_image`,
  `first_frame`, `last_frame`, or `driving_video`. The tool uploads the matching
  `*_path` or `*_url` input to ComfyUI and patches the returned server filename
  into that declared binding before submission.
- A declared `filename_prefix` binding defaults to `video/<output stem>` and
  may be overridden by the caller.
- For community workflows, inspect each loader node and note every required model or custom node before running. Missing models should be handled through the tool's structured `missing_models` payload when available.

## Model and LoRA Setup

- Use ComfyUI Manager or the workflow author's model links when available, and respect model licenses.
- Place models in the folders expected by the loader nodes: diffusion models under `ComfyUI/models/diffusion_models/`, text encoders under `ComfyUI/models/text_encoders/`, VAEs under `ComfyUI/models/vae/`, and LoRAs under `ComfyUI/models/loras/`.
- For LoRA stacks, use `LoraLoader` or `LoraLoaderModelOnly` chains in the workflow. Record each LoRA name plus `strength_model` and `strength_clip` when applicable.
- The current ComfyUI tools do not inject LoRAs into arbitrary graphs. To use LoRAs, provide a workflow that already contains the LoRA loader chain and pass model-stack provenance.

## Provenance

- For custom workflows, provide `workflow_name` and `workflow_model` when known.
- Provide `workflow_model_stack` for reproducibility when the workflow is not bundled. Include base checkpoint or diffusion model, quantization, text encoder, VAE, LoRAs and strengths, sampler or scheduler, steps, and guidance if the workflow exposes them.
- The tools record the final workflow hash. Treat that hash plus the model stack, seed, dimensions, and prompt as the reproducibility contract.
- Profile-bound video provenance also records the profile name/version/hash,
  declared and applied bindings, and common loader assets inferred from the
  final graph when `workflow_model_stack` is not supplied.

## Failure Handling

- If the server is unavailable, surface the structured setup offer. Starting ComfyUI or setting `COMFYUI_SERVER_URL` is the first fix.
- If models are missing, read `data.missing_models[]`; each item should include the file name, role, destination hint, and download URL when OpenMontage knows it.
- If custom nodes are missing, ask the user to install them through ComfyUI Manager or the workflow author's documented install path, then restart ComfyUI.
- If a long render times out locally, check ComfyUI history before retrying from scratch; the server may still have completed the prompt -- or just call again with `resume_prompt_id` set to the `prompt_id` from the timeout error.

## Music (`comfyui_music`)

- Bundled default is the user's validated ACE-Step 1.5 Turbo AIO graph, built from ComfyUI's native `TextEncodeAceStepAudio1.5`/`EmptyAceStep1.5LatentAudio` nodes. It requires `ace_step_1.5_turbo_aio.safetensors` under `ComfyUI/models/checkpoints/`.
- `prompt` maps to the bundled workflow's `tags` field (style/genre/mood, e.g. `"upbeat electronic pop, female vocals"`), matching the same "prompt = music description" convention `suno_music` uses. `lyrics` is a separate optional field -- leave empty for instrumental, or use `[verse]`/`[chorus]`/`[bridge]` structure tags and `[zh]`/`[ja]`/`[ko]`-style language-code prefixes for non-English lines.
- The bundled workflow profile binds `prompt`, `lyrics`, duration (to both conditioning and latent nodes), seed (to both LM and sampler), `steps`, sampler `cfg`, audio-code `cfg_scale`, BPM, time signature, language, key, audio-code generation, temperature, top-p/top-k/min-p, and output prefix. Missing `ace_step_1.5_turbo_aio.safetensors` surfaces through the same `data.missing_models[]` contract as image/video.
- Need ACE-Step v1, XL, a different node pack, or a non-ACE-Step audio model? Fall back to `workflow_json`/`workflow_path` + `output_node`, exactly like a custom image/video workflow -- in that mode `prompt` becomes provenance/logging only again and must already be baked into the graph.
- `output_node` (bundled or custom) should be the node that writes the final audio -- the bundled workflow's is `SaveAudioMP3`. The client reads artifacts from that node's `"audio"` output key (parallel to `"images"` for image/video savers).
- For custom workflows, provide `workflow_name`/`workflow_model`/`workflow_model_stack` for provenance exactly as you would for a custom image/video workflow.

## Qwen3-TTS (`comfyui_tts`)

- The integrated user workflow is split into three independently executable graphs: `voice_design`, `custom_voice`, and `voice_clone`. This prevents ComfyUI from evaluating all three saver branches for every narration request.
- `voice_design` accepts `character`, `style_name`, and concrete delivery `instructions`; `custom_voice` additionally accepts a bundled `speaker` name; `voice_clone` requires `reference_audio_path` and optionally accepts an exact `reference_text` transcript.
- Reference audio is uploaded to ComfyUI's input directory and bound to the graph's `LoadAudio` node. Use clean, single-speaker audio without music or room echo; provide `reference_text` when known for better cloning consistency.
- All modes bind `text`, `language`, `model_size`, `seed`, `unload_models`, and the MP3 filename prefix through validated workflow profiles in `tools/_comfyui/profiles/`.
- The required custom node classes are `AILab_Qwen3TTSVoiceDesign`, `AILab_Qwen3TTSCustomVoice`, `AILab_Qwen3TTSVoiceClone`, and `AILab_Qwen3TTSVoiceInstruct`. The current graph uses `SaveAudioMP3`; ComfyUI labels it deprecated but still exposes it on the validated local installation.
