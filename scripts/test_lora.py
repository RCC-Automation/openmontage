"""Step 7: which checkpoint is her? Held-out prompts, every checkpoint, one sheet.

    python scripts/test_lora.py --project burningman --trigger BMGRLBR
    python scripts/test_lora.py --project burningman --trigger BMGRLBR --strength 0.7

Ten prompts that appear nowhere in the training captions - different clothes,
different places, different actions - rendered at the same seed with **no LoRA**
and with **every checkpoint**. The no-LoRA column is the control: it is what the
base model does with the trigger word alone, which is nothing.

Two numbers per render, and they pull against each other:

    cos_face     ArcFace to the face master. Is it her?
    novelty      CLIP distance to the nearest training image. Is it a NEW
                 picture, or is the LoRA replaying what it memorised?

**Overtraining is what this catches.** Identity climbs with steps and keeps
climbing after the model has stopped being able to render anything but the
training set - same pose, same wet top, same playa, whatever the prompt asked
for. A checkpoint that scores 0.75 identity at 0.30 novelty is worse than one
at 0.65 and 0.60. Neither number decides: the sheet is per-checkpoint so the
choice is made by eye, which is the whole reason the checkpoints exist.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from lib.face_identity import faces_in  # noqa: E402
from lib.sheets import ACCENTS, SheetItem, labelled_sheet  # noqa: E402
from tools._comfyui.client import ComfyUIClient  # noqa: E402
from tools._comfyui.lora_train import build_sdxl_lora_render_graph  # noqa: E402

#: Held out on purpose: none of these clothes, places or actions appears in a
#: training caption. A LoRA that only works on the training prompts has learned
#: the dataset, not the character.
HELD_OUT = [
    "walking through a crowded market in a red summer dress, full body, natural daylight",
    "sitting at a cafe table in a black leather jacket, medium shot, overcast",
    "close-up portrait in a wool coat with snow falling, winter light",
    "standing on a city rooftop at night in a silver party dress, neon signs behind her",
    "in a library reading, medium shot, warm lamplight, wearing a grey sweater",
    "on a sailboat in a striped swimsuit, full body, bright midday sun",
    "close-up portrait, business suit, office window light, serious expression",
    "hiking on a forest trail in a green raincoat, full body, soft diffused light",
    "at a formal dinner in an evening gown, medium shot, candlelight",
    "close-up portrait, hair wet from rain, plain dark background, dramatic side light",
]


def _vector(path: Path) -> np.ndarray | None:
    found = faces_in(path)
    if not found:
        return None
    v = getattr(found[0], "normed_embedding", None)
    return None if v is None else np.asarray(v, dtype=np.float32)


def _clip(paths: list[Path]) -> np.ndarray | None:
    try:
        from lib.clip_embedder import embed_images
    except Exception:
        return None
    try:
        v = np.asarray(embed_images([str(p) for p in paths]), dtype=np.float32)
    except Exception:
        return None
    n = np.linalg.norm(v, axis=1, keepdims=True)
    n[n == 0] = 1.0
    return v / n


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project", required=True)
    parser.add_argument("--trigger", required=True)
    parser.add_argument("--checkpoint", default="juggernautXL_ragnarok.safetensors")
    parser.add_argument("--strength", type=float, default=0.8)
    parser.add_argument("--seed", type=int, default=31337)
    parser.add_argument("--prompts", type=int, default=10)
    args = parser.parse_args()

    project = ROOT / "projects" / args.project
    record_path = project / "lora" / "training.json"
    if not record_path.is_file():
        print(f"FAIL: no training record at {record_path}")
        return 1
    record = json.loads(record_path.read_text(encoding="utf-8"))
    checkpoints = record.get("checkpoints", [])
    if not checkpoints:
        print("FAIL: the training record has no checkpoints")
        return 1

    masters = json.loads((project / "masters" / "masters.json").read_text(encoding="utf-8"))
    face_vector = _vector(Path(masters["face"]))
    if face_vector is None:
        print("FAIL: the face master has no detectable face")
        return 1
    manifest = json.loads((project / "dataset" / "dataset.json").read_text(encoding="utf-8"))
    train_paths = [Path(i["path"]) for i in manifest["images"]]
    train_clip = _clip(train_paths)
    if train_clip is None:
        print("! CLIP unavailable - novelty will not be measured, only identity")

    out = project / "lora_test"
    out.mkdir(parents=True, exist_ok=True)
    client = ComfyUIClient()
    if not client.is_available():
        print("FAIL: ComfyUI is not reachable")
        return 1

    prompts = HELD_OUT[: args.prompts]
    columns = [("none", None)] + [(str(c["steps"]), c["listed"]) for c in checkpoints]
    print(f"{len(prompts)} held-out prompts x {len(columns)} columns "
          f"(no LoRA + {len(checkpoints)} checkpoints) = {len(prompts) * len(columns)} renders\n")

    rows: list[dict] = []
    started = time.time()
    for label, lora in columns:
        col_dir = out / f"steps_{label}"
        col_dir.mkdir(exist_ok=True)
        paths, faces = [], []
        for i, prompt in enumerate(prompts):
            full = f"{args.trigger} woman, {prompt}"
            path = col_dir / f"{i:02d}.png"
            if not path.is_file():
                graph = build_sdxl_lora_render_graph(
                    checkpoint=args.checkpoint, prompt=full, seed=args.seed + i,
                    lora_name=lora, strength_model=args.strength, strength_clip=args.strength,
                )
                try:
                    client.generate(graph, output_node="7", dest=path, timeout=600)
                except Exception as exc:
                    print(f"  {label:>5}  prompt {i}: FAILED {str(exc)[:90]}")
                    continue
            v = _vector(path)
            paths.append(path)
            faces.append(None if v is None else float(np.dot(face_vector, v)))
        # Novelty: 1 - the highest CLIP similarity to any training image. Low
        # means this render is a near-copy of something in the dataset.
        novelty = None
        if train_clip is not None and paths:
            rendered = _clip(paths)
            if rendered is not None:
                novelty = float((1.0 - (rendered @ train_clip.T).max(axis=1)).mean())
        scored = [f for f in faces if f is not None]
        rows.append({
            "label": label, "lora": lora, "paths": [str(p) for p in paths],
            "cos_face": [None if f is None else round(f, 4) for f in faces],
            "mean_cos": round(float(np.mean(scored)), 4) if scored else None,
            "faces_found": len(scored), "novelty": None if novelty is None else round(novelty, 4),
        })
        mean_t = "n/a" if not scored else f"{np.mean(scored):.3f}"
        nov_t = "n/a" if novelty is None else f"{novelty:.3f}"
        print(f"  {label:>5} steps  identity {mean_t}  novelty {nov_t}  "
              f"({len(scored)}/{len(prompts)} had a face)")

    sheets = {}
    for row in rows:
        items = [
            SheetItem(Path(p), f"{row['label']} steps",
                      f"cos {c:.2f}" if c is not None else "no face",
                      ACCENTS[1] if row["label"] == "none" else ACCENTS[0])
            for p, c in zip(row["paths"], row["cos_face"])
        ]
        s = labelled_sheet(items, out / f"sheet_{row['label']}.png", columns=5, cell=340,
                           title=(f"{args.trigger} @ {row['label']} steps - held-out prompts. "
                                  f"identity {row['mean_cos']}  novelty {row['novelty']}"))
        if s:
            sheets[row["label"]] = str(s)

    report = {
        "trigger": args.trigger, "strength": args.strength, "seed": args.seed,
        "prompts": prompts, "training": {k: record[k] for k in ("total_steps", "rank", "learning_rate", "images")},
        "columns": rows, "sheets": sheets,
        "reading": ("identity = ArcFace to the face master. novelty = 1 - max CLIP similarity to any "
                    "training image; low novelty means the LoRA is replaying the dataset. Pick by eye."),
        "minutes": round((time.time() - started) / 60, 1),
    }
    (out / "test_report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(f"\nreport: {out / 'test_report.json'}")
    for label, s in sheets.items():
        print(f"  {label:>5} steps  {s}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
