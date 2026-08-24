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
from lib.model_registry import (  # noqa: E402
    ModelRegistry,
    default_ledger_path,
    default_models_root,
)
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
    parser.add_argument(
        "--recipe", default="auto", choices=["auto", "always", "never"],
        help=(
            "Whether to drive each checkpoint at the sampler settings in its own "
            "metadata. auto: only where the graph is the shape those settings came "
            "from. always: force it everywhere. never: identical sampling for all."
        ),
    )
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    client = VRGDGClient()
    if not client.is_available():
        print("FAIL:", client.unavailable_reason())
        return 1

    # Which files are image generators is read from their headers, not guessed
    # from their names - "moodyRealMix_ZIT_V7Global" is a Z-Image UNet and
    # "gonzalomoXLFluxPony_v30FluxDAIO" is a Flux.1 bundle. See lib/model_registry.
    registry = ModelRegistry.load(default_models_root(), default_ledger_path())
    counts = registry.scan()
    registry.save()
    print(f"registry: {counts['scanned']} files scanned, "
          f"{counts['added']} new, {counts['reclassified']} reclassified")

    models = args.models
    if not models:
        models = [Path(key).name for key in registry.eligible()]
    if not models:
        print("FAIL: no image models the installed graph sources can drive.")
        for key, why in registry.excluded().items():
            print(f"   excluded {Path(key).name}: {why}")
        return 1

    unknown = registry.unknown()
    if unknown:
        print(f"\n{len(unknown)} file(s) need a verdict before they can be tested:")
        for key in unknown:
            print(f"   {Path(key).name} - {registry.entries[key]['reason']}")
        print("   Resolve with ModelRegistry.resolve(key, eligible=True|False).\n")

    # No global encoder or VAE. Once a sweep mixes families there is no single
    # right answer: Z-Image decodes a 16-channel latent through ae.safetensors,
    # Flux.2 a 128-channel one through flux2-vae, and forcing one on the other
    # fails inside VAEDecode. The registry supplies each family's own pair.
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
        "use_embedded_recipe": args.recipe,
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

    dropped = result.data.get("shortlist_dropped") or 0
    total = result.data.get("ranked_total")
    heading = "ranking (this eliminates, it does not cast)"
    if dropped:
        heading += f" - showing {total - dropped} of {total}, {dropped} below the cut"
    print(f"\n{heading}:")
    for row in result.data.get("shortlist", []):
        print(f"  {row['rank']}. {row['label']:<48} {row['total']:.3f}  {row['seconds_per_image']:.0f}s")
    recipes = result.data.get("sampler_recipes_used") or {}
    if recipes:
        # The sweep's premise is that only the model varies. When a checkpoint
        # states its own sampler settings we honour them, which breaks that
        # premise - so say exactly where and how.
        print("\ndriven at their own embedded settings (not the shared defaults):")
        for label, recipe in sorted(recipes.items()):
            detail = ", ".join(f"{k}={v}" for k, v in sorted(recipe.items()))
            print(f"  {label:<48} {detail}")
    if result.data.get("contended_renders"):
        print(f"\n! {result.data['contended_renders']} render(s) shared the machine; "
              "their timings were not recorded")
    if result.data.get("caveat"):
        print("\n!", result.data["caveat"])
    print("\nsheet:", result.data.get("comparison_sheet"))
    print("next :", result.data.get("next_step"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
