# Compatibility and design notes

## Supported workflow

The current adapter supports the GGUF LTX 2.3 image-to-video route represented
by VRGDG's installed:

```text
Workflows\UsedForUIDoNotTouch\Singlei2vForUI_API.json
```

It expects the node identities used by the current VRGDG workflow, including
the decoder (`936`), image loader (`925`), scene selectors (`929`, `930`),
project inputs, two sampler passes, model loaders, optional LoRA block, and
video saver.

This is intentional fail-fast behavior. Silently writing values into the wrong
node after a VRGDG update would be worse than refusing to generate.

## Online versus offline graph generation

OpenMontage also contains `scripts/export_i2v_workflow.py`. That script calls
VRGDG's live `build_i2v` route and is preferred when ComfyUI is running because
the installed VRGDG code performs the graph construction.

This package is the offline/batch path. It is useful when:

- ComfyUI is stopped after a native crash.
- Many scene workflows must be prepared at once.
- A visible, reproducible workflow file is wanted before rendering.

Both approaches use the saved Builder session as the project authority.

## AMD/ROCm decoder workaround

The generated video decoder is:

```json
{
  "class_type": "VAEDecodeTiled",
  "inputs": {
    "tile_size": 256,
    "overlap": 64,
    "temporal_size": 32,
    "temporal_overlap": 16
  }
}
```

These values address a native ROCm/MIOpen abort observed during the final LTX
VAE decode. They trade some decode speed for smaller convolution workloads.

The separate `-DisableUpscale` option sets the second sigma schedule to `0.0`.
It addresses the much slower latent-upscale/refine pass, not the VAE decoder.

## Known limitations

- Non-GGUF LTX workflow variants are rejected.
- First/last-frame, ingredients-to-video, reference-to-video, ID-LoRA, and
  MiniMax routes have different graphs and need separate adapters.
- The image loader selects files by the first number in the filename. VRGDG's
  normal `scene_NNNN.png` layout is supported.
- Generated files are API-format JSON. Modern ComfyUI can open them directly,
  but their automatic canvas layout is mechanical.
- A VRGDG update that changes required node IDs requires an adapter update.

## Adding another VRGDG route

Do not copy a visually similar graph and remove nodes by hand. Start from the
route's complete installed API workflow or the live VRGDG build route, then:

1. Identify scene/project inputs by node class and role.
2. Preserve every required connection.
3. Apply only explicit machine compatibility transformations.
4. Validate model-loader values and installed node types.
5. Test one scene before adding batch selection.

