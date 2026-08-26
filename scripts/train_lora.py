"""Step 6: train the character LoRA, saving a checkpoint every N steps.

    python scripts/train_lora.py --project burningman --trigger BMGRLBR
    python scripts/train_lora.py --project burningman --trigger BMGRLBR --total 1500 --segment 250

`TrainLoraNode` has no save-every-N: it trains for `steps` and emits one
LORA_MODEL. But it accepts `existing_lora`, so a long run is submitted as a
chain of short ones, each resuming the file the last one saved. Six 250-step
segments cost the same GPU time as one 1500-step run plus a model reload
apiece, and they leave six checkpoints on disk.

That matters because **the visually best checkpoint is frequently not the last
one.** A character LoRA that is undertrained does not hold the face; one that
is overtrained holds it and nothing else - the background, the pose and the
lighting all collapse toward the training set. Loss will not tell you which
you have. `scripts/test_lora.py` renders every checkpoint against held-out
prompts so the choice is made by eye.

The staged dataset comes from `caption_dataset.py`: a subfolder of
ComfyUI-Shared's input directory holding NNN.png + NNN.txt pairs.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools._comfyui.client import ComfyUIClient, ComfyUIError  # noqa: E402
from tools._comfyui.lora_train import DEFAULT_LEARNING_RATE, build_sdxl_lora_train_graph  # noqa: E402

SHARED = Path(r"C:\Users\Barrul\AppData\Local\Comfy-Desktop\ComfyUI-Shared")
LORAS = SHARED / "models" / "loras"
#: `SaveLoRA`'s prefix is relative to the OUTPUT directory, not the models tree
#: - "loras/character/x" lands in output/loras/character/. It has to be copied
#: into models/loras/ before LoraLoader (or `existing_lora`) can see it.
SAVED_TO = SHARED / "output" / "loras" / "character"
INSTALL_TO = LORAS / "character"


def _listed_name(server: str, path: Path) -> str | None:
    """The file as ComfyUI's enum spells it - backslashes on Windows.

    A composed 'character/x.safetensors' is 'value not in list' even when the
    file is right there; the smoke run lost a render to exactly that.
    """
    info = requests.get(f"{server}/object_info/LoraLoader", timeout=60).json()
    spec = info["LoraLoader"]["input"]["required"]["lora_name"]
    names = spec[0] if isinstance(spec[0], list) else (spec[1].get("options") or [])
    tail = f"{path.parent.name}/{path.name}"
    for n in names:
        if n.replace("\\", "/").endswith(tail):
            return n
    return None


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project", required=True)
    parser.add_argument("--trigger", required=True)
    parser.add_argument("--folder", default=None, help="Staged dataset folder. Default: <trigger lower>_train")
    parser.add_argument("--checkpoint", default="juggernautXL_ragnarok.safetensors")
    parser.add_argument("--total", type=int, default=1500)
    parser.add_argument("--segment", type=int, default=250)
    parser.add_argument("--rank", type=int, default=32)
    parser.add_argument("--lr", type=float, default=DEFAULT_LEARNING_RATE)
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--timeout", type=int, default=5400)
    parser.add_argument(
        "--resume-from", type=int, default=0,
        help="Steps already trained. Continues from the checkpoint at that count.",
    )
    args = parser.parse_args()

    project = ROOT / "projects" / args.project
    out = project / "lora"
    out.mkdir(parents=True, exist_ok=True)
    folder = args.folder or f"{args.trigger.lower()}_train"
    staged = SHARED / "input" / folder
    pairs = sorted(staged.glob("*.png"))
    if not pairs:
        print(f"FAIL: no staged dataset at {staged}. Run caption_dataset.py first.")
        return 1

    client = ComfyUIClient()
    if not client.is_available():
        print("FAIL: ComfyUI is not reachable")
        return 1
    if client.queue_depth():
        print("FAIL: ComfyUI is busy; training needs the machine to itself")
        return 1

    print(f"training {args.trigger} on {len(pairs)} images from {folder}")
    print(f"{args.total} steps in {args.total // args.segment} segments of {args.segment}, "
          f"rank {args.rank}, lr {args.lr:g}, AdamW, bf16\n")

    existing = "[None]"
    checkpoints: list[dict] = []
    started = time.time()
    done = 0
    if args.resume_from:
        prior = sorted(SAVED_TO.glob(f"{args.trigger.lower()}_{args.resume_from}_steps_*.safetensors"),
                       key=lambda p: p.stat().st_mtime)
        if not prior:
            print(f"FAIL: no checkpoint at {args.resume_from} steps under {SAVED_TO}")
            return 1
        INSTALL_TO.mkdir(parents=True, exist_ok=True)
        installed = INSTALL_TO / prior[-1].name
        if not installed.is_file():
            import shutil

            shutil.copyfile(prior[-1], installed)
        listed = _listed_name(client.server_url, installed)
        if listed is None:
            print(f"FAIL: ComfyUI does not list {installed.name}")
            return 1
        existing, done = listed, args.resume_from
        checkpoints.append({"steps": done, "file": str(installed), "listed": listed,
                            "mb": round(installed.stat().st_size / 1e6, 1), "seconds": None})
        print(f"resuming from {installed.name} ({done} steps already trained)\n")
    while done < args.total:
        this = min(args.segment, args.total - done)
        target = done + this
        prefix = f"loras/character/{args.trigger.lower()}"
        graph = build_sdxl_lora_train_graph(
            checkpoint=args.checkpoint, dataset_folder=folder, prefix=prefix,
            steps=this, learning_rate=args.lr, rank=args.rank, seed=args.seed,
            existing_lora=existing,
        )
        seg_started = time.time()
        try:
            prompt_id = client.submit(graph)
            client.poll(prompt_id, timeout=args.timeout, interval=15)
        except ComfyUIError as exc:
            print(f"\nFAILED at step {target}: {str(exc)[:1500]}")
            (out / "training.json").write_text(json.dumps(
                {"trigger": args.trigger, "failed_at": target, "error": str(exc)[:3000],
                 "checkpoints": checkpoints}, indent=2), encoding="utf-8")
            return 2
        seg_seconds = time.time() - seg_started

        found = sorted(SAVED_TO.glob(f"{args.trigger.lower()}_*.safetensors"),
                       key=lambda p: p.stat().st_mtime)
        if not found:
            print(f"FAIL: segment to {target} saved nothing under {SAVED_TO}")
            return 2
        saved = found[-1]
        INSTALL_TO.mkdir(parents=True, exist_ok=True)
        installed = INSTALL_TO / saved.name
        if not installed.is_file() or installed.stat().st_mtime < saved.stat().st_mtime:
            import shutil

            shutil.copyfile(saved, installed)
        saved = installed
        listed = _listed_name(client.server_url, saved)
        if listed is None:
            print(f"FAIL: ComfyUI does not list {saved.name}; cannot resume from it")
            return 2
        existing = listed
        done = target
        checkpoints.append({
            "steps": target, "file": str(saved), "listed": listed,
            "mb": round(saved.stat().st_size / 1e6, 1), "seconds": round(seg_seconds, 1),
        })
        elapsed = time.time() - started
        left = (args.total - done) * (elapsed / done)
        print(f"  step {target:>5}/{args.total}  {seg_seconds:5.0f}s  "
              f"{saved.name}  ~{left / 60:.0f} min left")

    total_min = (time.time() - started) / 60
    record = {
        "trigger": args.trigger, "images": len(pairs), "dataset_folder": folder,
        "base": args.checkpoint, "total_steps": args.total, "segment": args.segment,
        "rank": args.rank, "learning_rate": args.lr, "optimizer": "AdamW",
        "minutes": round(total_min, 1),
        "seconds_per_step": round(total_min * 60 / args.total, 3),
        "checkpoints": checkpoints,
    }
    (out / "training.json").write_text(json.dumps(record, indent=2), encoding="utf-8")
    print(f"\n{args.total} steps in {total_min:.0f} min ({record['seconds_per_step']:.2f}s/step)")
    print(f"{len(checkpoints)} checkpoints -> {LORAS / 'character'}")
    print(f"record: {out / 'training.json'}")
    print(f"\nnext: python scripts/test_lora.py --project {args.project} --trigger {args.trigger}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
