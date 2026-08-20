from __future__ import annotations

import json
from pathlib import Path

import pytest

from tools.audio.comfyui_tts import ComfyUITTS
from tools.base_tool import ToolStatus


class FakeClient:
    def __init__(self, output: Path):
        self.output = output
        self.workflow = None
        self.output_node = None
        self.uploaded = None

    def is_available(self):
        return True

    def upload_input(self, path, name):
        self.uploaded = (Path(path), name)
        return name

    def generate(self, workflow, output_node, dest, **kwargs):
        self.workflow = workflow
        self.output_node = output_node
        dest = Path(dest)
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(b"ID3")
        return [dest]


@pytest.mark.parametrize(
    ("mode", "output_node", "text_node", "text_input"),
    [
        ("voice_design", "56", "60", "text"),
        ("custom_voice", "57", "61", "text"),
        ("voice_clone", "58", "59", "target_text"),
    ],
)
def test_qwen_modes_bind_text_and_output(tmp_path, mode, output_node, text_node, text_input):
    tool = ComfyUITTS()
    fake = FakeClient(tmp_path / "unused.mp3")
    tool._client = fake
    inputs = {
        "text": "OpenMontage local narration",
        "mode": mode,
        "output_path": str(tmp_path / f"{mode}.mp3"),
        "seed": 42,
    }
    if mode == "voice_clone":
        ref = tmp_path / "reference.wav"
        ref.write_bytes(b"RIFF")
        inputs["reference_audio_path"] = str(ref)

    result = tool.execute(inputs)

    assert result.success, result.error
    assert fake.output_node == output_node
    assert fake.workflow[text_node]["inputs"][text_input] == inputs["text"]
    assert result.data["mode"] == mode


def test_voice_clone_uploads_and_binds_reference_audio(tmp_path):
    ref = tmp_path / "voice.m4a"
    ref.write_bytes(b"audio")
    tool = ComfyUITTS()
    fake = FakeClient(tmp_path / "unused.mp3")
    tool._client = fake

    result = tool.execute({
        "text": "Clone test",
        "mode": "voice_clone",
        "reference_audio_path": str(ref),
        "output_path": str(tmp_path / "clone.mp3"),
        "seed": 7,
    })

    assert result.success, result.error
    assert fake.uploaded[0] == ref
    assert fake.workflow["62"]["inputs"]["audio"] == fake.uploaded[1]


def test_voice_clone_requires_reference_audio(monkeypatch):
    tool = ComfyUITTS()
    monkeypatch.setattr(tool._client, "is_available", lambda: True)
    result = tool.execute({"text": "Missing reference", "mode": "voice_clone"})
    assert not result.success
    assert "reference_audio_path" in result.error


def test_registry_discovers_comfyui_tts():
    from tools.tool_registry import ToolRegistry

    registry = ToolRegistry()
    registry.discover()
    tool = registry.get("comfyui_tts")

    assert tool is not None
    assert tool.capability == "tts"
    assert tool.provider == "comfyui"
