"""Windows against WSL, AOTriton against CK, on the same GPU.

    python scripts/bench_suite.py --workflow image --port 8188 --label win-aotriton
    python scripts/bench_suite.py --workflow ltx   --port 8188 --label win-ck --runs 3
    python scripts/bench_suite.py --report

Measures what a render actually spends its time on, per phase, identically on
both servers. Phase boundaries come from ComfyUI's **websocket**, which emits an
`executing` event as each node starts - so timings are derived from the server's
own event stream rather than from a log file. That matters: the two platforms
log differently, and reading the wrong log is what produced three false
conclusions on 2026-08-29 (`wiki/vrgdg/video-render.md`).

Phases are attributed by node class:

    load     *Loader*, *LoaderKJ, UnetLoaderGGUF, CheckpointLoaderSimple
    sample   KSampler*, SamplerCustom*
    decode   VAEDecode*
    other    everything else

**The lever worth testing** is `TORCH_ROCM_FA_PREFER_CK=1`, which moves PyTorch
SDPA from AOTriton onto the CK Tile backend. AMD measured **+50% on Strix Halo
for I2V** with it, and it needs no package - unlike flash-attn, which has no
wheel for gfx1151 on either platform. AMD also measured SageAttention at
**-34% to -36%** on this hardware, so that route is closed.

Set it before the server starts; it cannot be changed per request.

Cold means the first run after a server start or a `/free`. Warm means the model
is already resident. Both are reported because they answer different questions:
cold is what a 37-shot batch pays per model swap, warm is the engine's real cost.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import statistics
import subprocess
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from lib.machine_paths import project_dir, repo_root, scratch_dir  # noqa: E402

REPO = repo_root()
# Set per run in main(); a module-level project would pin this to one film.
PROJECT: Path
OUT: Path
KEYFRAME: Path
SCRATCH = scratch_dir()

LOAD_HINTS = ("Loader", "loader")
SAMPLE_HINTS = ("KSampler", "SamplerCustom")
DECODE_HINTS = ("VAEDecode",)

WAN_NEG = ("色调艳丽,过曝,静态,细节模糊不清,字幕,风格,作品,画作,画面,静止,整体发灰,最差质量,"
           "低质量,JPEG压缩残留,丑陋的,残缺的,多余的手指,画得不好的手部,画得不好的脸部,畸形的,"
           "毁容的,形态畸形的肢体,手指融合,静止不动的画面,杂乱的背景,三条腿,背景人很多,倒着走")
SCENE_PROMPT = ("A dense crowd of people in modern festival clothing walks along a dusty "
                "desert street, bicycles among them, dust drifting in the low afternoon "
                "light. A woman with a bright red scarf walks with them. Locked-off "
                "camera, no camera movement, no zoom, no pan.")


# --------------------------------------------------------------- workflows --

def wf_image(seed: int, width: int, height: int) -> tuple[dict, str]:
    """SDXL through CheckpointLoaderSimple - core nodes only, runs on a bare install."""
    sys.path.insert(0, str(REPO / "workflows" / "image-bench"))
    from graphs import MODELS, build
    spec = next(m for m in MODELS if m["key"] == "juggernautXL_ragnarok")
    g = build(spec, prompt=SCENE_PROMPT, negative="blurry, low quality, watermark",
              width=width, height=height, seed=seed, prefix="bench_suite")
    return g, "7"


def upload_image(srv: str, path: Path) -> str:
    """Put the keyframe on this server and return the name ComfyUI knows it by.

    The shipped Wan workflow has `image: ""` - no input baked in - so without
    this the benchmark animates nothing. Uploading to each server separately
    also guarantees both platforms start from the *same pixels*, which is the
    whole point of a comparison.
    """
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


def wf_video(seed: int, frames: int, width: int, height: int = 640,
             image_name: str = "") -> tuple[dict, str]:
    """Wan 2.2 I2V 4-step - core nodes only, so it runs on both servers."""
    path = REPO / "tools" / "_comfyui" / "workflows" / "wan22-i2v-4step.json"
    g = json.loads(path.read_text(encoding="utf-8"))
    g["97"]["inputs"]["image"] = image_name
    g["93"]["inputs"]["text"] = SCENE_PROMPT
    g["89"]["inputs"]["text"] = WAN_NEG
    g["98"]["inputs"].update(length=frames, width=width, height=height)
    for n in ("85", "86"):
        g[n]["inputs"]["noise_seed"] = seed
    return g, "108"


def wf_ltx(seed: int, *_a) -> tuple[dict, str]:
    """The generator's own known-good LTX graph - the path with 15 finished clips.

    Windows only: needs comfyui-vrgamedevgirl, ComfyUI-GGUF, KJNodes and
    ComfyUI-LTXVideo, none of which are installed in WSL.
    """
    import glob
    files = glob.glob(str(SCRATCH / "ltx_known_good" / "i2v_scene_0005*.json"))
    if not files:
        raise SystemExit("generate the LTX workflow first (generate_vrgdg_i2v_workflows.ps1)")
    g = json.loads(Path(files[0]).read_text(encoding="utf-8"))
    if "736:449" in g:
        g["736:449"]["inputs"]["value"] = seed
    return g, None


def to_wsl_paths(graph: dict) -> tuple[dict, int]:
    r"""Rewrite Windows absolute paths to their /mnt/<drive>/ equivalents.

    The LTX graph is written by a PowerShell generator that bakes in absolute
    Windows paths for the project folder, the audio, the SRT and the image
    folder. WSL cannot open `C:\...`, and ComfyUI rejects the prompt at
    validation with `Invalid file path`.

    This is the migration cost in miniature: models can be copied, but every
    path our tooling hands to ComfyUI has to be translated per platform. Doing
    it here keeps the benchmark honest; doing it for production means the same
    translation inside `lib/vrgdg_bridge.py` and `tools/video/vrgdg_project_sync.py`.
    """
    import re
    drive = re.compile(r"^([A-Za-z]):[\\/]")
    n = 0

    # A model name can also be a Windows *relative* path with a backslash -
    # `LTX_8bit\ltx-...safetensors` - which Linux lists with a forward slash.
    # Absolute paths and model names therefore need separate handling.
    model_name = re.compile(r"\.(safetensors|gguf|pth|ckpt|onnx)$", re.I)

    def conv(v):
        nonlocal n
        if not isinstance(v, str):
            return v
        if drive.match(v):
            n += 1
            return drive.sub(lambda m: f"/mnt/{m.group(1).lower()}/", v).replace("\\", "/")
        if "\\" in v and model_name.search(v):
            n += 1
            return v.replace("\\", "/")
        return v

    out = json.loads(json.dumps(graph))
    for node in out.values():
        for k, v in (node.get("inputs") or {}).items():
            node["inputs"][k] = conv(v)
    return out, n


WORKFLOWS = {"image": wf_image, "video": wf_video, "ltx": wf_ltx}


# ------------------------------------------------------------- measurement --

def comfy_pid(port: int, force: str | None = None) -> tuple[str, int | None]:
    """(platform, pid). WSL is asked through wsl.exe; Windows through psutil.

    The port is only a *hint*. Comfy Desktop reassigns ports when it thinks one
    is busy, and a Windows instance turning up on 8189 would otherwise be
    measured as if it lived in Linux - wrong pid, wrong memory numbers, and
    pointless path translation. `--platform` overrides the guess.
    """
    if force in ("windows", "wsl"):
        if force == "wsl":
            port = 8189
        else:
            try:
                import psutil
                best = None
                for p in psutil.process_iter(["pid", "cmdline"]):
                    cl = " ".join(p.info.get("cmdline") or [])
                    if "main.py" in cl and "ComfyUI" in cl:
                        rss = p.memory_info().rss
                        if best is None or rss > best[1]:
                            best = (p.info["pid"], rss)
                return "windows", best[0] if best else None
            except Exception:
                return "windows", None
    if port == 8189:
        try:
            r = subprocess.run(["wsl.exe", "-d", "Ubuntu-24.04", "--", "bash", "-lc",
                                "pgrep -f 'main.py --listen' | head -1"],
                               capture_output=True, text=True, timeout=60)
            pid = r.stdout.strip().splitlines()[-1] if r.stdout.strip() else None
            return "wsl", int(pid) if pid and pid.isdigit() else None
        except Exception:
            return "wsl", None
    try:
        import psutil
        best = None
        for p in psutil.process_iter(["pid", "cmdline"]):
            cl = " ".join(p.info.get("cmdline") or [])
            if "main.py" in cl and "ComfyUI" in cl:
                rss = p.memory_info().rss
                if best is None or rss > best[1]:
                    best = (p.info["pid"], rss)
        return "windows", best[0] if best else None
    except Exception:
        return "windows", None


def peak_rss_gib(platform: str, pid: int | None) -> float | None:
    """Peak physical memory. VmHWM on Linux, PeakWorkingSet on Windows."""
    if pid is None:
        return None
    if platform == "wsl":
        try:
            r = subprocess.run(["wsl.exe", "-d", "Ubuntu-24.04", "--", "bash", "-lc",
                                f"grep VmHWM /proc/{pid}/status"],
                               capture_output=True, text=True, timeout=60)
            kb = int(r.stdout.split()[1])
            return round(kb / 2**20, 2)
        except Exception:
            return None
    try:
        import psutil
        m = psutil.Process(pid).memory_info()
        return round(getattr(m, "peak_wset", m.rss) / 2**30, 2)
    except Exception:
        return None


def vram(srv: str) -> dict:
    """GPU memory from ComfyUI itself. RSS cannot see it - the weights live on
    the device, which is why an earlier /free test reported releasing nothing."""
    try:
        d = (json.loads(urllib.request.urlopen(f"{srv}/system_stats", timeout=20).read())
             .get("devices") or [{}])[0]
        return {"vram_total_gib": round(d.get("vram_total", 0) / 2**30, 2),
                "vram_free_gib": round(d.get("vram_free", 0) / 2**30, 2),
                "torch_vram_used_gib": round(
                    (d.get("torch_vram_total", 0) - d.get("torch_vram_free", 0)) / 2**30, 2)}
    except Exception:
        return {}


def probe_output(path: Path | None) -> dict:
    """Output correctness: does it exist, and is it the shape we asked for."""
    if not path or not path.exists():
        return {"correct": False, "why": "no file"}
    try:
        r = subprocess.run(
            ["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries",
             "stream=width,height,nb_frames", "-of", "csv=p=0", str(path)],
            capture_output=True, text=True, timeout=120)
        parts = [x for x in r.stdout.strip().split(",") if x]
        out = {"bytes": path.stat().st_size, "correct": path.stat().st_size > 1024}
        if len(parts) >= 2:
            out["width"], out["height"] = int(parts[0]), int(parts[1])
        if len(parts) >= 3 and parts[2].isdigit():
            out["frames"] = int(parts[2])
        return out
    except Exception as exc:
        return {"correct": path.stat().st_size > 1024, "probe_error": str(exc)[:80]}


def rss_gib(platform: str, pid: int | None) -> float | None:
    if pid is None:
        return None
    if platform == "wsl":
        try:
            r = subprocess.run(["wsl.exe", "-d", "Ubuntu-24.04", "--", "bash", "-lc",
                                f"grep VmRSS /proc/{pid}/status"],
                               capture_output=True, text=True, timeout=60)
            return round(int(r.stdout.split()[1]) / 2**20, 2)
        except Exception:
            return None
    try:
        import psutil
        return round(psutil.Process(pid).memory_info().rss / 2**30, 2)
    except Exception:
        return None


async def submit_and_watch(srv: str, graph: dict, phases: dict, classes: dict) -> str | None:
    """Connect the websocket FIRST, then submit, then attribute time per node.

    Order matters. A fast render can finish before a listener attached after
    submission ever sees an event, and the harness then waits forever on a
    stream that will never speak - which is exactly what happened on the first
    image run.
    """
    import websockets
    cur, t0, prompt_id = None, None, None
    srv_ws = srv.replace("http://", "ws://")
    async with websockets.connect(f"{srv_ws}/ws?clientId=benchsuite", max_size=None) as ws:
        # client_id must match the websocket's, or execution events are not
        # routed to this socket and the listener waits on a silent stream.
        req = urllib.request.Request(
            f"{srv}/prompt",
            data=json.dumps({"prompt": graph, "client_id": "benchsuite"}).encode(),
            headers={"Content-Type": "application/json"})
        prompt_id = json.loads(urllib.request.urlopen(req, timeout=120).read())["prompt_id"]
        while True:
            try:
                raw = await asyncio.wait_for(ws.recv(), timeout=1800)
            except asyncio.TimeoutError:
                return prompt_id
            if isinstance(raw, bytes):
                continue
            msg = json.loads(raw)
            data = msg.get("data") or {}
            if data.get("prompt_id") not in (None, prompt_id):
                continue
            if msg.get("type") == "executing":
                now = time.time()
                if cur is not None and t0 is not None:
                    cls = classes.get(cur, "")
                    key = ("load" if any(h in cls for h in LOAD_HINTS)
                           else "sample" if any(h in cls for h in SAMPLE_HINTS)
                           else "decode" if any(h in cls for h in DECODE_HINTS)
                           else "other")
                    phases[key] = phases.get(key, 0.0) + (now - t0)
                node = data.get("node")
                if node is None:
                    return prompt_id
                cur, t0 = node, now


def run_once(srv: str, graph: dict, out_node: str | None, platform: str, pid: int | None,
             label: str, idx: int) -> dict:
    classes = {k: v.get("class_type", "") for k, v in graph.items()}
    before = rss_gib(platform, pid)
    vram_before = vram(srv)
    start = time.time()
    phases: dict[str, float] = {}
    try:
        prompt_id = asyncio.run(submit_and_watch(srv, graph, phases, classes))
    except urllib.error.HTTPError as exc:
        return {"run": idx, "ok": False, "error": exc.read().decode(errors="replace")[:300]}
    except Exception as exc:
        return {"run": idx, "ok": False, "error": f"{type(exc).__name__}: {exc}"[:300]}
    if prompt_id is None:
        return {"run": idx, "ok": False, "error": "no prompt id"}

    hist = {}
    while time.time() - start < 7200:
        try:
            hist = json.loads(urllib.request.urlopen(f"{srv}/history/{prompt_id}", timeout=60).read())
            if prompt_id in hist:
                break
        except Exception:
            pass
        time.sleep(2)
    entry = hist.get(prompt_id, {})
    elapsed = round(time.time() - start, 1)

    # Server-side end-to-end, independent of our polling.
    msgs = {m[0]: m[1] for m in (entry.get("status") or {}).get("messages", [])}
    server_s = None
    if "execution_start" in msgs and "execution_success" in msgs:
        server_s = round((msgs["execution_success"]["timestamp"]
                          - msgs["execution_start"]["timestamp"]) / 1000, 1)

    saved, meta = None, {}
    for node in (entry.get("outputs") or {}).values():
        for kind in ("videos", "gifs", "images"):
            for item in node.get(kind) or []:
                q = urllib.parse.urlencode({"filename": item["filename"],
                                            "subfolder": item.get("subfolder", ""),
                                            "type": item.get("type", "output")})
                dest = OUT / f"{label}_r{idx}{Path(item['filename']).suffix}"
                dest.write_bytes(urllib.request.urlopen(f"{srv}/view?{q}", timeout=900).read())
                saved = dest
                meta = {"bytes": dest.stat().st_size}
                break
            if saved:
                break
        if saved:
            break

    return {
        "run": idx,
        "ok": bool(saved),
        "status": (entry.get("status") or {}).get("status_str"),
        "end_to_end_s": elapsed,
        "server_s": server_s,
        "load_s": round(phases.get("load", 0), 1),
        "sample_s": round(phases.get("sample", 0), 1),
        "decode_s": round(phases.get("decode", 0), 1),
        "other_s": round(phases.get("other", 0), 1),
        "rss_before_gib": before,
        "rss_after_gib": rss_gib(platform, pid),
        "peak_rss_gib": peak_rss_gib(platform, pid),
        "vram_before": vram_before,
        "vram_after": vram(srv),
        "output": str(saved) if saved else None,
        "check": probe_output(saved),
        **meta,
    }


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--workflow", choices=sorted(WORKFLOWS), required=True)
    ap.add_argument("--port", type=int, default=8188)
    ap.add_argument("--label", required=True)
    ap.add_argument("--runs", type=int, default=3)
    ap.add_argument("--frames", type=int, default=81)
    ap.add_argument("--width", type=int, default=640)
    ap.add_argument("--height", type=int, default=640)
    ap.add_argument("--seed", type=int, default=6100)
    ap.add_argument("--no-free", action="store_true", help="skip the /free release test")
    ap.add_argument("--platform", choices=("windows", "wsl"), default=None,
                    help="override the platform guess; the port is only a hint")
    ap.add_argument("--project", default=None,
                    help="project id; defaults to OPENMONTAGE_PROJECT or the "
                         "most recently touched project")
    ap.add_argument("--keyframe", type=Path, default=None,
                    help="input image for the video workflows")
    args = ap.parse_args()

    global PROJECT, OUT, KEYFRAME
    PROJECT = project_dir(args.project)
    OUT = PROJECT / "scene_look" / "bench-suite"
    KEYFRAME = args.keyframe or (PROJECT / "scene_look" / "l3" / "01_flow-across.png")

    srv = f"http://127.0.0.1:{args.port}"
    OUT.mkdir(parents=True, exist_ok=True)
    platform, pid = comfy_pid(args.port, args.platform)
    print(f"{args.label}: {args.workflow} on {srv} ({platform}, pid {pid}), {args.runs} runs\n")

    image_name = ""
    if args.workflow == "video":
        image_name = upload_image(srv, KEYFRAME)
        print(f"  keyframe uploaded to this server as {image_name!r}\n")

    rows = []
    for i in range(1, args.runs + 1):
        if args.workflow == "video":
            graph, out_node = wf_video(args.seed + i, args.frames, args.width,
                                       args.height, image_name)
        elif args.workflow == "image":
            graph, out_node = wf_image(args.seed + i, args.width, args.height)
        else:
            graph, out_node = wf_ltx(args.seed + i)
        if platform == "wsl":
            graph, n = to_wsl_paths(graph)
            if i == 1 and n:
                print(f"  translated {n} Windows path(s) to /mnt for WSL")
        r = run_once(srv, graph, out_node, platform, pid, args.label, i)
        rows.append(r)
        # Append each run as it lands. A 3-run Wan benchmark is over an hour and
        # the harness has been killed mid-flight repeatedly; partial results on
        # disk are worth more than a complete set that never gets written.
        with (OUT / f"{args.label}_{args.workflow}.jsonl").open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(r) + "\n")
        state = "cold" if i == 1 else "warm"
        if r.get("ok"):
            print(f"  run {i} ({state:4}): {r['end_to_end_s']:7.1f}s  "
                  f"load {r['load_s']:6.1f}  sample {r['sample_s']:6.1f}  "
                  f"decode {r['decode_s']:5.1f}  peak {r['peak_rss_gib']} GiB")
        else:
            print(f"  run {i} ({state:4}): FAILED  {str(r.get('error') or r.get('status'))[:80]}")

    freed = None
    if not args.no_free:
        rss_pre = rss_gib(platform, pid)
        vram_pre = vram(srv)
        try:
            urllib.request.urlopen(urllib.request.Request(
                f"{srv}/free", data=json.dumps({"unload_models": True, "free_memory": True}).encode(),
                headers={"Content-Type": "application/json"}), timeout=180)
            time.sleep(8)
        except Exception:
            pass
        rss_post, vram_post = rss_gib(platform, pid), vram(srv)
        vpre = vram_pre.get("vram_free_gib", 0.0)
        vpost = vram_post.get("vram_free_gib", 0.0)
        freed = {
            "rss_before_free_gib": rss_pre, "rss_after_free_gib": rss_post,
            "vram_free_before_gib": vpre, "vram_free_after_gib": vpost,
            # Positive means /free handed memory back. RSS cannot see this at
            # all - the weights live on the device, not in the process.
            "vram_released_gib": round(vpost - vpre, 2),
        }
        print(f"\n  /free: VRAM free {vpre} -> {vpost} GiB "
              f"(released {freed['vram_released_gib']})")

    ok = [r for r in rows if r.get("ok")]
    warm = [r["end_to_end_s"] for r in ok[1:]]
    summary = {
        "label": args.label, "workflow": args.workflow, "port": args.port,
        "platform": platform, "runs": args.runs,
        "completed": len(ok), "stable": len(ok) == args.runs,
        "cold_s": ok[0]["end_to_end_s"] if ok else None,
        "warm_mean_s": round(statistics.mean(warm), 1) if warm else None,
        "sample_mean_s": round(statistics.mean([r["sample_s"] for r in ok[1:]]), 1) if len(ok) > 1 else None,
        "peak_rss_gib": max([r["peak_rss_gib"] for r in ok if r["peak_rss_gib"]], default=None),
        "free": freed, "runs_detail": rows,
    }
    dest = OUT / f"{args.label}_{args.workflow}.json"
    dest.write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(f"\n  stable over {args.runs} runs: {summary['stable']}")
    print(f"  written: {dest}")
    return 0 if summary["stable"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
