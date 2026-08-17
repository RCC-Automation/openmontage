"""Load, validate, and apply bindings for custom ComfyUI workflows.

A workflow profile keeps user-facing OpenMontage inputs separate from the
node IDs used by a particular API-format ComfyUI graph. Profiles may bind one
logical value to one target or to several targets, which is required by
multi-pass workflows.
"""

from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any, Mapping


SUPPORTED_PROFILE_VERSION = 1


class WorkflowProfileError(ValueError):
    """Raised when a workflow profile is malformed or incompatible."""


def load_workflow_profile(path: str | Path) -> dict[str, Any]:
    """Load a workflow profile from *path* and validate its basic shape.

    Workflow compatibility is checked separately by
    :func:`validate_workflow_profile`, because loading a profile does not
    necessarily imply that its target workflow is available yet.
    """

    profile_path = Path(path)
    try:
        with profile_path.open(encoding="utf-8") as handle:
            profile = json.load(handle)
    except OSError as exc:
        raise WorkflowProfileError(
            f"Unable to read workflow profile {profile_path}: {exc}"
        ) from exc
    except json.JSONDecodeError as exc:
        raise WorkflowProfileError(
            f"Workflow profile {profile_path} is not valid JSON: {exc}"
        ) from exc

    return parse_workflow_profile_json(profile)


def parse_workflow_profile_json(
    value: str | Mapping[str, Any],
) -> dict[str, Any]:
    """Parse an inline JSON profile or validate an already-decoded profile."""

    if isinstance(value, str):
        try:
            profile = json.loads(value)
        except json.JSONDecodeError as exc:
            raise WorkflowProfileError(
                f"Inline workflow profile is not valid JSON: {exc}"
            ) from exc
    else:
        profile = value

    _validate_profile_shape(profile)
    return copy.deepcopy(dict(profile))


def validate_workflow_profile(
    workflow: Mapping[str, Any], profile: Mapping[str, Any]
) -> None:
    """Validate that every profile target exists in *workflow*.

    Validation is deliberately performed before binding application so a
    stale multi-target profile cannot produce a partially patched graph.
    """

    if not isinstance(workflow, Mapping):
        raise WorkflowProfileError("ComfyUI workflow must be a JSON object")

    _validate_profile_shape(profile)

    output_node = profile["output_node"]
    if output_node not in workflow:
        raise WorkflowProfileError(
            f'Workflow profile "{profile["name"]}" references missing '
            f'output node "{output_node}"'
        )

    for binding_name, binding in profile["bindings"].items():
        for target in _targets(binding_name, binding):
            node_id = target["node"]
            input_name = target["input"]
            if node_id not in workflow:
                raise WorkflowProfileError(
                    f'Binding "{binding_name}" references missing node '
                    f'"{node_id}"'
                )

            node = workflow[node_id]
            if not isinstance(node, Mapping):
                raise WorkflowProfileError(
                    f'Workflow node "{node_id}" must be a JSON object'
                )
            inputs = node.get("inputs")
            if not isinstance(inputs, Mapping):
                raise WorkflowProfileError(
                    f'Workflow node "{node_id}" has no inputs object'
                )
            if input_name not in inputs:
                raise WorkflowProfileError(
                    f'Binding "{binding_name}" references missing input '
                    f'"{input_name}" on node "{node_id}"'
                )


def apply_workflow_bindings(
    workflow: Mapping[str, Any],
    profile: Mapping[str, Any],
    values: Mapping[str, Any],
) -> dict[str, Any]:
    """Return a deep-copied workflow with supplied profile bindings applied.

    Values omitted by the caller leave their targets unchanged. A supplied
    value without a declared binding is rejected rather than silently ignored.
    The original workflow is never mutated.
    """

    if not isinstance(values, Mapping):
        raise WorkflowProfileError("Workflow binding values must be an object")

    validate_workflow_profile(workflow, profile)

    unknown = sorted(set(values) - set(profile["bindings"]))
    if unknown:
        names = ", ".join(f'"{name}"' for name in unknown)
        raise WorkflowProfileError(
            f"Requested workflow values have no declared binding: {names}"
        )

    patched = copy.deepcopy(dict(workflow))
    for binding_name, value in values.items():
        for target in _targets(binding_name, profile["bindings"][binding_name]):
            patched[target["node"]]["inputs"][target["input"]] = copy.deepcopy(
                value
            )
    return patched


def _validate_profile_shape(profile: Mapping[str, Any]) -> None:
    if not isinstance(profile, Mapping):
        raise WorkflowProfileError("Workflow profile must be a JSON object")

    version = profile.get("version")
    if version != SUPPORTED_PROFILE_VERSION:
        raise WorkflowProfileError(
            f"Unsupported workflow profile version {version!r}; "
            f"expected {SUPPORTED_PROFILE_VERSION}"
        )

    name = profile.get("name")
    if not isinstance(name, str) or not name.strip():
        raise WorkflowProfileError("Workflow profile requires a non-empty name")

    output_node = profile.get("output_node")
    if not isinstance(output_node, str) or not output_node.strip():
        raise WorkflowProfileError(
            "Workflow profile requires output_node as a non-empty string"
        )

    bindings = profile.get("bindings")
    if not isinstance(bindings, Mapping) or not bindings:
        raise WorkflowProfileError(
            "Workflow profile requires a non-empty bindings object"
        )

    for binding_name, binding in bindings.items():
        if not isinstance(binding_name, str) or not binding_name.strip():
            raise WorkflowProfileError(
                "Workflow profile binding names must be non-empty strings"
            )
        list(_targets(binding_name, binding))


def _targets(binding_name: str, binding: Any) -> list[Mapping[str, str]]:
    targets = binding if isinstance(binding, list) else [binding]
    if not targets:
        raise WorkflowProfileError(
            f'Binding "{binding_name}" must declare at least one target'
        )

    normalized: list[Mapping[str, str]] = []
    for index, target in enumerate(targets):
        if not isinstance(target, Mapping):
            raise WorkflowProfileError(
                f'Binding "{binding_name}" target {index} must be an object'
            )
        node_id = target.get("node")
        input_name = target.get("input")
        if not isinstance(node_id, str) or not node_id.strip():
            raise WorkflowProfileError(
                f'Binding "{binding_name}" target {index} requires a '
                "non-empty node string"
            )
        if not isinstance(input_name, str) or not input_name.strip():
            raise WorkflowProfileError(
                f'Binding "{binding_name}" target {index} requires a '
                "non-empty input string"
            )
        normalized.append(target)
    return normalized
