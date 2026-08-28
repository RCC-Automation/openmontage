# OpenMontage workflow utilities

This directory contains reusable workflow adapters and operator-facing tools.
Generated media and machine-specific ComfyUI graphs do not belong here; they
remain under an OpenMontage production project or the source VRGDG project.

## Available packages

- [`vrgdg-i2v-generator/`](vrgdg-i2v-generator/README.md) — export one,
  selected, or all scenes from a compatible VRGDG AI Video Builder project as
  complete standalone ComfyUI LTX I2V workflows, including the AMD-safe tiled
  VAE decoder.

