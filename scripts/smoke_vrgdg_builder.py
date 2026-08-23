"""Smoke test for the VRGDG graph-builder mode.

Reads the model names the user already saved in the VRGDG Builder, asks VRGDG
to build a Z-Image graph, runs it through comfyui_image, and prints the
provenance record. Needs ComfyUI running with comfyui-vrgamedevgirl loaded.

    python scripts/smoke_vrgdg_builder.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools._comfyui.vrgdg import VRGDGClient  # noqa: E402
from tools.graphics.comfyui_image import ComfyUIImage  # noqa: E402

PROMPT = (
    "A cinematic clockwork heroine with luminous pink hair beneath a colossal "
    "celestial observatory, brass constellations orbiting above her, midnight "
    "blue and warm amber light, intricate editorial fantasy portrait"
)


def main() -> int:
    client = VRGDGClient()
    print(f"server            : {client.server_url}")
    if not client.is_available():
        print("FAIL: " + client.unavailable_reason())
        return 1
    print(f"vrgdg pack        : {client.pack_version() or 'unknown'}")

    # Use the model names already saved in the Builder rather than the ones
    # baked into the shipped template.
    try:
        defaults = client.model_defaults().get("defaults", {})
        z = defaults.get("zimage_settings", {}) or {}
    except Exception as exc:  # noqa: BLE001
        print(f"warn: could not read model defaults ({exc}); using fallbacks")
        z = {}

    payload = {
        "unet_name": z.get("unet_name") or "zImageTurbo_turbo.safetensors",
        "clip_name": z.get("clip_name") or "qwen3_4b_fp8_scaled.safetensors",
        "vae_name": z.get("vae_name") or "ae.safetensors",
        "first_pass_width": 1280,
        "first_pass_height": 720,
        "second_pass_width": 1920,
        "second_pass_height": 1080,
        "seed": 24082301,
        "seed_mode": "fixed",
    }
    print("models            : "
          f"{payload['unet_name']} / {payload['clip_name']} / {payload['vae_name']}")

    out = ROOT / "projects" / "comfyui-connection-test" / "assets" / "images" / "vrgdg_zimage_smoke.png"
    out.parent.mkdir(parents=True, exist_ok=True)

    print("\nsubmitting ... (first run loads the models, so allow a few minutes)\n")
    result = ComfyUIImage().execute(
        {
            "prompt": PROMPT,
            "vrgdg_build": {"kind": "zimage", "payload": payload},
            "output_path": str(out),
        }
    )

    print(f"success           : {result.success}")
    if not result.success:
        print(f"error             : {result.error}")
        return 1

    print(f"artifact          : {result.artifacts[0] if result.artifacts else '-'}")
    print(f"seed              : {result.seed}")
    print(f"model             : {result.model}")
    print(f"runtime (s)       : {result.duration_seconds:.1f}")
    print("\nprovenance:")
    print(json.dumps(result.data.get("workflow_provenance", {}), indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
