"""Put the cast's face back into a rendered clip, and prove it worked.

    .venv/Scripts/python.exe scripts/swap_clip_faces.py --project the-man-watches --only sc05 sc11 sc18
    .venv/Scripts/python.exe scripts/swap_clip_faces.py --project the-man-watches --below 0.45
    .venv/Scripts/python.exe scripts/swap_clip_faces.py --project the-man-watches --only sc05 --dry-run

Why this stage exists
---------------------

Identity on this film was established on the hero **stills** - swapped with
ReActor, measured with ArcFace, all of them passed - and then never checked
again. Wan redraws the face during image-to-video, and measured on the finished
clips identity had collapsed:

    scene      still   clip
    sc31 CU     0.84    0.76   held
    sc16 MCU    0.79    0.54   held
    sc09 MCU    0.65    0.38   borderline
    sc18 MED    0.79    0.25   lost
    sc11 WIDE   0.76    0.20   lost
    sc05 MWIDE  0.69    0.11   lost
    sc08 MCU    0.48    0.09   lost

The pattern is shot size: the more pixels on her face, the more survives
generation. That is not something a better still can fix, because the still was
already right. Identity has to be re-applied **after** the video exists, which
is what this does.

What it will not fix
--------------------

A face that is not in frame. sc08 and sc09 are written as "head tilted back
looking straight up" and show the underside of a jaw; there is no face to swap
onto and no viewer could identify her either. Those need re-directing, not
swapping - the script says so rather than pretending.

The measurement is the point
----------------------------

Every clip is measured before and after against the same reference
`identity_check.json` used, so the numbers are comparable to the ones already on
record. **A swap that does not improve identity is discarded** and the original
kept. Without that this stage would be a way to make footage worse while
reporting success - the failure mode DECISIONS #37 is about.

`input_faces_index` picks which face in frame to replace. It defaults to the
largest, which in a crowd shot is often a bystander - that is exactly how sc07's
still scored *worse* after its swap (DECISIONS #47). It is a flag here because
in a crowd the right answer is per shot, and the before/after number will tell
you when you have chosen wrong.
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from lib.comfy_routing import upload_image  # noqa: E402
from lib.machine_paths import project_dir  # noqa: E402

#: ReActor lives on the Windows install. Wan renders on WSL, so a swap can run
#: beside a shoot without the two competing for the same weights.
SERVER = "http://127.0.0.1:8188"
FPS = 16
#: The reference identity_check.json measured against. Keeping it identical is
#: what makes a number here comparable to the ones already recorded.
REFERENCE = "scene_look/hair/06_polished.png"
FLOOR = 0.45


def measure(clip: Path, ref_embedding, app, samples: int = 6) -> dict:
    """Mean/best ArcFace similarity to the reference across sampled frames."""
    import cv2
    import numpy as np

    n = int(subprocess.run(
        ["ffprobe", "-v", "error", "-select_streams", "v:0", "-count_frames",
         "-show_entries", "stream=nb_read_frames", "-of", "csv=p=0", str(clip)],
        capture_output=True, text=True).stdout.strip() or 0)
    if not n:
        return {"frames": 0, "faces": 0, "mean": None, "best": None}
    idx = [int(i * (n - 1) / max(1, samples - 1)) for i in range(samples)]
    sims = []
    for i in idx:
        raw = subprocess.run(
            ["ffmpeg", "-v", "error", "-i", str(clip), "-vf", f"select=eq(n\\,{i})",
             "-frames:v", "1", "-f", "image2pipe", "-vcodec", "png", "-"],
            capture_output=True).stdout
        if not raw:
            continue
        img = cv2.imdecode(np.frombuffer(raw, np.uint8), cv2.IMREAD_COLOR)
        faces = app.get(img)
        if not faces:
            continue
        f = max(faces, key=lambda x: (x.bbox[2] - x.bbox[0]) * (x.bbox[3] - x.bbox[1]))
        sims.append(float(np.dot(ref_embedding, f.normed_embedding)))
    return {"frames": n, "faces": len(sims),
            "mean": round(sum(sims) / len(sims), 4) if sims else None,
            "best": round(max(sims), 4) if sims else None}


def swap_graph(clip: Path, ref_name: str, sid: str, faces_index: str,
               restore: str, visibility: float = 1.0) -> dict:
    """Frames in, face swapped on every one of them, video out.

    `format: "None"` on the loader matters: the default ("AnimateDiff") coerces
    rate and size to that model's expectations, which would silently resample a
    clip cut to a slot measured in frames.
    """
    return {
        "1": {"class_type": "VHS_LoadVideoPath", "inputs": {
            "video": str(clip), "force_rate": 0, "custom_width": 0,
            "custom_height": 0, "frame_load_cap": 0, "skip_first_frames": 0,
            "select_every_nth": 1, "format": "None"}},
        "2": {"class_type": "LoadImage", "inputs": {"image": ref_name}},
        "3": {"class_type": "ReActorFaceSwap", "inputs": {
            "enabled": True, "input_image": ["1", 0], "source_image": ["2", 0],
            "swap_model": "inswapper_128.onnx",
            "facedetection": "retinaface_resnet50",
            "face_restore_model": restore,
            "face_restore_visibility": visibility,
            "codeformer_weight": 0.5, "detect_gender_input": "no",
            "detect_gender_source": "no", "input_faces_index": faces_index,
            "source_faces_index": "0", "console_log_level": 1}},
        "4": {"class_type": "VHS_VideoCombine", "inputs": {
            "images": ["3", 0], "frame_rate": FPS, "loop_count": 0,
            "filename_prefix": f"swap/{sid}", "format": "video/h264-mp4",
            "pingpong": False, "save_output": True}},
    }


def run(server: str, graph: dict, dest: Path, minutes: float) -> dict:
    start = time.time()
    req = urllib.request.Request(f"{server}/prompt",
                                 data=json.dumps({"prompt": graph}).encode(),
                                 headers={"Content-Type": "application/json"})
    try:
        pid = json.loads(urllib.request.urlopen(req, timeout=120).read())["prompt_id"]
    except urllib.error.HTTPError as exc:
        body = exc.read().decode(errors="replace")
        try:
            d = json.loads(body)
            body = "; ".join(
                f"node {n} ({v.get('class_type')}): {e.get('details') or e.get('message')}"
                for n, v in (d.get("node_errors") or {}).items()
                for e in v.get("errors") or []) or body
        except Exception:
            pass
        return {"ok": False, "error": body[:300]}

    while time.time() - start < minutes * 60:
        try:
            hist = json.loads(urllib.request.urlopen(
                f"{server}/history/{pid}", timeout=60).read())
            if pid in hist:
                break
        except Exception:
            pass
        time.sleep(5)
    else:
        return {"ok": False, "error": f"still running after {minutes:.0f} min",
                "prompt_id": pid}

    # VHS_VideoCombine reports under "gifs" whatever the container actually is,
    # and SaveVideo reports video under "images" - so check every bucket rather
    # than the one that seems right (HANDOFF trap).
    for node in (hist[pid].get("outputs") or {}).values():
        for kind in ("gifs", "videos", "images"):
            for item in node.get(kind) or []:
                if not str(item.get("filename", "")).endswith(".mp4"):
                    continue
                q = urllib.parse.urlencode({
                    "filename": item["filename"],
                    "subfolder": item.get("subfolder", ""),
                    "type": item.get("type", "output")})
                dest.write_bytes(urllib.request.urlopen(
                    f"{server}/view?{q}", timeout=1800).read())
                return {"ok": True, "seconds": round(time.time() - start, 1),
                        "prompt_id": pid}
    return {"ok": False, "error": "finished but produced no mp4",
            "prompt_id": pid}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--project", default=None)
    ap.add_argument("--only", nargs="+", help="scene ids; default is every clip")
    ap.add_argument("--below", type=float, default=None,
                    help="only swap clips whose measured identity is under this")
    ap.add_argument("--server", default=SERVER)
    ap.add_argument("--reference", default=None)
    ap.add_argument("--faces-index", default="0",
                    help="which face in frame to replace, largest first. "
                         "In a crowd the largest is often a bystander")
    ap.add_argument("--restore", default="GPEN-BFR-512.onnx",
                    choices=("none", "codeformer-v0.1.0.pth", "GFPGANv1.3.pth",
                             "GFPGANv1.4.pth", "GPEN-BFR-512.onnx"),
                    help="face restorer. GPEN-BFR-512 is the one reported best "
                         "for faces turned away from camera, which most of a "
                         "film is")
    ap.add_argument("--visibility", type=float, default=0.75,
                    help="how much of the restored face to keep, 0.1-1.0. "
                         "A restorer invents detail independently on every "
                         "frame, so at 1.0 that invention flickers; 0.7-0.8 "
                         "keeps the detail and blends most of the shimmer away")
    ap.add_argument("--minutes", type=float, default=30.0)
    ap.add_argument("--keep-worse", action="store_true",
                    help="keep the swap even when it lowers identity")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    import cv2
    import insightface

    project = project_dir(args.project)
    plan = json.loads((project / "artifacts" / "scene_plan.json").read_text(encoding="utf-8"))
    video = project / "assets" / "video"
    keep = project / "scene_look"
    ref = Path(args.reference) if args.reference else project / REFERENCE
    if not ref.is_file():
        print(f"no reference image at {ref}")
        return 1

    ids = args.only or [s["id"] for s in plan["scenes"]]
    clips = [(sid, video / f"{sid}.mp4") for sid in ids
             if (video / f"{sid}.mp4").is_file()]
    if not clips:
        print("no clips to work on")
        return 1

    app = insightface.app.FaceAnalysis(name="buffalo_l",
                                       providers=["CPUExecutionProvider"])
    app.prepare(ctx_id=-1, det_size=(640, 640))
    ref_face = app.get(cv2.imread(str(ref)))
    if not ref_face:
        print(f"no face found in the reference {ref}")
        return 1
    ref_emb = ref_face[0].normed_embedding
    print(f"reference: {ref}\n")

    print(f"{'scene':6} {'before':>8} {'faces':>6}")
    todo = []
    for sid, clip in clips:
        m = measure(clip, ref_emb, app)
        flag = ""
        if not m["faces"]:
            flag = "  no face in frame - swapping cannot help, re-direct the shot"
        elif args.below is not None and (m["mean"] or 0) >= args.below:
            flag = "  above the floor, skipping"
        else:
            todo.append((sid, clip, m))
        print(f"{sid:6} {str(m['mean']):>8} {m['faces']:>6}{flag}")

    if not todo:
        print("\nnothing to swap")
        return 0
    print(f"\n{len(todo)} clip(s) to swap"
          + (" (dry run)" if args.dry_run else "") + "\n")
    if args.dry_run:
        return 0

    ref_name = upload_image(args.server, ref)
    ledger = project / "artifacts" / "shoot_log.jsonl"
    improved = worse = failed = 0

    for sid, clip, before in todo:
        print(f"  {sid} ({before['frames']}f) ...", end="", flush=True)
        tmp = video / f"{sid}.swap.mp4"
        r = run(args.server, swap_graph(clip, ref_name, sid, args.faces_index,
                                        args.restore, args.visibility),
                tmp, args.minutes)
        if not r.get("ok"):
            print(f" FAILED: {str(r.get('error'))[:100]}")
            tmp.unlink(missing_ok=True)
            failed += 1
            continue

        after = measure(tmp, ref_emb, app)
        gain = (after["mean"] or 0) - (before["mean"] or 0)
        better = gain > 0.02
        print(f" {r['seconds']}s  {before['mean']} -> {after['mean']}"
              f"  ({gain:+.3f})", end="")

        if better or args.keep_worse:
            shutil.copyfile(clip, keep / f"{sid}_before_swap.mp4")
            tmp.replace(clip)
            print("  kept" + ("" if better else "  (kept despite being worse)"))
            improved += 1
        else:
            tmp.unlink(missing_ok=True)
            print("  DISCARDED - no improvement, original kept")
            worse += 1

        with ledger.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps({
                "ok": True, "id": sid, "stage": "clip_face_swap",
                "engine": f"reactor inswapper_128 + {args.restore} @ {args.visibility}",
                "platform": "windows", "seconds": r.get("seconds"),
                "identity_before": before["mean"], "identity_after": after["mean"],
                "kept": bool(better or args.keep_worse),
                "input_faces_index": args.faces_index,
                "reference": str(ref.relative_to(project)),
            }) + "\n")

    print(f"\n{improved} improved, {worse} discarded, {failed} failed")
    return 0 if not failed else 1


if __name__ == "__main__":
    raise SystemExit(main())
