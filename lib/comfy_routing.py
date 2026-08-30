"""Which ComfyUI server a workflow belongs on, and the paths it needs there.

This machine runs two ComfyUI installs against one GPU, and the right one
depends on the *engine*, not the capability:

    Wan 2.2 / 2.1  ->  WSL     (33% faster warm; measured 2026-08-30)
    LTX, SDXL, VRGDG, face swap -> Windows  (2.5x faster on LTX, 19% on stills)

`ComfyUIClient` already resolves a server per *capability*
(`COMFYUI_VIDEO_SERVER_URL` and friends), but Wan and LTX are both "video", so
capability routing cannot express the split. This module routes per workflow.

Full numbers and the reasoning: `wiki/comfyui/two-platforms.md`.

**Never run both servers at once.** GPU memory is system RAM on this machine -
63.6 GiB total - and an idle WSL holding 41 GiB killed the Windows process
mid-load. :func:`assert_exclusive` is the guard.

Environment:

    COMFYUI_SERVER_URL       the Windows install   (default http://127.0.0.1:8188)
    COMFYUI_WAN_SERVER_URL   the WSL install       (default http://127.0.0.1:8189)
"""

from __future__ import annotations

import json
import os
import re
import urllib.request
from pathlib import Path
from typing import Any

__all__ = [
    "WAN_PATTERNS", "is_wan", "server_for", "wan_server", "windows_server",
    "target_is_wsl", "to_wsl_paths", "prepare", "assert_exclusive", "which_platform",
]

#: A workflow is a Wan workflow if its name matches any of these. Matching on
#: the name rather than a hand-kept list means a new `wan22-*.json` routes
#: correctly the day it is added, instead of silently running on Windows where
#: the weights no longer exist.
WAN_PATTERNS = (
    re.compile(r"wan[-_.]?\d", re.I),      # wan22-i2v-4step, wan2_2_14B_i2v
    re.compile(r"wan[-_]?animate", re.I),
    re.compile(r"scail", re.I),            # wan2.1 SCAIL character replacement
)

DEFAULT_WINDOWS = "http://127.0.0.1:8188"
DEFAULT_WAN = "http://127.0.0.1:8189"


def is_wan(workflow: str | Path) -> bool:
    """True when this workflow needs the WSL install."""
    name = Path(str(workflow)).name
    return any(p.search(name) for p in WAN_PATTERNS)


def windows_server() -> str:
    return (os.environ.get("COMFYUI_SERVER_URL") or DEFAULT_WINDOWS).rstrip("/")


def wan_server() -> str:
    return (os.environ.get("COMFYUI_WAN_SERVER_URL") or DEFAULT_WAN).rstrip("/")


def server_for(workflow: str | Path) -> str:
    """The server URL this workflow should be submitted to."""
    return wan_server() if is_wan(workflow) else windows_server()


def which_platform(server: str) -> str:
    """'windows' | 'wsl' | 'unknown', asked of the server itself.

    The port is only a hint: Comfy Desktop reassigns ports when it thinks one is
    busy, and a Windows instance can turn up on 8189. Reported `vram_total`
    distinguishes them - Windows sees 87.9 GiB, WSL 95.7 - because WSL's ROCm
    reports a larger share of the same unified memory.
    """
    try:
        with urllib.request.urlopen(f"{server}/system_stats", timeout=15) as r:
            d = (json.loads(r.read()).get("devices") or [{}])[0]
        gib = d.get("vram_total", 0) / 2 ** 30
        if gib > 92:
            return "wsl"
        if gib > 0:
            return "windows"
    except Exception:
        pass
    return "unknown"


def target_is_wsl(server: str) -> bool:
    return which_platform(server) == "wsl"


def to_wsl_paths(graph: dict[str, Any]) -> tuple[dict[str, Any], int]:
    r"""Rewrite a graph's Windows paths for a Linux ComfyUI. Returns (graph, n).

    Three incompatibilities, each failing differently:

    - **absolute paths** (``C:\Users\...``) - rejected at validation with
      "Invalid file path", so at least it is loud;
    - **model names with backslashes** (``LTX_8bit\ltx-...``), which Linux lists
      with forward slashes - this one is quiet, and a miss selects a *different*
      model rather than erroring;
    - model files that are simply absent on the target, which is a copy problem
      rather than a path one.

    Only the first two are fixable here.
    """
    drive = re.compile(r"^([A-Za-z]):[\\/]")
    model_name = re.compile(r"\.(safetensors|gguf|pth|ckpt|onnx)$", re.I)
    n = 0

    def conv(v: Any) -> Any:
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


def prepare(workflow: str | Path, graph: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    """Pick the server for *workflow* and adapt *graph* to it.

    The single call a caller needs::

        server, graph = prepare("wan22-i2v-4step.json", graph)
        submit(server, graph)
    """
    server = server_for(workflow)
    if target_is_wsl(server):
        graph, _ = to_wsl_paths(graph)
    return server, graph


def assert_exclusive(server: str) -> None:
    """Raise if the *other* ComfyUI is also up.

    Both running at once is not merely wasteful. On 2026-08-29 an idle WSL
    holding 41 GiB caused the Windows process to die with an access violation
    part-way through loading a 13.6 GB model, because GPU memory here is system
    RAM and 41 + 27 > 63.6.
    """
    other = windows_server() if server.rstrip("/") == wan_server() else wan_server()
    try:
        urllib.request.urlopen(f"{other}/system_stats", timeout=5)
    except Exception:
        return
    raise RuntimeError(
        f"Both ComfyUI servers are running ({server} and {other}). GPU memory is "
        "system RAM on this machine and running both has crashed the backend "
        "mid-load. Stop one first: 'wsl.exe --shutdown' for WSL, or quit Comfy "
        "Desktop for Windows. See wiki/comfyui/two-platforms.md."
    )
