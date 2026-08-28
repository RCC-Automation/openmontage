"""The image bench, run on a character instead of a generic subject.

The difference is that a character has a ground truth. Every render is scored
by ArcFace cosine against the character's approved anchor, so "which model is
best" stops being a matter of taste and becomes two separate questions:

  * which model renders the best PICTURE from the description alone, and
  * which model, or which mechanism, actually produces THIS PERSON.

Those have different answers, and the second one is what a film needs.

    python workflows/image-bench/run_character.py --project projects/burningman

Bands measured on this machine (wiki/character/measuring-identity.md):
  0.10-0.21  different people          0.53-0.68  Klein reference conditioning
  0.12-0.46  LoRA, native trainer      0.75-0.84  IP-Adapter FaceID
  0.80-0.88  ReActor face swap         0.92       the same woman, best case
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import numpy as np  # noqa: E402

from graphs import MODELS, build, klein, sdxl, zimage  # noqa: E402
from lib.face_identity import face_embeddings, faces_in  # noqa: E402

SRV = "http://127.0.0.1:8188"
COMFY_INPUT = Path(r"C:\Users\Barrul\AppData\Local\Comfy-Desktop\ComfyUI-Shared\input")
W, H = 1280, 720

# Her canonical brief. The identity-carrying tokens are constant; only the
# framing clause changes between shot sizes, so the two runs are comparable.
SUBJECT = ("Rave, outdoors, burning man, young woman, athletic, slender, fit, cute face, "
           "brown eyes, blonde hair, plaits, hair strands framing face, beautiful eyes, "
           "French, sweaty, loose flowing top, midriff, outdoor festival, smirk, posing, "
           "traditional media, real life photo, cinematic")

FRAMINGS = {
    # The clause her anchor was selected under.
    "closeup": "close-up portrait, head and shoulders. soft key light, gentle falloff. "
               "facing the camera straight on",
    # The one that breaks things: at full length the face is a tiny part of the
    # frame, which is where reference conditioning was measured to collapse
    # (DECISIONS #30) and where ArcFace starts returning noise (#40).
    "fullbody": "full body shot, head to feet in frame, standing, wide framing showing the "
                "whole figure and the desert around her. soft key light, gentle falloff. "
                "facing the camera straight on",
}
NEGATIVE = "blurry, low quality, deformed, plastic skin, oversaturated, watermark, cropped head"

#: Below this the face is too few pixels for ArcFace to mean anything. Measured
#: convention from DECISIONS #40: identity read off a frame where the face is
#: under ~1% of the area is noise, including negative cosines.
MEASURABLE_FACE_FRACTION = 0.01

# Trained here on her dataset. UNet-only from the native trainer, so weak - it is
# in the sweep to show the ceiling of that route, not because it is recommended.
HER_LORA = r"character\bmgrlbr_1500_steps_01251_.safetensors"


def wait_for_queue(limit_s: int = 3600) -> bool:
    start = time.time()
    while time.time() - start < limit_s:
        try:
            q = json.load(urllib.request.urlopen(SRV + "/queue", timeout=15))
        except Exception:
            time.sleep(5)
            continue
        if not (q.get("queue_running") or q.get("queue_pending")):
            return True
        time.sleep(5)
    return False


def flush() -> None:
    try:
        req = urllib.request.Request(
            SRV + "/free", data=json.dumps({"unload_models": True, "free_memory": True}).encode(),
            headers={"Content-Type": "application/json"})
        urllib.request.urlopen(req, timeout=180).read()
        time.sleep(4)
    except Exception:
        pass


def submit(graph: dict, dest: Path, timeout_s: int = 2400) -> float | None:
    if not wait_for_queue():
        return None
    started = time.time()
    try:
        req = urllib.request.Request(
            SRV + "/prompt", data=json.dumps({"prompt": graph, "client_id": "char-bench"}).encode(),
            headers={"Content-Type": "application/json"})
        pid = json.load(urllib.request.urlopen(req, timeout=60))["prompt_id"]
    except urllib.error.HTTPError as exc:
        print(f"    FAIL submit: {exc.read().decode()[:300]}")
        return None
    while True:
        if time.time() - started > timeout_s:
            print("    TIMEOUT")
            return None
        time.sleep(3)
        try:
            hist = json.load(urllib.request.urlopen(f"{SRV}/history/{pid}", timeout=120))
        except Exception:
            print("    LOST: backend died")
            return None
        if pid in hist:
            break
    entry = hist[pid]
    if not entry.get("status", {}).get("completed", True):
        print(f"    FAIL: {json.dumps(entry.get('status', {}).get('messages', []))[-300:]}")
        return None
    for _n, out in entry.get("outputs", {}).items():
        for image in out.get("images", []):
            qs = urllib.parse.urlencode({"filename": image["filename"],
                                         "subfolder": image.get("subfolder", ""),
                                         "type": image.get("type", "output")})
            dest.write_bytes(urllib.request.urlopen(f"{SRV}/view?{qs}", timeout=300).read())
    return round(time.time() - started, 1)


def faceswap_graph(target: str, source: str) -> dict:
    return {
        "1": {"class_type": "LoadImage", "inputs": {"image": target}, "_meta": {"title": "target"}},
        "2": {"class_type": "LoadImage", "inputs": {"image": source}, "_meta": {"title": "her face"}},
        "3": {"class_type": "ReActorFaceSwap",
              "inputs": {"enabled": True, "input_image": ["1", 0], "source_image": ["2", 0],
                         "swap_model": "inswapper_128.onnx", "facedetection": "retinaface_resnet50",
                         "face_restore_model": "codeformer-v0.1.0.pth", "face_restore_visibility": 1.0,
                         "codeformer_weight": 0.5, "detect_gender_input": "no",
                         "detect_gender_source": "no", "input_faces_index": "0",
                         "source_faces_index": "0", "console_log_level": 1},
              "_meta": {"title": "face swap"}},
        "4": {"class_type": "SaveImage", "inputs": {"images": ["3", 0], "filename_prefix": "char/swap"}},
    }


def klein_reference_graph(face: str, seed: int, prompt: str, steps: int = 4) -> dict:
    g = klein(unet="flux-2-klein-4b-fp8.safetensors", prompt=prompt, negative=NEGATIVE,
              width=W, height=H, seed=seed, steps=steps, cfg=1.0, prefix="char/ref")
    g["20"] = {"class_type": "LoadImage", "inputs": {"image": face}, "_meta": {"title": "her face"}}
    g["21"] = {"class_type": "ImageScaleToTotalPixels",
               "inputs": {"image": ["20", 0], "upscale_method": "lanczos", "megapixels": 1.0,
                          "resolution_steps": 1}, "_meta": {"title": "to 1MP"}}
    g["22"] = {"class_type": "VAEEncode", "inputs": {"pixels": ["21", 0], "vae": ["3", 0]},
               "_meta": {"title": "encode"}}
    g["23"] = {"class_type": "ReferenceLatent", "inputs": {"conditioning": ["4", 0], "latent": ["22", 0]},
               "_meta": {"title": "reference latent"}}
    g["10"]["inputs"]["positive"] = ["23", 0]
    g["5"]["inputs"]["conditioning"] = ["23", 0]
    return g


def face_fraction(path: Path) -> float | None:
    """Face box over frame area - the witness that the shot size actually happened."""
    detected = faces_in(path)
    if not detected:
        return None
    try:
        from PIL import Image
        with Image.open(path) as handle:
            frame = float(handle.width * handle.height)
    except Exception:
        return None
    x1, y1, x2, y2 = detected[0].bbox
    return round(float(abs((x2 - x1) * (y2 - y1)) / frame), 5) if frame else None


def score(paths: list[Path], anchor: Path) -> dict[str, dict]:
    """ArcFace cosine against the anchor, with the face fraction beside it.

    Both numbers, always. A cosine read off a frame where the face is a handful
    of pixels is noise that looks exactly like a measurement, and reporting it
    bare is how a whole afternoon got spent on a wrong answer (DECISIONS #40).
    """
    vectors = face_embeddings([anchor] + paths)
    ref = vectors[0]
    out: dict[str, dict] = {}
    for path, vec in zip(paths, vectors[1:]):
        frac = face_fraction(path)
        cosine = None if (ref is None or vec is None) else round(float(np.dot(ref, vec)), 3)
        out[path.stem] = {
            "identity": cosine,
            "face_fraction": frac,
            "measurable": bool(frac is not None and frac >= MEASURABLE_FACE_FRACTION),
        }
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--project", default="projects/burningman")
    ap.add_argument("--out", default="projects/burningman/model-bench")
    ap.add_argument("--seed", type=int, default=7777)
    ap.add_argument("--stage", default="all", choices=["all", "models", "identity", "score"])
    ap.add_argument("--framing", default="closeup", choices=sorted(FRAMINGS))
    args = ap.parse_args()

    prompt = f"{SUBJECT}. {FRAMINGS[args.framing]}"
    out = Path(args.out) if args.framing == "closeup" else Path(f"{args.out}-{args.framing}")
    out.mkdir(parents=True, exist_ok=True)
    anchor = Path(args.project) / "anchor" / "anchor.png"
    anchor_face = Path(args.project) / "anchor" / "anchor_face.png"
    staged = "char_anchor_face.png"
    if anchor_face.is_file():
        shutil.copy2(anchor_face, COMFY_INPUT / staged)

    results: list[dict] = []
    common = dict(prompt=prompt, negative=NEGATIVE, width=W, height=H)

    if args.stage in ("all", "models"):
        pool = sorted(MODELS, key=lambda m: (bool(m.get("heavy")), m["family"]))
        print(f"PASS A - her description across {len(pool)} models\n")
        for i, spec in enumerate(pool, 1):
            dest = out / f"{spec['key']}.png"
            if dest.is_file():
                print(f"[{i:2}/{len(pool)}] {spec['label']:38} already rendered")
                results.append({"key": spec["key"], "label": spec["label"],
                                "family": spec["family"], "mode": "prompt only"})
                continue
            if spec.get("heavy"):
                flush()
            g = build(spec, seed=args.seed + i, prefix=f"char/{spec['key']}", **common)
            print(f"[{i:2}/{len(pool)}] {spec['label']:38} {spec['family']}")
            secs = submit(g, dest)
            print(f"    {'FAILED' if secs is None else f'{secs:7.1f}s'}")
            results.append({"key": spec["key"], "label": spec["label"], "family": spec["family"],
                            "seconds": secs, "mode": "prompt only"})

    if args.stage in ("all", "identity") and anchor_face.is_file():
        print("\nPASS B - identity mechanisms\n")
        jobs: list[tuple[str, str, dict]] = []
        # her trained LoRA on the SDXL it was trained against
        jobs.append(("id_lora_sdxl", "her LoRA on juggernautXL (UNet-only, weak by design)",
                     sdxl(ckpt="juggernautXL_ragnarok.safetensors", seed=args.seed + 101,
                          steps=30, cfg=4.5, sampler="dpmpp_2m_sde", scheduler="karras",
                          loras=((HER_LORA, 0.9),), prefix="char/lora", **common)))
        # reference conditioning, identity fed in before generation
        jobs.append(("id_klein_reference", "Klein reference latent (identity in)",
                     klein_reference_graph(staged, args.seed + 102, prompt=prompt)))
        for key, label, graph in jobs:
            dest = out / f"{key}.png"
            print(f"  {label}")
            secs = submit(graph, dest)
            print(f"    {'FAILED' if secs is None else f'{secs:7.1f}s'}")
            results.append({"key": key, "label": label, "family": "identity",
                            "seconds": secs, "mode": "conditioned"})
        # face swap, applied onto the three best pictures from pass A
        prior = json.loads((out / "results.json").read_text(encoding="utf-8")) if (out / "results.json").is_file() else []
        base_keys = [r["key"] for r in results if r.get("mode") == "prompt only"][:0] or []
        for key in ("zImageTurbo", "klein_distilled", "juggernautXL_ragnarok"):
            src = out / f"{key}.png"
            if not src.is_file():
                continue
            staged_target = f"char_target_{key}.png"
            shutil.copy2(src, COMFY_INPUT / staged_target)
            dest = out / f"id_swap_{key}.png"
            print(f"  ReActor swap onto {key}")
            secs = submit(faceswap_graph(staged_target, staged), dest)
            print(f"    {'FAILED' if secs is None else f'{secs:7.1f}s'}")
            results.append({"key": f"id_swap_{key}", "label": f"face swap onto {key}",
                            "family": "identity", "seconds": secs, "mode": "swapped"})

    # ---- score everything against the anchor ------------------------------
    existing = sorted(p for p in out.glob("*.png"))
    scores = score(existing, anchor) if anchor.is_file() else {}
    merged: dict[str, dict] = {}
    if (out / "results.json").is_file():
        for r in json.loads((out / "results.json").read_text(encoding="utf-8")):
            merged[r["key"]] = r
    for r in results:
        merged[r["key"]] = {**merged.get(r["key"], {}), **r}
    for key, entry in merged.items():
        entry.update(scores.get(key) or {"identity": None, "face_fraction": None, "measurable": False})
    rows = list(merged.values())
    (out / "results.json").write_text(json.dumps(rows, indent=1), encoding="utf-8")

    trusted = [r for r in rows if r.get("measurable") and r.get("identity") is not None]
    untrusted = [r for r in rows if r.get("identity") is not None and not r.get("measurable")]
    trusted.sort(key=lambda r: -r["identity"])
    print(f"\nIdentity vs anchor - {len(trusted)} measurable, "
          f"{len(untrusted)} with a face too small to trust\n")
    for r in trusted:
        print(f"  {r['identity']:.3f}  face {r['face_fraction'] * 100:5.2f}%  "
              f"{r.get('mode', '?'):12} {r['label']}")
    if untrusted:
        print(f"\n  NOT TRUSTWORTHY - face under {MEASURABLE_FACE_FRACTION * 100:g}% "
              "of frame, the cosine is noise:")
        for r in sorted(untrusted, key=lambda r: -(r["face_fraction"] or 0)):
            print(f"    ({r['identity']:.3f}) face {r['face_fraction'] * 100:5.2f}%  {r['label']}")
    nofaces = [r["label"] for r in rows if r.get("identity") is None]
    if nofaces:
        print(f"\n  no face detected at all: {', '.join(nofaces)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
