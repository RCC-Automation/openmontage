"""Wan goes to WSL, everything else stays on Windows.

The split is measured, not stylistic (`wiki/comfyui/two-platforms.md`): Wan 2.2
I2V is 33% faster warm in WSL, LTX is 2.5x faster on Windows, and since
2026-08-30 the Wan weights exist *only* in WSL. A workflow routed to the wrong
server fails by finding an empty model dropdown - no error, no explanation -
which is exactly the failure mode `HANDOFF.md` records for the missing MSR LoRA.

These tests exist so that failure cannot be introduced quietly.
"""

from __future__ import annotations

import json

import pytest

from lib.comfy_routing import (
    is_wan, prepare, server_for, to_wsl_paths, wan_server, windows_server,
)


@pytest.mark.parametrize("name", [
    "wan22-i2v-4step.json",
    "wan22-t2v-4step.json",
    "my_video_wan2_2_14B_i2v.json",
    "my_video_wan2_2_14B_flf2v.json",
    "my_video_wan_animate2.json",
    "my_video_wan21_scail2_character_replacement.json",
    "wan2.2_something_new.json",          # a file nobody has written yet
])
def test_wan_workflows_route_to_wsl(name):
    assert is_wan(name)
    assert server_for(name) == wan_server()


@pytest.mark.parametrize("name", [
    "juggernaut-xl-ragnarok-txt2img.json",
    "flux2-txt2img.json",
    "ace-step-1.5-turbo-aio-t2a.json",
    "i2v_scene_0005_mara-prepares_tiled.json",   # LTX through the VRGDG generator
    "qwen3-tts-voice-clone.json",
])
def test_everything_else_stays_on_windows(name):
    assert not is_wan(name)
    assert server_for(name) == windows_server()


def test_full_paths_route_the_same_as_bare_names():
    """Callers pass whatever they have - a path must not change the decision."""
    assert is_wan(r"C:\repo\tools\_comfyui\workflows\wan22-i2v-4step.json")
    assert is_wan("/mnt/c/repo/local_workflows/my_video_wan_animate2.json")


def test_absolute_windows_paths_become_mnt():
    graph = {"1": {"class_type": "LoadAudio",
                   "inputs": {"audio_file": r"C:\Users\Barrul\project\audio.mp3"}}}
    out, n = to_wsl_paths(graph)
    assert n == 1
    assert out["1"]["inputs"]["audio_file"] == "/mnt/c/Users/Barrul/project/audio.mp3"


def test_model_names_with_backslashes_are_converted():
    """The quiet one: a miss selects a different model instead of erroring."""
    graph = {"1": {"class_type": "DiffusionModelLoaderKJ",
                   "inputs": {"model_name": r"LTX_8bit\ltx-2.3-22b-dev.safetensors"}}}
    out, n = to_wsl_paths(graph)
    assert n == 1
    assert out["1"]["inputs"]["model_name"] == "LTX_8bit/ltx-2.3-22b-dev.safetensors"


def test_plain_values_are_left_alone():
    """Prompts contain colons and slashes; none of that is a path."""
    graph = {"1": {"class_type": "CLIPTextEncode",
                   "inputs": {"text": "a 16:9 shot, low light", "seed": 42,
                              "model_name": "juggernautXL_ragnarok.safetensors"}}}
    out, n = to_wsl_paths(graph)
    assert n == 0
    assert out == graph


def test_translation_does_not_mutate_the_caller_s_graph():
    graph = {"1": {"class_type": "LoadImage", "inputs": {"image": r"C:\x\y.png"}}}
    original = json.dumps(graph, sort_keys=True)
    to_wsl_paths(graph)
    assert json.dumps(graph, sort_keys=True) == original


def test_prepare_leaves_a_windows_bound_graph_untouched(monkeypatch):
    """A Windows workflow must never be path-translated."""
    monkeypatch.setattr("lib.comfy_routing.target_is_wsl", lambda _s: False)
    graph = {"1": {"class_type": "LoadImage", "inputs": {"image": r"C:\x\y.png"}}}
    server, out = prepare("juggernaut-xl-ragnarok-txt2img.json", graph)
    assert server == windows_server()
    assert out["1"]["inputs"]["image"] == r"C:\x\y.png"


def test_prepare_translates_for_a_wan_workflow(monkeypatch):
    monkeypatch.setattr("lib.comfy_routing.target_is_wsl", lambda _s: True)
    graph = {"1": {"class_type": "LoadImage", "inputs": {"image": r"C:\x\y.png"}}}
    server, out = prepare("wan22-i2v-4step.json", graph)
    assert server == wan_server()
    assert out["1"]["inputs"]["image"] == "/mnt/c/x/y.png"


def test_the_two_servers_are_different():
    """A single URL for both would silently send Wan to Windows, where the
    weights no longer exist."""
    assert windows_server() != wan_server()
