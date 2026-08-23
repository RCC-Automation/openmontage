"""Run the quick screen test: one close-up per model, one shared seed.

    python scripts/quick_screen_test.py
    python scripts/quick_screen_test.py --dry-run
    python scripts/quick_screen_test.py --brief "an old lighthouse keeper" --budget 40

Same prompt, same seed, only the model changes. Finishes in minutes and produces
a side-by-side sheet. It cannot measure whether a model holds one identity across
seeds - run the 'shortlist' preset on the survivors before casting anything.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from lib.checkpoint import init_project  # noqa: E402
from tools._comfyui.vrgdg import VRGDGClient  # noqa: E402
from tools.graphics.screen_test import ScreenTest  # noqa: E402

DEFAULT_BRIEF = (
    "a clockwork heroine with luminous pink hair and a brass filigree collar, "
    "cinematic portrait, intricate detail"
)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project", default="screen-tests")
    parser.add_argument("--character", default="Wren")
    parser.add_argument("--brief", default=DEFAULT_BRIEF)
    parser.add_argument("--models", nargs="*", help="Defaults to every installed image model.")
    parser.add_argument("--budget", type=float, default=None, help="GPU-minute ceiling.")
    parser.add_argument("--preset", default="quick", choices=["quick", "shortlist", "full"])
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    client = VRGDGClient()
    if not client.is_available():
        print("FAIL:", client.unavailable_reason())
        return 1

    # Take the model names ComfyUI actually reports, so a typo cannot waste an hour.
    models = args.models
    if not models:
        from tools._comfyui.client import ComfyUIClient

        available = ComfyUIClient().list_models()
        pool = available.get("diffusion_models", []) + available.get("checkpoints", [])
        skip = ("wan", "ltx", "minimax", "acestep", "animate", "scail", "ernie")
        models = sorted(
            m for m in pool
            if not any(s in m.lower() for s in skip) and m.lower().endswith((".safetensors", ".gguf"))
        )
    if not models:
        print("FAIL: no image models found on the server.")
        return 1

    # The Builder's saved defaults hold the encoder and VAE that actually work here.
    defaults = {}
    try:
        defaults = (client.model_defaults().get("defaults") or {}).get("zimage_settings", {}) or {}
    except Exception:
        pass

    print(f"models under test ({len(models)}):")
    for m in models:
        print("   -", m)
    print()

    inputs = {
        "project_dir": str(init_project(args.project, title="Screen tests", pipeline_type="cinematic")),
        "character": args.character,
        "brief": args.brief,
        "matrix": {"models": models},
        "preset": args.preset,
        "clip_name": defaults.get("clip_name") or "qwen3_4b_fp8_scaled.safetensors",
        "vae_name": defaults.get("vae_name") or "ae.safetensors",
        "dry_run": bool(args.dry_run),
    }
    if args.budget:
        inputs["budget_minutes"] = args.budget

    result = ScreenTest().execute(inputs)
    print(json.dumps(result.data.get("plan", {}), indent=2))
    if not result.success:
        print("\nFAIL:", result.error)
        return 1
    if args.dry_run:
        print("\nDry run only. Re-run without --dry-run to generate.")
        return 0

    print("\nranking (this eliminates, it does not cast):")
    for row in result.data.get("shortlist", []):
        print(f"  {row['rank']}. {row['label']:<48} {row['total']:.3f}  {row['seconds_per_image']:.0f}s")
    if result.data.get("caveat"):
        print("\n!", result.data["caveat"])
    print("\nsheet:", result.data.get("comparison_sheet"))
    print("next :", result.data.get("next_step"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
