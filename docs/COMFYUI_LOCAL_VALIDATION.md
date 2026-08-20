# Local ComfyUI integration validation

Validated on a local ComfyUI Desktop installation using the OpenMontage
`integration/comfyui-local` branch. All generation ran locally without paid
provider APIs.

## Integration status

- Custom API-format ComfyUI video workflows support reusable workflow profiles.
- Profile bindings cover prompts, seeds, dimensions, timing, filename prefixes,
  reference frames, reference images, and driving video inputs.
- Custom ComfyUI image workflows use the same profile mechanism for prompt,
  seed, dimensions, steps, guidance, optional negative prompt, filename prefix,
  and output-node selection.
- Workflow and profile JSON files are decoded explicitly as UTF-8 on Windows.
- Result format is derived from the returned artifact; GIF utility output is no
  longer reported as MP4 or given assumed video metadata.
- Applied profile bindings and workflow hashes are recorded in provenance.

## Workflow showcase

Artifacts are stored outside the repository in:

`C:\Users\Barrul\Documents\ChatGPT\Projects\ShortFilmProduction\comfyui-workflow-showcase`

| # | Local workflow | Result | Inputs / intent | Seed | Runtime |
|---|---|---|---|---:|---:|
| 1 | `my_flux_txt2image.json` | `01_flux_editorial.png` | FLUX editorial portrait test | workflow value | 115.41 s |
| 2 | `my_v2i.json` | `02_wan_clip.gif` | Video-to-GIF utility test | n/a | 18.20 s |
| 3 | `my_video_wan2_2_14B_i2v.json` | `03_wan22_i2v_dragon_awakes.mp4` | White dragon-knight reference; awakening motion | 24081901 | 212.86 s |
| 4 | `my_video_wan2_2_14B_flf2v.json` | `04_wan22_flf2v_runway_metamorphosis.mp4` | Avant-garde model first frame to inflated-puffer final frame | 24081902 | 178.91 s |
| 5 | `my_video_wan_animate2.json` | `05_wan_animate2_clockwork_dancer.mp4` | Pink-haired clockwork heroine driven by `street_dance_drive.mp4` | 24081903 | 239.08 s |
| 6 | `my_video_wan21_scail2_character_replacement.json` | `06_wan21_scail2_neon_clockwork_replacement.mp4` | Pink-haired heroine replacing the subject in the street-dance driving video | 24081904 | 3963.79 s |
| 7 | `my_flux_txt2image.json` with `flux-custom-example.json` | `07_flux_runtime_bound_observatory.png` | Runtime-bound celestial-observatory clockwork heroine | 24082026 | 97.68 s |

All six original workflows completed successfully. The seventh generation is a
focused end-to-end verification of the new image workflow-profile bindings.

## Runtime-bound FLUX verification

The seventh generation used these OpenMontage inputs:

- Prompt: `A cinematic clockwork heroine with luminous pink hair stands beneath
  a colossal celestial observatory, brass constellations orbiting above her,
  midnight blue and warm amber light, intricate editorial fantasy portrait,
  looking directly at the camera`
- Seed: `24082026`
- Size: `768 x 1024`
- Steps: `12`
- Guidance / CFG: `2.5`
- Output node: `9`
- Filename prefix: `image/07_flux_runtime_bound_observatory`

The returned provenance recorded the same values under
`workflow_profile.applied_bindings`, confirming that the runtime prompt replaced
the prompt baked into the ComfyUI graph.

The profile maps the local graph as follows:

| OpenMontage value | ComfyUI node | Node input |
|---|---|---|
| Prompt | `56:51` | `text` |
| Seed | `56:52` | `seed` |
| Steps | `56:52` | `steps` |
| Guidance | `56:52` | `cfg` |
| Width | `56:50` | `width` |
| Height | `56:50` | `height` |
| Filename prefix | `9` | `filename_prefix` |

## Automated verification

- ComfyUI adapter and workflow-profile contracts: `151 passed`
- Python syntax compilation: passed
- Git whitespace validation: passed
- Profile validation against `local_workflows/my_flux_txt2image.json`: passed
- Live runtime-bound FLUX generation: passed

## Findings and operational notes

1. The Animate2 workflow exposed a Windows legacy-codepage failure because its
   JSON contains UTF-8 characters. Explicit UTF-8 decoding fixed it and is
   protected by a regression test.
2. The video-to-GIF workflow returned a correct GIF, but the video adapter
   previously hard-coded `format: mp4` and default timing metadata. Result
   reporting is now based on the returned artifact extension.
3. Before image workflow profiles were added, OpenMontage provenance could show
   the caller's prompt while the custom FLUX graph still used its baked prompt.
   The live seventh generation confirms that this mismatch is fixed.
4. The SCAIL2 character-replacement graph is functional but took about 66
   minutes for the tested 81-frame output. It is suitable as a high-quality
   integration example, but a shorter workflow should be used for routine
   smoke testing.

## Recommended next engineering work

- Add a lightweight, opt-in live ComfyUI smoke-test command that does not run in
  normal CI.
- Infer the model stack for custom image workflows, matching the video adapter's
  richer provenance.
- Add media probing when exact GIF/video duration, frame count, dimensions, and
  frame rate are required rather than explicitly bound by a profile.
- Prepare a draft upstream pull request after reviewing which local workflow
  profiles are generic enough to publish.
