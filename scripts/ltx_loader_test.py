"""Does LTX deadlock because of the GGUF, or regardless of it?

    python scripts/ltx_loader_test.py                 # int8 transformer
    python scripts/ltx_loader_test.py --loader gguf   # the control, expected to hang
    python scripts/ltx_loader_test.py --frames 25     # shorter still

LTX has hung three times on this machine, most recently at 640x640, 69 frames,
8 steps, with the upscale pass disabled - the smallest job it has been given.
The log signature is identical every time: both models report `loaded
completely`, and then nothing. **Sampling never starts.** No progress bar, no
error, no traceback.

Because the weights load fine, the dequantising loader is not obviously at
fault - but every hang so far has gone through `UnetLoaderGGUF` and the Q6_K
distilled file, and that is the only common factor we have. This changes exactly
that one node and leaves the other 58 alone.

    UnetLoaderGGUF(LTX-2.3-22B-distilled-1.1-Q6_K.gguf)
      -> DiffusionModelLoaderKJ(LTX_8bit/...dev_transformer_only_int8_convrot)

The graph is the one VRGDG built and we already pruned, submitted straight to
ComfyUI. So this also answers the second question - whether anything about
VRGDG's orchestration is involved - because VRGDG is not in the loop at all here.

**Two things this test deliberately does not care about.** The int8 file is the
*dev* model while the GGUF is the *distilled* one, so an 8-step distilled sigma
schedule is wrong for it and the picture may be poor. And the swap drops
whatever the GGUF loader was doing about dtype. Neither matters: the question is
whether the sampler produces a single step, not whether the frame is good.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from lib.comfy_routing import windows_server  # noqa: E402
from lib.machine_paths import comfy_install_dir, project_dir, repo_root  # noqa: E402

REPO = repo_root()
SRV = windows_server()
GRAPH: Path                     # set in main()
OUT: Path

#: The wrapper log, not ComfyUI/user/comfyui.log - only the wrapper carries the
#: per-step progress bar this test looks for.
_install = comfy_install_dir()
LOG = (_install / "logs" / "comfyui.log") if _install else Path("comfyui.log")

INT8 = "LTX_8bit" + "\\" + "ltx-2.3-22b-dev_transformer_only_int8_convrot.safetensors"


def swap_loader(graph: dict, loader: str) -> tuple[dict, str | None]:
    """Replace the GGUF UNet loader in place, keeping its node id and edges."""
    if loader == "gguf":
        return graph, None
    target = next((k for k, v in graph.items()
                   if v.get("class_type") == "UnetLoaderGGUF"), None)
    if target is None:
        return graph, None
    graph[target] = {
        "class_type": "DiffusionModelLoaderKJ",
        "inputs": {
            "model_name": INT8,
            "weight_dtype": "default",
            "compute_dtype": "bf16",
            "patch_cublaslinear": False,
            # No SageAttention on ROCm - offering it is a CUDA assumption in the
            # node, not a capability here (wiki/comfyui/this-machine.md).
            "sage_attention": "disabled",
            "enable_fp16_accumulation": False,
        },
        "_meta": {"title": "LTX int8 transformer"},
    }
    return graph, target


def log_size() -> int:
    try:
        return LOG.stat().st_size
    except OSError:
        return 0


def log_since(offset: int) -> str:
    try:
        with LOG.open("rb") as f:
            f.seek(offset)
            return f.read().decode("utf-8", "replace")
    except OSError:
        return ""


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--loader", choices=("int8", "gguf"), default="int8")
    ap.add_argument("--frames", type=int, default=None, help="override the latent length")
    ap.add_argument("--minutes", type=float, default=25.0, help="give up after this long")
    ap.add_argument("--project", default=None, help="project id for the graph and outputs")
    args = ap.parse_args()

    global GRAPH, OUT
    OUT = project_dir(args.project) / "scene_look" / "engine-bench"
    GRAPH = OUT / "ltx_graph.json"

    if not GRAPH.exists():
        raise SystemExit(f"missing {GRAPH} - run bench_ltx.py once to capture the graph")
    graph = json.loads(GRAPH.read_text(encoding="utf-8"))

    graph, swapped = swap_loader(graph, args.loader)
    print(f"loader: {args.loader}" + (f" (node {swapped} replaced)" if swapped else ""))

    if args.frames:
        for k, v in graph.items():
            if v.get("class_type") == "PrimitiveInt" and v["inputs"].get("value") == 69:
                v["inputs"]["value"] = args.frames
                print(f"  frames 69 -> {args.frames} (node {k})")

    (OUT / f"ltx_graph_{args.loader}.json").write_text(json.dumps(graph, indent=1), encoding="utf-8")

    mark = log_size()
    start = time.time()
    req = urllib.request.Request(f"{SRV}/prompt", data=json.dumps({"prompt": graph}).encode(),
                                 headers={"Content-Type": "application/json"})
    try:
        pid = json.loads(urllib.request.urlopen(req, timeout=120).read())["prompt_id"]
    except urllib.error.HTTPError as exc:
        print("REJECTED:", exc.read().decode(errors="replace")[:800])
        return 1
    print(f"submitted {pid[:8]}, watching the log for a sampler step ...\n")

    sampling_seen = False
    deadline = start + args.minutes * 60
    while time.time() < deadline:
        tail = log_since(mark)
        # A progress bar, or any per-step line, is proof the sampler is alive.
        if not sampling_seen and re.search(r"\d+%\|| it/s|s/it", tail):
            sampling_seen = True
            print(f"  SAMPLING STARTED at {time.time()-start:.0f}s "
                  "-- this is what has never happened before")
        try:
            hist = json.loads(urllib.request.urlopen(f"{SRV}/history/{pid}", timeout=60).read())
            if pid in hist:
                break
        except Exception:
            pass
        time.sleep(5)
    else:
        print(f"\nNO RESULT after {args.minutes:.0f} min. sampling_started={sampling_seen}")
        print("Clearing with /free (interrupt does not reach a deadlocked job).")
        urllib.request.urlopen(urllib.request.Request(
            f"{SRV}/free", data=json.dumps({"unload_models": True, "free_memory": True}).encode(),
            headers={"Content-Type": "application/json"}), timeout=120)
        print("\n--- log since submit ---")
        print(log_since(mark)[-2500:])
        return 1

    elapsed = round(time.time() - start, 1)
    saved = None
    for node in (hist[pid].get("outputs") or {}).values():
        for kind in ("videos", "gifs", "images"):
            for item in node.get(kind) or []:
                q = urllib.parse.urlencode({
                    "filename": item["filename"], "subfolder": item.get("subfolder", ""),
                    "type": item.get("type", "output")})
                dest = OUT / f"ltx_{args.loader}{Path(item['filename']).suffix}"
                dest.write_bytes(urllib.request.urlopen(f"{SRV}/view?{q}", timeout=900).read())
                saved = dest
                break
            if saved:
                break
        if saved:
            break

    print(f"\nLTX {args.loader}: {elapsed}s ({elapsed/60:.1f} min), "
          f"sampling_started={sampling_seen} -> {saved}")
    (OUT / f"ltx_{args.loader}.json").write_text(json.dumps({
        "loader": args.loader, "seconds": elapsed, "sampling_started": sampling_seen,
        "path": str(saved) if saved else None, "prompt_id": pid}, indent=2), encoding="utf-8")
    return 0 if saved else 1


if __name__ == "__main__":
    raise SystemExit(main())
