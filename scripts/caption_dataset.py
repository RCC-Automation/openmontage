"""Step 5 of the character workflow: caption the curated dataset and stage it.

    python scripts/caption_dataset.py --project burningman --trigger BMGRLX
    python scripts/caption_dataset.py --project burningman --trigger BMGRLX --outfit flexible --show 10

Reads `dataset/dataset.json` (the images you picked in step 4), writes one
caption per image, and stages `NNN.png` + `NNN.txt` pairs where ComfyUI's
native trainer reads them: a subfolder of `ComfyUI-Shared\\input`.

**Caption what varies. Omit what is constant about her.** Whatever a caption
never names is absorbed into the trigger token; whatever it names stays
steerable. So every caption carries the shot size (explicitly, every time - it
is the field that later lets a prompt *ask* for a framing and be obeyed),
the angle, the expression, the background and the lighting. None carries her
face, eye colour, hair colour, age or build.

The varying axes come from the descriptor each image was generated with, so
no vision model has to guess them back from pixels. Same field order in every
caption; never reordered.

**Outfit is a decision, not a default.** `--outfit fixed` (default) treats the
wardrobe as part of her - captions never mention it, the trigger learns it,
and prompting a different outfit later will fight the LoRA. `--outfit flexible`
names the clothing in every caption so it stays promptable - but the
descriptors do not record clothing per image, so flexible mode writes the
brief's wardrobe phrase and prints a warning that a VLM pass would do better.
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
import sys
from pathlib import Path

from lib.machine_paths import comfy_shared_dir

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

def _shared() -> Path:
    """The ComfyUI shared tree, discovered rather than hard-coded.

    Set COMFYUI_SHARED_DIR if it lives somewhere unusual on this machine.
    """
    d = comfy_shared_dir()
    if d is None:
        raise SystemExit(
            "ComfyUI shared tree not found. Set COMFYUI_SHARED_DIR to the "
            "directory holding models/, input/ and output/."
        )
    return d


SHARED_INPUT = _shared() / "input"

#: Shot phrases as generated -> the short, consistent token the caption uses.
SHOT_WORDS = {
    "close-up portrait, head and shoulders": "close-up portrait",
    "medium shot from the waist up": "medium shot, waist up",
    "wide shot, full figure in the environment": "full-body shot",
}
ANGLE_WORDS = {
    "facing the camera straight on": "front view",
    "three-quarter view": "three-quarter view",
    "side profile": "profile view",
}


def _trigger_ok(token: str) -> bool:
    return 7 <= len(token) <= 20 and re.fullmatch(r"[A-Za-z0-9]+", token) is not None


def _caption(trigger: str, descriptor: dict, outfit_phrase: str | None) -> str:
    """One caption, fixed field order: trigger, subject, shot, angle, expression, [outfit], background, lighting."""
    shot = SHOT_WORDS.get(descriptor.get("shot", ""), descriptor.get("shot", ""))
    angle = ANGLE_WORDS.get(descriptor.get("angle", ""), descriptor.get("angle", ""))
    parts = [f"{trigger} woman", shot, angle, descriptor.get("expression", "")]
    if outfit_phrase:
        parts.append(outfit_phrase)
    parts += [descriptor.get("background", ""), descriptor.get("lighting", "")]
    return ", ".join(p.strip() for p in parts if p and p.strip())


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project", required=True)
    parser.add_argument("--trigger", required=True, help="Invented token, 7-20 ASCII letters/digits, not a word.")
    parser.add_argument("--outfit", choices=["fixed", "flexible"], default="fixed")
    parser.add_argument("--outfit-phrase", default=None, help="flexible only: the wardrobe words to caption.")
    parser.add_argument("--folder-name", default=None, help="Staging folder under ComfyUI-Shared/input. Default: <trigger lower>_train")
    parser.add_argument("--show", type=int, default=10, help="Print the first N captions for the read-through gate.")
    args = parser.parse_args()

    if not _trigger_ok(args.trigger):
        print("FAIL: trigger must be 7-20 ASCII letters/digits and not a dictionary word (e.g. BMGRLX7)")
        return 1

    project = ROOT / "projects" / args.project
    manifest_path = project / "dataset" / "dataset.json"
    if not manifest_path.is_file():
        print(f"FAIL: no curated dataset at {manifest_path}. Run dataset_klein.py --pick first.")
        return 1
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    images = manifest.get("images", [])
    if not images:
        print("FAIL: dataset.json has no images")
        return 1

    outfit_phrase = None
    if args.outfit == "flexible":
        outfit_phrase = args.outfit_phrase or "wearing a wet white tied top and shorts"
        print("! flexible outfit: captions carry one wardrobe phrase for every image because the\n"
              "  descriptors do not record clothing per image. A VLM pass (Florence-2) would caption\n"
              "  each outfit individually; this is the honest approximation until then.\n")

    folder = args.folder_name or f"{args.trigger.lower()}_train"
    staged = SHARED_INPUT / folder
    if staged.exists():
        shutil.rmtree(staged)
    staged.mkdir(parents=True)

    captions = []
    for i, image in enumerate(images):
        caption = _caption(args.trigger, image.get("descriptor", {}), outfit_phrase)
        src = Path(image["path"])
        shutil.copyfile(src, staged / f"{i:03d}.png")
        (staged / f"{i:03d}.txt").write_text(caption, encoding="utf-8")
        # Keep the caption beside the accepted image too, so the project is
        # self-contained and the manifest can be reused for another trainer.
        src.with_suffix(".txt").write_text(caption, encoding="utf-8")
        image["caption"] = caption
        captions.append(caption)

    manifest["trigger"] = args.trigger
    manifest["outfit"] = args.outfit
    manifest["caption_fields"] = ["trigger", "subject", "shot", "angle", "expression"] + (["outfit"] if outfit_phrase else []) + ["background", "lighting"]
    manifest["staged_folder"] = str(staged)
    manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")

    print(f"captioned {len(images)} images, trigger {args.trigger}, outfit {args.outfit}")
    print(f"staged   -> {staged}  (dropdown name: {folder})")
    print(f"manifest -> {manifest_path}\n")
    print(f"read these {min(args.show, len(captions))} end to end - if her face is described in any of them, the trigger will bind weakly:")
    for c in captions[: args.show]:
        print("  ", c)
    identity_words = ("brown eyes", "blonde", "plait", "braid", "cute face", "beautiful eyes", "french", "athletic", "slender", "fit")
    leaks = [c for c in captions if any(w in c.lower() for w in identity_words)]
    if leaks:
        print(f"\n! {len(leaks)} caption(s) name an identity trait; they should not. Fix the vocabulary and re-run.")
        return 2
    print("\nno identity traits in any caption - the trigger carries her.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
