"""Fetch the Wan 2.2 text-to-video weights that were never downloaded.

    python scripts/fetch_wan_t2v.py            # download what is missing
    python scripts/fetch_wan_t2v.py --check    # report only, download nothing

`tools/_comfyui/workflows/wan22-t2v-4step.json` has shipped in this repo the
whole time and has never been runnable: both 14B noise stages and both 4-step
LoRAs are absent from the shared model tree. The workflow names them, ComfyUI
lists an empty dropdown, and nothing says why - the same shape as the MSR LoRA
trap in `HANDOFF.md`.

Resumable and safe to re-run. Completion is decided by comparing the local file
against the server's `Content-Length`, never by a marker file - the installer's
marker convention is what made five finished downloads report as partial
(`HANDOFF.md`, Traps).
"""

from __future__ import annotations

import argparse
import subprocess
import sys
import urllib.request
from pathlib import Path

SHARED = Path(r"C:\Users\Barrul\AppData\Local\Comfy-Desktop\ComfyUI-Shared\models")
BASE = ("https://huggingface.co/Comfy-Org/Wan_2.2_ComfyUI_Repackaged/"
        "resolve/main/split_files")

FILES = [
    ("diffusion_models", "wan2.2_t2v_high_noise_14B_fp8_scaled.safetensors",
     f"{BASE}/diffusion_models/wan2.2_t2v_high_noise_14B_fp8_scaled.safetensors"),
    ("diffusion_models", "wan2.2_t2v_low_noise_14B_fp8_scaled.safetensors",
     f"{BASE}/diffusion_models/wan2.2_t2v_low_noise_14B_fp8_scaled.safetensors"),
    ("loras", "wan2.2_t2v_lightx2v_4steps_lora_v1.1_high_noise.safetensors",
     f"{BASE}/loras/wan2.2_t2v_lightx2v_4steps_lora_v1.1_high_noise.safetensors"),
    ("loras", "wan2.2_t2v_lightx2v_4steps_lora_v1.1_low_noise.safetensors",
     f"{BASE}/loras/wan2.2_t2v_lightx2v_4steps_lora_v1.1_low_noise.safetensors"),
]


def remote_size(url: str) -> int | None:
    try:
        req = urllib.request.Request(url, method="HEAD")
        with urllib.request.urlopen(req, timeout=60) as r:
            return int(r.headers.get("Content-Length") or 0) or None
    except Exception:
        return None


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--check", action="store_true")
    args = ap.parse_args()

    total = 0
    plan: list[tuple[Path, str, int]] = []
    for folder, name, url in FILES:
        dest = SHARED / folder / name
        want = remote_size(url)
        have = dest.stat().st_size if dest.exists() else 0
        if want and have == want:
            print(f"have  {name}  ({have/2**30:.2f} GiB)")
            continue
        state = "resume" if have else "fetch"
        print(f"{state:5} {name}  ({(want or 0)/2**30:.2f} GiB"
              + (f", {have/2**30:.2f} already" if have else "") + ")")
        plan.append((dest, url, want or 0))
        total += (want or 0) - have

    if not plan:
        print("\nnothing to do - all four present and byte-complete")
        return 0
    print(f"\n{len(plan)} file(s), {total/2**30:.1f} GiB to fetch")
    if args.check:
        return 0

    for dest, url, want in plan:
        dest.parent.mkdir(parents=True, exist_ok=True)
        print(f"\n-> {dest.name}", flush=True)
        # -C - resumes; on an already-complete file the server answers 416 and
        # curl exits 33, which is success for our purposes.
        rc = subprocess.run(
            ["curl", "-L", "-C", "-", "--retry", "5", "--retry-delay", "5",
             "-o", str(dest), url]).returncode
        have = dest.stat().st_size if dest.exists() else 0
        if want and have == want:
            print(f"   complete: {have} bytes == remote")
        elif rc == 33 and have:
            print(f"   already complete ({have} bytes); server refused the range")
        else:
            print(f"   INCOMPLETE: {have} of {want} bytes (curl exit {rc}) - re-run to resume")
            return 1
    print("\nall four present. Restart ComfyUI so the loaders pick them up.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
