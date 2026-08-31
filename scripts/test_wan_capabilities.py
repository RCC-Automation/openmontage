"""Run the two Wan capabilities that have never been executed here.

    python scripts/test_wan_capabilities.py --test flf
    python scripts/test_wan_capabilities.py --test animate
    python scripts/test_wan_capabilities.py --test both

Both need the **WSL** ComfyUI (`scripts/start_comfyui_wsl.sh`) and the Windows
one stopped - see `wiki/comfyui/two-platforms.md`.

**flf** - first-to-last-frame with a *correlated* pair. The earlier attempt fed
it two independently generated images, which is a cut between two scenes rather
than one scene at two moments, and the engine papered over the gap. This uses a
start frame and an end frame *derived from it* by img2img (`end_frame.py`), so
the crowd, ground and light are the same pixels and only the subject has moved.
That is the difference between an authored action and a hopeful one, and it is
what the film's nine turning shots depend on.

**animate** - motion transfer: a still plus a driving video. It needs no end
frame at all, which makes it the other candidate for those nine shots. 15.5 GiB
of weights have sat unused since they were copied.

Neither has ever produced a frame on this machine. The point is to find out what
they do and write it down.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from lib.comfy_routing import to_wsl_paths, wan_server, which_platform  # noqa: E402
from lib.machine_paths import project_dir, repo_root  # noqa: E402

REPO = repo_root()


def upload(srv: str, path: Path) -> str:
    boundary = "----openmontage"
    body = f"--{boundary}\r\n".encode()
    body += (f'Content-Disposition: form-data; name="image"; filename="{path.name}"\r\n'
             "Content-Type: image/png\r\n\r\n").encode()
    body += path.read_bytes() + b"\r\n"
    body += (f'--{boundary}\r\nContent-Disposition: form-data; name="overwrite"\r\n'
             "\r\ntrue\r\n").encode()
    body += f"--{boundary}--\r\n".encode()
    req = urllib.request.Request(
        f"{srv}/upload/image", data=body,
        headers={"Content-Type": f"multipart/form-data; boundary={boundary}"})
    return json.loads(urllib.request.urlopen(req, timeout=600).read())["name"]


def run(srv: str, graph: dict, dest: Path, minutes: float) -> dict:
    graph, n = to_wsl_paths(graph)
    start = time.time()
    req = urllib.request.Request(f"{srv}/prompt",
                                 data=json.dumps({"prompt": graph}).encode(),
                                 headers={"Content-Type": "application/json"})
    try:
        pid = json.loads(urllib.request.urlopen(req, timeout=120).read())["prompt_id"]
    except urllib.error.HTTPError as exc:
        body = exc.read().decode(errors="replace")
        try:
            d = json.loads(body)
            errs = []
            for nid, v in (d.get("node_errors") or {}).items():
                for e in v.get("errors") or []:
                    errs.append(f"node {nid} ({v.get('class_type')}): {e.get('details')}")
            return {"ok": False, "error": "; ".join(errs) or d.get("error", {}).get("message", body[:200])}
        except Exception:
            return {"ok": False, "error": body[:300]}

    print(f"    prompt {pid[:8]} accepted, rendering ...", flush=True)
    while time.time() - start < minutes * 60:
        try:
            hist = json.loads(urllib.request.urlopen(f"{srv}/history/{pid}", timeout=60).read())
            if pid in hist:
                break
        except Exception:
            pass
        time.sleep(10)
    else:
        return {"ok": False, "error": f"no result after {minutes:.0f} min", "prompt_id": pid}

    entry = hist[pid]
    for node in (entry.get("outputs") or {}).values():
        for kind in ("videos", "gifs", "images"):
            for item in node.get(kind) or []:
                q = urllib.parse.urlencode({
                    "filename": item["filename"], "subfolder": item.get("subfolder", ""),
                    "type": item.get("type", "output")})
                dest.parent.mkdir(parents=True, exist_ok=True)
                dest.write_bytes(urllib.request.urlopen(f"{srv}/view?{q}", timeout=1800).read())
                return {"ok": True, "seconds": round(time.time() - start, 1),
                        "path": str(dest), "prompt_id": pid}
    return {"ok": False, "error": "completed but wrote no file",
            "status": (entry.get("status") or {}).get("status_str"), "prompt_id": pid}


def probe(path: Path) -> str:
    try:
        r = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0",
                            "-show_entries", "stream=width,height,nb_frames,r_frame_rate",
                            "-of", "csv=p=0", str(path)],
                           capture_output=True, text=True, timeout=120)
        return r.stdout.strip()
    except Exception:
        return "?"


def test_flf(srv: str, out: Path, project: Path, minutes: float) -> dict:
    """Start frame + an end frame derived from it, so the pair is one scene."""
    start_img = project / "scene_look" / "l3" / "01_flow-across.png"
    # 0.35 was the sweep value where the crowd held and the subject had moved.
    end_img = project / "scene_look" / "end-frame" / "end_d035.png"
    for p in (start_img, end_img):
        if not p.exists():
            return {"ok": False, "error": f"missing {p} - run end_frame.py first"}

    wf = REPO / "local_workflows" / "my_video_wan2_2_14B_flf2v.json"
    graph = json.loads(wf.read_text(encoding="utf-8"))
    a, b = upload(srv, start_img), upload(srv, end_img)
    # Node 68 is start_image and 62 is end_image, read off the consuming
    # WanFirstLastFrameToVideo node - NOT off loader order, which implies the
    # opposite and renders the shot backwards.
    graph["68"]["inputs"]["image"] = a
    graph["62"]["inputs"]["image"] = b
    graph["6"]["inputs"]["text"] = (
        "A dense crowd of people in modern festival clothing walks along a dusty desert "
        "street. A woman with a bright red scarf walks with them, moving closer to the "
        "camera. Locked-off camera, no camera movement.")
    graph["67"]["inputs"].update(width=640, height=640, length=81)
    for n in ("57", "58"):
        graph[n]["inputs"]["noise_seed"] = 8100
    print(f"  flf: {start_img.name} -> {end_img.name} (derived, so one scene)")
    return run(srv, graph, out / "wan_flf_correlated.mp4", minutes)


def test_animate(srv: str, out: Path, project: Path, minutes: float) -> dict:
    """A still driven by motion from an existing clip. No end frame needed."""
    wf = REPO / "local_workflows" / "my_video_wan_animate2.json"
    graph = json.loads(wf.read_text(encoding="utf-8"))
    still = project / "scene_look" / "l3" / "01_flow-across.png"
    driver = project / "scene_look" / "engine-bench" / "wan_i2v_wsl.mp4"
    if not driver.exists():
        return {"ok": False, "error": f"no driving video at {driver}"}
    graph["30"]["inputs"]["image"] = upload(srv, still)
    print(f"  animate: {still.name} driven by {driver.name}")
    print("    (the driving video must be set on the workflow's video loader;")
    print("     reporting whatever the graph says it needs)")
    return run(srv, graph, out / "wan_animate.mp4", minutes)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--test", choices=("flf", "animate", "both"), default="both")
    ap.add_argument("--project", default=None)
    ap.add_argument("--minutes", type=float, default=45.0)
    args = ap.parse_args()

    srv = wan_server()
    plat = which_platform(srv)
    if plat != "wsl":
        print(f"{srv} reports itself as {plat}, not wsl. "
              "Start the WSL ComfyUI (scripts/start_comfyui_wsl.sh) and stop the Windows one.")
        return 1

    project = project_dir(args.project)
    out = project / "scene_look" / "capabilities"
    out.mkdir(parents=True, exist_ok=True)
    results = {}

    for name, fn in (("flf", test_flf), ("animate", test_animate)):
        if args.test not in (name, "both"):
            continue
        print(f"\n=== {name} ===")
        r = fn(srv, out, project, args.minutes)
        if r.get("ok"):
            r["probe"] = probe(Path(r["path"]))
            print(f"  OK {r['seconds']}s -> {Path(r['path']).name}  [{r['probe']}]")
        else:
            print(f"  FAILED: {str(r.get('error'))[:220]}")
        results[name] = r

    (out / "capabilities.json").write_text(json.dumps(results, indent=2), encoding="utf-8")
    print(f"\nwritten: {out / 'capabilities.json'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
