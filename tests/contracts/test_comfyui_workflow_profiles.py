"""Contract tests for custom ComfyUI workflow binding profiles."""

from __future__ import annotations

import json

import pytest

from tools._comfyui.profiles import (
    WorkflowProfileError,
    apply_workflow_bindings,
    load_workflow_profile,
    validate_workflow_profile,
)


def _workflow():
    return {
        "10": {"class_type": "CLIPTextEncode", "inputs": {"text": "old"}},
        "11": {"class_type": "KSampler", "inputs": {"seed": 1}},
        "12": {"class_type": "CLIPTextEncode", "inputs": {"text": "old"}},
        "20": {
            "class_type": "SaveVideo",
            "inputs": {"filename_prefix": "video/original"},
        },
    }


def _profile():
    return {
        "version": 1,
        "name": "test-profile",
        "output_node": "20",
        "bindings": {
            "prompt": {"node": "10", "input": "text"},
            "seed": {"node": "11", "input": "seed"},
            "filename_prefix": {"node": "20", "input": "filename_prefix"},
            "multi_prompt": [
                {"node": "10", "input": "text"},
                {"node": "12", "input": "text"},
            ],
        },
    }


def test_load_workflow_profile(tmp_path):
    path = tmp_path / "profile.json"
    path.write_text(json.dumps(_profile()), encoding="utf-8")

    assert load_workflow_profile(path) == _profile()


def test_load_workflow_profile_rejects_invalid_json(tmp_path):
    path = tmp_path / "profile.json"
    path.write_text("{", encoding="utf-8")

    with pytest.raises(WorkflowProfileError, match="not valid JSON"):
        load_workflow_profile(path)


def test_validate_workflow_profile_accepts_compatible_graph():
    validate_workflow_profile(_workflow(), _profile())


def test_validate_workflow_profile_rejects_unsupported_version():
    profile = _profile()
    profile["version"] = 2

    with pytest.raises(WorkflowProfileError, match="Unsupported"):
        validate_workflow_profile(_workflow(), profile)


def test_validate_workflow_profile_rejects_missing_output_node():
    profile = _profile()
    profile["output_node"] = "999"

    with pytest.raises(WorkflowProfileError, match="missing output node"):
        validate_workflow_profile(_workflow(), profile)


def test_validate_workflow_profile_rejects_missing_binding_node():
    profile = _profile()
    profile["bindings"]["prompt"]["node"] = "999"

    with pytest.raises(WorkflowProfileError, match="missing node"):
        validate_workflow_profile(_workflow(), profile)


def test_validate_workflow_profile_rejects_missing_binding_input():
    profile = _profile()
    profile["bindings"]["prompt"]["input"] = "missing"

    with pytest.raises(WorkflowProfileError, match="missing input"):
        validate_workflow_profile(_workflow(), profile)


def test_apply_workflow_bindings_patches_supplied_values_only():
    workflow = _workflow()

    patched = apply_workflow_bindings(
        workflow,
        _profile(),
        {"prompt": "new", "seed": 42},
    )

    assert patched["10"]["inputs"]["text"] == "new"
    assert patched["11"]["inputs"]["seed"] == 42
    assert patched["20"]["inputs"]["filename_prefix"] == "video/original"


def test_apply_workflow_bindings_does_not_mutate_original():
    workflow = _workflow()

    patched = apply_workflow_bindings(workflow, _profile(), {"prompt": "new"})

    assert patched is not workflow
    assert patched["10"]["inputs"]["text"] == "new"
    assert workflow["10"]["inputs"]["text"] == "old"


def test_apply_workflow_bindings_supports_multi_target_binding():
    patched = apply_workflow_bindings(
        _workflow(), _profile(), {"multi_prompt": "same"}
    )

    assert patched["10"]["inputs"]["text"] == "same"
    assert patched["12"]["inputs"]["text"] == "same"


def test_invalid_multi_target_binding_fails_atomically():
    workflow = _workflow()
    profile = _profile()
    profile["bindings"]["multi_prompt"][1]["node"] = "999"

    with pytest.raises(WorkflowProfileError, match="missing node"):
        apply_workflow_bindings(workflow, profile, {"multi_prompt": "new"})

    assert workflow["10"]["inputs"]["text"] == "old"
    assert workflow["12"]["inputs"]["text"] == "old"


def test_apply_workflow_bindings_rejects_undeclared_value():
    with pytest.raises(WorkflowProfileError, match="no declared binding"):
        apply_workflow_bindings(_workflow(), _profile(), {"unknown": 1})
