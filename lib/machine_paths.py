"""Where things live on this machine, discovered rather than hard-coded.

Scripts kept spelling out `C:\\Users\\Barrul\\AppData\\Local\\Comfy-Desktop\\...`,
`/home/barrul/...` and `projects/the-man-watches/...`. That works on exactly one
machine, for exactly one film, until someone renames a folder.

Everything here is **discovered, with an environment override**, so a script can
say what it needs without knowing whose machine it is:

    from lib.machine_paths import repo_root, project_dir, comfy_models_dir

    OUT = project_dir("the-man-watches") / "scene_look"
    models = comfy_models_dir()

Overrides, all optional:

    OPENMONTAGE_PROJECT          default project id for `project_dir()`
    COMFYUI_INSTALL_DIR          the ComfyUI install (holds ComfyUI/main.py)
    COMFYUI_SHARED_DIR           the shared tree with models/, input/, output/
    COMFYUI_MODELS_DIR           the models tree, if it is not <shared>/models
    WSL_DISTRO                   default "Ubuntu-24.04"
    WSL_HOME                     default discovered from the distro
"""

from __future__ import annotations

import functools
import os
import subprocess
from pathlib import Path

__all__ = [
    "repo_root", "projects_root", "project_dir", "default_project",
    "comfy_install_dir", "comfy_shared_dir", "comfy_models_dir",
    "comfy_python", "wsl_distro", "wsl_home", "wsl_path", "scratch_dir",
]


# ------------------------------------------------------------------ repo --

@functools.lru_cache(maxsize=1)
def repo_root() -> Path:
    """Walk up from this file until a repo marker appears."""
    here = Path(__file__).resolve()
    for parent in [here.parent, *here.parents]:
        if (parent / "pipeline_defs").is_dir() and (parent / "lib").is_dir():
            return parent
    return here.parent.parent


def projects_root() -> Path:
    return repo_root() / "projects"


def default_project() -> str | None:
    """The project a script should act on when none is named.

    `OPENMONTAGE_PROJECT` first; otherwise the most recently modified project
    directory, which is almost always the one being worked on.
    """
    named = os.environ.get("OPENMONTAGE_PROJECT")
    if named:
        return named
    root = projects_root()
    if not root.is_dir():
        return None
    dirs = [d for d in root.iterdir() if d.is_dir() and not d.name.startswith("_")]
    if not dirs:
        return None
    return max(dirs, key=lambda d: d.stat().st_mtime).name


def project_dir(project: str | None = None) -> Path:
    """The workspace for *project*, or the default one."""
    name = project or default_project()
    if not name:
        raise RuntimeError(
            "No project given and none found under projects/. Pass one "
            "explicitly or set OPENMONTAGE_PROJECT."
        )
    return projects_root() / name


# --------------------------------------------------------------- ComfyUI --

def _first_existing(*candidates: Path | str | None) -> Path | None:
    for c in candidates:
        if not c:
            continue
        p = Path(c)
        if p.exists():
            return p
    return None


@functools.lru_cache(maxsize=1)
def comfy_install_dir() -> Path | None:
    """The directory containing `ComfyUI/main.py`."""
    env = os.environ.get("COMFYUI_INSTALL_DIR")
    if env:
        return Path(env)
    local = os.environ.get("LOCALAPPDATA")
    guesses = []
    if local:
        base = Path(local) / "Comfy-Desktop" / "ComfyUI-Installs"
        if base.is_dir():
            # Prefer a plain "ComfyUI"; otherwise the first install that has main.py.
            guesses.append(base / "ComfyUI")
            guesses.extend(sorted(d for d in base.iterdir() if d.is_dir()))
    for g in guesses:
        if (g / "ComfyUI" / "main.py").exists():
            return g
    return None


@functools.lru_cache(maxsize=1)
def comfy_shared_dir() -> Path | None:
    """The tree holding `models/`, `input/`, `output/`."""
    env = os.environ.get("COMFYUI_SHARED_DIR")
    if env:
        return Path(env)
    local = os.environ.get("LOCALAPPDATA")
    return _first_existing(Path(local) / "Comfy-Desktop" / "ComfyUI-Shared" if local else None)


def comfy_models_dir() -> Path | None:
    env = os.environ.get("COMFYUI_MODELS_DIR")
    if env:
        return Path(env)
    shared = comfy_shared_dir()
    return shared / "models" if shared else None


def comfy_python() -> Path | None:
    """The ComfyUI venv's interpreter - the one with torch, not ours."""
    install = comfy_install_dir()
    if not install:
        return None
    return _first_existing(
        install / "ComfyUI" / ".venv" / "Scripts" / "python.exe",   # Windows
        install / "ComfyUI" / ".venv" / "bin" / "python",           # Linux
    )


# ------------------------------------------------------------------- WSL --

def wsl_distro() -> str:
    return os.environ.get("WSL_DISTRO", "Ubuntu-24.04")


@functools.lru_cache(maxsize=1)
def wsl_home() -> str | None:
    """The WSL user's home, asked of the distro itself."""
    env = os.environ.get("WSL_HOME")
    if env:
        return env
    try:
        r = subprocess.run(["wsl.exe", "-d", wsl_distro(), "--", "bash", "-lc", "echo $HOME"],
                           capture_output=True, text=True, timeout=60)
        home = r.stdout.strip().splitlines()[-1].strip() if r.stdout.strip() else ""
        return home or None
    except Exception:
        return None


def wsl_path(win_path: Path | str) -> str:
    r"""`C:\a\b` -> `/mnt/c/a/b`. The translation WSL needs for any host path."""
    s = str(win_path)
    if len(s) > 2 and s[1] == ":" and s[2] in "\\/":
        return f"/mnt/{s[0].lower()}/" + s[3:].replace("\\", "/")
    return s.replace("\\", "/")


# --------------------------------------------------------------- scratch --

def scratch_dir(name: str = "openmontage") -> Path:
    """Somewhere to put working files that are not deliverables."""
    env = os.environ.get("OPENMONTAGE_SCRATCH")
    base = Path(env) if env else Path(os.environ.get("TEMP") or "/tmp")
    p = base / name
    p.mkdir(parents=True, exist_ok=True)
    return p
