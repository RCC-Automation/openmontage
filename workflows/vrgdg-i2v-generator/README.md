# VRGDG I2V workflow generator

Creates standalone ComfyUI API workflows from a VRGDG AI Video Builder
project. It can export one scene, several selected scenes, or every scene.

The generator is designed for OpenMontage projects that hand scene plans,
prompts, images, timing, audio, and model choices to VRGDG. It reads VRGDG's
saved `vrgdg_builder_session.json`; it does not invent or reconstruct the
creative state.

## Why this exists

VRGDG's Builder hides the submitted ComfyUI graph behind its custom interface.
That makes machine-specific fixes difficult to apply. On the AMD/ROCm Windows
host used for this integration, the LTX video VAE can abort the ComfyUI process
when decoded as one large tile. The generated workflows replace `VAEDecode`
with `VAEDecodeTiled` using a conservative 256-pixel spatial tile.

The generator also preserves the complete VRGDG graph. A hand-copied partial
prompt is not enough: it is easy to lose the VAE, model, CLIP, source-image,
audio, trimming, and saver connections.

## Requirements

- Windows PowerShell 5.1 or PowerShell 7.
- ComfyUI Desktop with `comfyui-vrgamedevgirl` installed.
- A VRGDG Builder project containing `vrgdg_builder_session.json`.
- The project audio and scene images referenced by the session must still
  exist.
- The current workflow adapter targets VRGDG's GGUF LTX 2.3 I2V workflow.

ComfyUI does not need to be running to generate workflows.

## Interactive use

Run:

```powershell
& ".\workflows\vrgdg-i2v-generator\start_generator.ps1"
```

The launcher asks for the VRGDG project directory and whether to generate one,
several, or all scenes.

## Command-line use

One scene:

```powershell
& ".\workflows\vrgdg-i2v-generator\generate_vrgdg_i2v_workflows.ps1" `
  -ProjectRoot "C:\path\to\ComfyUI-Shared\output\MyProject" `
  -Scene 7
```

Several scenes:

```powershell
& ".\workflows\vrgdg-i2v-generator\generate_vrgdg_i2v_workflows.ps1" `
  -ProjectRoot "C:\path\to\ComfyUI-Shared\output\MyProject" `
  -Scenes 4,6,9
```

Every scene:

```powershell
& ".\workflows\vrgdg-i2v-generator\generate_vrgdg_i2v_workflows.ps1" `
  -ProjectRoot "C:\path\to\ComfyUI-Shared\output\MyProject" `
  -AllScenes
```

Disable the expensive LTX second/upscale pass as well:

```powershell
& ".\workflows\vrgdg-i2v-generator\generate_vrgdg_i2v_workflows.ps1" `
  -ProjectRoot "C:\path\to\ComfyUI-Shared\output\MyProject" `
  -AllScenes `
  -DisableUpscale
```

`-DisableUpscale` is recommended on the documented AMD host: the measured
second pass was roughly 24 times slower per step than the base pass and was the
site of hangs and crashes. It is independent of the tiled VAE fix.

## Output

By default files are written to:

```text
<VRGDG project>\workflows\generated_i2v_tiled\
```

The directory contains:

- `i2v_scene_NNNN_description_tiled.json` — runnable API workflow for each
  selected scene. The description comes from the scene label or story beat and
  is shortened to a filesystem-safe slug.
- `all_project_scenes.srt` — complete project timing used with the selected
  1-based scene number.
- `i2v_general_template_tiled.json` — the installed VRGDG base workflow with
  the decoder correction applied.

The original Builder session, source images, and existing rendered clips are
not modified.

After generation, the launcher prints a clearly labelled list under
`Generated scene workflow file(s)`. Open those scene files in ComfyUI. The
separately labelled supporting template is not the selected scene workflow.

## What is transferred

- Prompt and 1-based scene selection.
- Source image folder and image number.
- Project audio and full scene timing.
- Width, height, FPS, seed, pre-roll, and tail frames.
- GGUF UNet, CLIP, video/audio VAE, and spatial upscaler names.
- First- and second-pass samplers, sigma schedules, strengths, and bypasses.
- Global settings plus scene-level I2V overrides.
- Up to 20 configured LoRAs and both pass strengths.
- Complete trimming, audio, video-combine, and output connections from VRGDG's
  installed API workflow.
- Scene-aware workflow and rendered-video base names, such as
  `scene_0004_mara-enters-the-night-fire-district`.

## Verification

After generation:

```powershell
& ".\workflows\vrgdg-i2v-generator\verify_generated_workflows.ps1" `
  -WorkflowDirectory "C:\path\to\MyProject\workflows\generated_i2v_tiled"
```

Test one short scene before starting a batch. Close other GPU-heavy ComfyUI
instances during rendering.

## Safety and versioning

The tool reads the installed VRGDG `Singlei2vForUI_API.json` at runtime rather
than bundling a stale copy. It validates the node IDs it needs and stops if the
installed workflow is incompatible. See [COMPATIBILITY.md](COMPATIBILITY.md).
