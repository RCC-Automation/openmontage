"""WP7 step 7.0: does LoRA training run on this ROCm machine at all?

    python scripts/train_lora_smoke.py
    python scripts/train_lora_smoke.py --steps 300 --rank 16

A throwaway LoRA from ~10 images already on disk. It is not meant to be good.
It answers three questions that every other part of WP7 depends on and nobody
has ever checked here (QUESTIONS.md Q7):

    1. does the native trainer complete on ROCm, and how long is a step
    2. does the saved file load back through LoraLoader
    3. does it move a same-seed render toward the anchor at all

Stages the dataset into ComfyUI's input directory (the folder loader reads
subfolders of it, from a dropdown - so the folder must appear in object_info
before the graph validates), submits the training graph, waits, finds the
saved file, then renders the gate pair: identical prompt and seed with and
without the LoRA, scored by ArcFace against the character's anchor.

Everything it produces is kept under projects/<project>/lora_smoke/.
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
import time
from pathlib import Path

import numpy as np
import requests

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from lib.face_identity import faces_in  # noqa: E402
from lib.sheets import ACCENTS, SheetItem, labelled_sheet  # noqa: E402
from tools._comfyui.client import ComfyUIClient, ComfyUIError  # noqa: E402
from tools._comfyui.lora_train import (  # noqa: E402
    DEFAULT_LEARNING_RATE,
    build_sdxl_lora_render_graph,
    build_sdxl_lora_train_graph,
)

# ComfyUI Desktop keeps input, output and models in the SHARED tree, not under
# the install. <install>/input exists too - stale, holding a placeholder - and a
# folder staged there never appears in the loader's dropdown. HANDOFF section 3.
SHARED = Path(r"C:\Users\Barrul\AppData\Local\Comfy-Desktop\ComfyUI-Shared")
COMFY = SHARED
MODELS = SHARED / "models"


def _vector(path: Path) -> np.ndarray | None:
    found = faces_in(path)
    if len(found) != 1:
        return None
    v = getattr(found[0], "normed_embedding", None)
    return None if v is None else np.asarray(v, dtype=np.float32)


def _folder_options(server: str) -> list[str]:
    info = requests.get(f"{server}/object_info/LoadImageTextDataSetFromFolder", timeout=60).json()
    spec = info["LoadImageTextDataSetFromFolder"]["input"]["required"]["folder"]
    if isinstance(spec[0], list):
        return list(spec[0])
    if len(spec) > 1 and isinstance(spec[1], dict):
        return list(spec[1].get("options") or [])
    return []


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project", default="character-lora")
    parser.add_argument("--images-dir", default=None, help="Defaults to <project>/dataset/renders/close_up")
    parser.add_argument("--anchor", default=None, help="Defaults to <project>/anchor/anchor.png")
    parser.add_argument("--n", type=int, default=10)
    parser.add_argument("--trigger", default="WRENX")
    parser.add_argument("--caption", default="{trigger} woman, close-up portrait, head and shoulders")
    parser.add_argument("--checkpoint", default="juggernautXL_ragnarok.safetensors")
    parser.add_argument("--folder-name", default="lora_smoke")
    parser.add_argument("--comfy-input", default=str(COMFY / "input"))
    parser.add_argument("--comfy-output", default=str(COMFY / "output"))
    parser.add_argument("--steps", type=int, default=200)
    parser.add_argument("--lr", type=float, default=DEFAULT_LEARNING_RATE)
    parser.add_argument("--rank", type=int, default=16)
    parser.add_argument("--strength", type=float, default=0.8)
    parser.add_argument("--gate-seed", type=int, default=7777)
    parser.add_argument("--timeout", type=int, default=5400)
    parser.add_argument(
        "--lora", default=None,
        help="Skip training; run only the gate against this file in models/loras/ (e.g. character/x.safetensors).",
    )
    args = parser.parse_args()

    project = ROOT / "projects" / args.project
    images_dir = Path(args.images_dir) if args.images_dir else project / "dataset" / "renders" / "close_up"
    anchor = Path(args.anchor) if args.anchor else project / "anchor" / "anchor.png"
    out = project / "lora_smoke"
    out.mkdir(parents=True, exist_ok=True)

    images = sorted(images_dir.glob("*.png"))[: args.n]
    if len(images) < 4:
        print(f"FAIL: need at least 4 images in {images_dir}, found {len(images)}")
        return 1
    anchor_vector = _vector(anchor)
    if anchor_vector is None:
        print(f"FAIL: anchor at {anchor} has no single face")
        return 1

    client = ComfyUIClient()
    if not client.is_available():
        print("FAIL: ComfyUI is not reachable")
        return 1
    if client.queue_depth():
        print("FAIL: ComfyUI is busy; a training run must have the machine to itself")
        return 1

    if args.lora:
        installed = MODELS / "loras" / args.lora
        if not installed.is_file():
            print(f"FAIL: no such LoRA {installed}")
            return 1
        train_seconds = 0.0
        print(f"gate only, against {installed.name}")
    else:
        # --------------------------------------------------------- stage
        staged = Path(args.comfy_input) / args.folder_name
        if staged.exists():
            shutil.rmtree(staged)
        staged.mkdir(parents=True)
        caption = args.caption.format(trigger=args.trigger)
        for i, src in enumerate(images):
            shutil.copyfile(src, staged / f"{i:03d}.png")
            (staged / f"{i:03d}.txt").write_text(caption, encoding="utf-8")
        print(f"staged {len(images)} image+caption pairs -> {staged}")
        print(f"caption: {caption!r}")

        options = _folder_options(client.server_url)
        if args.folder_name not in options:
            print(f"FAIL: '{args.folder_name}' is not in the loader's dropdown {options}.")
            print(f"      ComfyUI's input directory is not {args.comfy_input}, or it needs a refresh.")
            return 1

        # --------------------------------------------------------- train
        prefix = f"loras/character/{args.trigger.lower()}_smoke"
        graph = build_sdxl_lora_train_graph(
            checkpoint=args.checkpoint,
            dataset_folder=args.folder_name,
            prefix=prefix,
            steps=args.steps,
            learning_rate=args.lr,
            rank=args.rank,
        )
        (out / "train_graph.json").write_text(json.dumps(graph, indent=2), encoding="utf-8")
        print(f"\ntraining: {args.steps} steps, rank {args.rank}, lr {args.lr:g}, AdamW, bf16")
        started = time.time()
        try:
            prompt_id = client.submit(graph)
            print(f"submitted {prompt_id}; waiting up to {args.timeout}s ...")
            client.poll(prompt_id, timeout=args.timeout, interval=15)
        except ComfyUIError as exc:
            elapsed = time.time() - started
            print(f"\nTRAINING FAILED after {elapsed:.0f}s:\n{str(exc)[:3000]}")
            (out / "result.json").write_text(
                json.dumps({"trained": False, "error": str(exc)[:5000], "seconds": round(elapsed, 1)}, indent=2),
                encoding="utf-8",
            )
            return 2
        train_seconds = time.time() - started
        print(f"training finished in {train_seconds:.0f}s ({train_seconds / max(1, args.steps):.2f}s/step)")

        # -------------------------------------------------------- locate
        candidates = sorted(
            list((Path(args.comfy_output) / "loras" / "character").glob(f"{args.trigger.lower()}_smoke*.safetensors"))
            + list((MODELS / "loras" / "character").glob(f"{args.trigger.lower()}_smoke*.safetensors")),
            key=lambda p: p.stat().st_mtime,
        )
        if not candidates:
            print("FAIL: training reported success but no .safetensors was written under output/loras/character or models/loras/character")
            return 2
        saved = candidates[-1]
        lora_dir = MODELS / "loras" / "character"
        lora_dir.mkdir(parents=True, exist_ok=True)
        installed = lora_dir / saved.name
        if saved.resolve() != installed.resolve():
            shutil.copyfile(saved, installed)
        print(f"lora: {installed} ({installed.stat().st_size / 1e6:.1f} MB)")

    # The name must be exactly as ComfyUI lists it. On Windows that is a
    # backslash-joined relative path, and a forward slash is "value not in
    # list" - the first smoke lost its gate to precisely that.
    listed = requests.get(f"{client.server_url}/object_info/LoraLoader", timeout=60).json()
    spec = listed["LoraLoader"]["input"]["required"]["lora_name"]
    names = spec[0] if isinstance(spec[0], list) else (spec[1].get("options") if len(spec) > 1 else [])
    matches = [n for n in names if n.replace("\\", "/").endswith("character/" + installed.name)]
    if not matches:
        print(f"FAIL: ComfyUI does not list {installed.name} under loras/ yet (has {len(names)} entries). Refresh or restart it.")
        return 2
    lora_name = matches[0]
    print(f"as listed: {lora_name}")

    # --------------------------------------------------------------- gate
    gate_prompt = f"{args.trigger} woman, close-up portrait, head and shoulders, soft key light, facing the camera"
    renders = {}
    for label, name in (("without", None), ("with", lora_name)):
        dest = out / f"gate_{label}.png"
        g = build_sdxl_lora_render_graph(
            checkpoint=args.checkpoint, prompt=gate_prompt, seed=args.gate_seed,
            lora_name=name, strength_model=args.strength, strength_clip=args.strength,
        )
        try:
            client.generate(g, output_node="7", dest=dest, timeout=600)
        except Exception as exc:
            print(f"gate render '{label}' FAILED: {str(exc)[:400]}")
            (out / "result.json").write_text(
                json.dumps({"trained": True, "lora": str(installed), "train_seconds": round(train_seconds, 1),
                            "gate": f"render {label} failed: {str(exc)[:1000]}"}, indent=2), encoding="utf-8")
            return 3
        v = _vector(dest)
        renders[label] = None if v is None else float(np.dot(anchor_vector, v))
        print(f"gate {label:7s}: cos to anchor {'no face' if v is None else f'{renders[label]:.4f}'}")

    moved = (renders.get("with") is not None and renders.get("without") is not None
             and renders["with"] > renders["without"])
    sheet = labelled_sheet(
        [
            SheetItem(anchor, "anchor", "", ACCENTS[1]),
            SheetItem(out / "gate_without.png", "same seed, no LoRA", f"cos {renders.get('without')}", ACCENTS[3]),
            SheetItem(out / "gate_with.png", f"LoRA @ {args.strength}", f"cos {renders.get('with')}", ACCENTS[0] if moved else ACCENTS[3]),
        ],
        out / "gate.png", columns=3, cell=420,
        title=f"7.0 smoke: {args.steps} steps on {len(images)} images. Did identity move toward the anchor?",
    )
    result = {
        "trained": True,
        "lora": str(installed),
        "train_seconds": round(train_seconds, 1),
        "seconds_per_step": round(train_seconds / max(1, args.steps), 3),
        "steps": args.steps, "rank": args.rank, "lr": args.lr, "images": len(images),
        "gate": {"without": renders.get("without"), "with": renders.get("with"), "moved_toward_anchor": moved},
        "sheet": None if sheet is None else str(sheet),
    }
    (out / "result.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(f"\nsheet : {sheet}")
    print(f"result: {out / 'result.json'}")
    print(f"\nGATE {'PASSED' if moved else 'FAILED'}: with {renders.get('with')} vs without {renders.get('without')}")
    return 0 if moved else 4


if __name__ == "__main__":
    raise SystemExit(main())
