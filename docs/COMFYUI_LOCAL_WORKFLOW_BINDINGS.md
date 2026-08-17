# Local ComfyUI Workflow Bindings

This document records the node and input mappings discovered in the API-format
ComfyUI workflows under `local_workflows/`. It is intended to guide a reusable
OpenMontage workflow-profile implementation. The source workflows were not
modified during this analysis.

## Recommended implementation order

1. `my_video_wan2_2_14B_i2v.json`
2. `my_video_wan2_2_14B_flf2v.json`
3. `my_video_wan_animate2.json`
4. `my_video_wan21_scail2_character_replacement.json`

The WAN 2.2 I2V graph is the best first integration target because it has a
single prompt, sampler, image input, and final output. SCAIL2 requires
multi-target bindings and coordinated chunk arithmetic.

## WAN 2.2 14B image-to-video

Workflow: `local_workflows/my_video_wan2_2_14B_i2v.json`

| OpenMontage value | Node | Input | Notes |
|---|---:|---|---|
| Positive prompt | `171` | `text` | Main generation prompt |
| Negative prompt | `168` | `text` | Empty in exported graph |
| Seed | `181` | `noise_seed` | High-noise sampling stage |
| Width | `165` | `width` | Currently 640 |
| Height | `165` | `height` | Currently 640 |
| Duration seconds | `192` | `value` | Currently 5 |
| FPS | `193` | `value` | Currently 16 |
| Frame count | `194` | computed | `floor(duration * fps + 1)` |
| Starting image | `97` | `image` | ComfyUI input filename |
| Output prefix | `108` | `filename_prefix` | Final video prefix |
| Final output | `108` | - | `SaveVideo` node |

Use `output_node="108"`. Prefer changing duration and FPS instead of replacing
the `165.length` connection. Node 194 already calculates WAN-compatible frame
counts, such as 81 frames for five seconds at 16 FPS.

Suggested profile:

```json
{
  "workflow_name": "wan2.2-14b-i2v-rocm",
  "output_node": "108",
  "bindings": {
    "prompt": {"node": "171", "input": "text"},
    "negative_prompt": {"node": "168", "input": "text"},
    "seed": {"node": "181", "input": "noise_seed"},
    "width": {"node": "165", "input": "width"},
    "height": {"node": "165", "input": "height"},
    "duration_seconds": {"node": "192", "input": "value"},
    "fps": {"node": "193", "input": "value"},
    "reference_image": {"node": "97", "input": "image"},
    "filename_prefix": {"node": "108", "input": "filename_prefix"}
  }
}
```

## WAN 2.2 14B first/last-frame-to-video

Workflow: `local_workflows/my_video_wan2_2_14B_flf2v.json`

| OpenMontage value | Node | Input |
|---|---:|---|
| Positive prompt | `6` | `text` |
| Negative prompt | `7` | `text` |
| Seed | `57` | `noise_seed` |
| Width | `67` | `width` |
| Height | `67` | `height` |
| Frame count | `67` | `length` |
| First-frame image | `68` | `image` |
| Last-frame image | `62` | `image` |
| FPS | `60` | `fps` |
| Output prefix | `61` | `filename_prefix` |
| Final output | `61` | - |

Use `output_node="61"`. Only node 57 should receive the requested seed. Node
58 has noise disabled and its `noise_seed=0` should remain unchanged.

Suggested profile:

```json
{
  "workflow_name": "wan2.2-14b-first-last-frame-rocm",
  "output_node": "61",
  "bindings": {
    "prompt": {"node": "6", "input": "text"},
    "negative_prompt": {"node": "7", "input": "text"},
    "seed": {"node": "57", "input": "noise_seed"},
    "width": {"node": "67", "input": "width"},
    "height": {"node": "67", "input": "height"},
    "num_frames": {"node": "67", "input": "length"},
    "first_frame": {"node": "68", "input": "image"},
    "last_frame": {"node": "62", "input": "image"},
    "fps": {"node": "60", "input": "fps"},
    "filename_prefix": {"node": "61", "input": "filename_prefix"}
  }
}
```

## WAN Animate2

Workflow: `local_workflows/my_video_wan_animate2.json`

| OpenMontage value | Node | Input | Notes |
|---|---:|---|---|
| Main prompt | `261:3` | `text` | Appearance and motion prompt |
| Negative prompt | `261:4` | `text` | Generation exclusions |
| Pose prompt | `261:222` | `text` | Pose/reference description |
| Seed | `261:19` | `noise_seed` | Main sampler |
| Reference image | `189` | `image` | ComfyUI input filename |
| Driving video | `240` | `file` | ComfyUI input filename |
| Width | `261:243` | `resize_type.width` | Drives downstream width |
| Height | `261:243` | `resize_type.height` | Drives downstream height |
| Frame count | `261:247` | `length` | Currently 81 |
| Output prefix | `246` | `filename_prefix` | Clean generated video |
| Final output | `246` | - | Use this output |
| Comparison output | `292` | - | Side-by-side review only |

Use `output_node="246"` for production assets. Node 292 emits the side-by-side
comparison rather than the clean generated clip. Dimensions are derived from
the resized driving video, so patch node `261:243`, not the connected width and
height inputs on node `261:247`.

Suggested profile:

```json
{
  "workflow_name": "wan-animate2-rocm",
  "output_node": "246",
  "bindings": {
    "prompt": {"node": "261:3", "input": "text"},
    "negative_prompt": {"node": "261:4", "input": "text"},
    "pose_prompt": {"node": "261:222", "input": "text"},
    "seed": {"node": "261:19", "input": "noise_seed"},
    "reference_image": {"node": "189", "input": "image"},
    "driving_video": {"node": "240", "input": "file"},
    "width": {"node": "261:243", "input": "resize_type.width"},
    "height": {"node": "261:243", "input": "resize_type.height"},
    "num_frames": {"node": "261:247", "input": "length"},
    "filename_prefix": {"node": "246", "input": "filename_prefix"}
  }
}
```

## WAN 2.1 SCAIL2 character replacement

Workflow: `local_workflows/my_video_wan21_scail2_character_replacement.json`

This graph has two generation passes. Global values must be applied to both
passes.

| Value | First pass | Second pass |
|---|---|---|
| Positive prompt | `213:3.text` | `262:258.text` |
| Negative prompt | `213:4.text` | `262:257.text` |
| Seed | `213:19.noise_seed` | `262:227.noise_seed` |
| Width | `213:178.value` | `262:236.value` |
| Height | `213:179.value` | `262:237.value` |
| Source batch length | `213:177.length` | `262:235.length` |

Shared values:

| OpenMontage value | Node | Input |
|---|---:|---|
| Reference character image | `30` | `image` |
| Source/driving video | `155` | `file` |
| First-pass output | `202` | - |
| Final combined prefix | `271` | `filename_prefix` |
| Final combined output | `271` | - |

Use `output_node="271"`. The profile format must permit one logical input to
patch multiple node/input targets. Do not expose a simple `num_frames` binding
yet: the two passes, overlap, batch offsets, and stitching expressions must be
changed coherently.

Suggested profile excerpt:

```json
{
  "workflow_name": "wan21-scail2-character-replacement-rocm",
  "output_node": "271",
  "bindings": {
    "prompt": [
      {"node": "213:3", "input": "text"},
      {"node": "262:258", "input": "text"}
    ],
    "negative_prompt": [
      {"node": "213:4", "input": "text"},
      {"node": "262:257", "input": "text"}
    ],
    "seed": [
      {"node": "213:19", "input": "noise_seed"},
      {"node": "262:227", "input": "noise_seed"}
    ],
    "width": [
      {"node": "213:178", "input": "value"},
      {"node": "262:236", "input": "value"}
    ],
    "height": [
      {"node": "213:179", "input": "value"},
      {"node": "262:237", "input": "value"}
    ],
    "reference_image": {"node": "30", "input": "image"},
    "driving_video": {"node": "155", "input": "file"},
    "filename_prefix": {"node": "271", "input": "filename_prefix"}
  }
}
```

## Video-to-GIF utility workflow

Workflow: `local_workflows/my_v2i.json`

This is a conversion utility, not a video-generation workflow.

| Value | Node | Input |
|---|---:|---|
| Input video | `2` | `video` |
| Maximum loaded frames | `2` | `frame_load_cap` |
| Output prefix | `4` | `filename_prefix` |
| Output format | `4` | `format` |
| Output node | `4` | - |

It should not be registered as an OpenMontage `video_generation` profile.

## Required adapter work

Implementation status on `integration/comfyui-local`:

- Workflow-profile validation and scalar/multi-target binding are implemented.
- `comfyui_video` accepts `workflow_profile_json` or `workflow_profile_path`.
- Profile-bound reference images are uploaded through ComfyUI's
  `/upload/image` endpoint and the returned server filename is patched into the
  declared `reference_image` binding.
- Driving-video upload, filename-prefix binding, and expanded profile
  provenance remain future work.

### Parameter injection

For profile-bound custom workflows, the adapter now:

1. Load the API-format workflow and profile.
2. Validate that every referenced node and input exists.
3. Patch scalar or multi-target bindings.
4. Submit the patched graph.
5. Retrieve artifacts from the declared output node.
6. Record the workflow name, hash, model information, and applied bindings as
   provenance.

### Input upload

The workflows contain ComfyUI-local filenames such as images and driving
videos. Profile-bound `reference_image` inputs now use the same upload behavior
as the bundled WAN I2V path. Driving-video and other arbitrary file bindings do
not yet automatically receive that behavior.

### Profile validation

Reject a profile before submission when:

- a node does not exist;
- an input field does not exist;
- a requested binding has no target;
- an output node is absent;
- an input upload cannot be completed;
- a multi-target binding only patches some of its declared targets.

## Scope note

These bindings are specific to the exported graph versions currently stored
under `local_workflows/`. Re-exporting or structurally editing a ComfyUI graph
can change node IDs. Profiles must therefore fail clearly when their graph no
longer matches rather than silently submitting partially patched workflows.
