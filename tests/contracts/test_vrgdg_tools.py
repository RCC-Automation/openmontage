"""Contracts for the VRGDG graph-builder integration.

These cover the parts that are easy to get subtly wrong and expensive to
discover live: VRGDG's inconsistent error conventions, output-node selection in
graphs that carry preview and comparison savers, and the mutual exclusion
between the three graph sources on the ComfyUI tools.
"""

from __future__ import annotations

import json
from unittest.mock import patch

import pytest

from tools._comfyui.vrgdg import (
    BUILD_ROUTES,
    HOST_BOUND_ROUTES,
    VRGDGClient,
    VRGDGError,
    VRGDGGraph,
    build_routes_for,
    graph_hash,
    resolve_output_node,
)


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

class FakeResponse:
    def __init__(self, payload, status_code=200, text=None):
        self._payload = payload
        self.status_code = status_code
        self.reason = "Bad Request" if status_code >= 400 else "OK"
        self.text = text if text is not None else json.dumps(payload)

    @property
    def ok(self):
        return self.status_code < 400

    def json(self):
        if self._payload is _NON_JSON:
            raise ValueError("no json")
        return self._payload


_NON_JSON = object()


def _client():
    return VRGDGClient(server_url="http://testhost:8188")


# ---------------------------------------------------------------------------
# route registry
# ---------------------------------------------------------------------------

def test_route_kinds_and_paths_are_unique():
    kinds = [r.kind for r in BUILD_ROUTES.values()]
    paths = [r.path for r in BUILD_ROUTES.values()]
    assert len(kinds) == len(set(kinds))
    assert len(paths) == len(set(paths))


def test_every_route_path_is_a_workflow_runner_build_route():
    for route in BUILD_ROUTES.values():
        assert route.path.startswith("/vrgdg/workflow_runner/build_")
        assert route.path.endswith("_prompt")


def test_capability_filter_partitions_the_registry():
    total = sum(
        len(build_routes_for(cap)) for cap in ("image", "video", "audio", "utility")
    )
    assert total == len(BUILD_ROUTES)


def test_project_bound_routes_require_a_project_folder():
    for route in BUILD_ROUTES.values():
        if route.project_bound:
            assert "project_folder" in route.required


# ---------------------------------------------------------------------------
# transport normalisation
# ---------------------------------------------------------------------------

def test_host_bound_routes_are_refused_before_any_request():
    client = _client()
    with patch("tools._comfyui.vrgdg.requests.post") as post:
        with pytest.raises(VRGDGError, match="human at the ComfyUI machine"):
            client._request("POST", "/vrgdg/music_builder/pick_path", {})
    post.assert_not_called()


def test_pick_path_is_in_the_host_bound_set():
    # It opens a native OS file dialog on the ComfyUI host and blocks forever.
    assert "/vrgdg/music_builder/pick_path" in HOST_BOUND_ROUTES


def test_ok_false_with_http_200_is_still_a_failure():
    # /vrgdg/update/v10/status does exactly this.
    client = _client()
    with patch(
        "tools._comfyui.vrgdg.requests.post",
        return_value=FakeResponse({"ok": False, "error": "boom"}, 200),
    ):
        with pytest.raises(VRGDGError, match="boom"):
            client._request("POST", "/vrgdg/workflow_runner/build_zimage_prompt", {})


def test_http_500_body_is_reported():
    # The storyboard routes error with 500 rather than 400.
    client = _client()
    with patch(
        "tools._comfyui.vrgdg.requests.post",
        return_value=FakeResponse({"error": "storyboard exploded"}, 500),
    ):
        with pytest.raises(VRGDGError, match="storyboard exploded"):
            client._request("POST", "/vrgdg/storyboard/save", {})


def test_unwrapped_success_payload_is_accepted():
    # *_from_concepts/generate returns the raw helper result with no ok key.
    client = _client()
    with patch(
        "tools._comfyui.vrgdg.requests.post",
        return_value=FakeResponse({"generated": 3}, 200),
    ):
        assert client._request("POST", "/vrgdg/t2i_from_concepts/generate", {}) == {
            "generated": 3
        }


def test_non_json_body_is_a_clear_error_not_a_traceback():
    client = _client()
    with patch(
        "tools._comfyui.vrgdg.requests.post",
        return_value=FakeResponse(_NON_JSON, 502, text="<html>bad gateway</html>"),
    ):
        with pytest.raises(VRGDGError, match="non-JSON body"):
            client._request("POST", "/vrgdg/workflow_runner/build_zimage_prompt", {})


def test_tolerate_not_ok_lets_the_status_route_answer():
    client = _client()
    with patch(
        "tools._comfyui.vrgdg.requests.get",
        return_value=FakeResponse({"ok": False, "installed_commit": "abc123def456789"}, 200),
    ):
        assert client.pack_version() == "abc123def456"


# ---------------------------------------------------------------------------
# build
# ---------------------------------------------------------------------------

def test_unknown_kind_lists_the_known_kinds():
    with pytest.raises(VRGDGError, match="zimage"):
        _client().build("not_a_route", {"prompt": "x"})


def test_missing_required_keys_are_named():
    with pytest.raises(VRGDGError, match="unet_name"):
        _client().build("zimage", {"prompt": "a cat"})


def test_project_bound_route_says_so_when_keys_are_missing():
    with pytest.raises(VRGDGError, match="project-bound"):
        _client().build("i2v", {"i2v_prompt": "a cat walks"})


def test_build_returns_graph_with_seed_and_template():
    payload = {
        "ok": True,
        "workflow_path": "C:/x/text2image_zimage_API.json",
        "used_seed": 4242,
        "prompt": {"9": {"class_type": "SaveImage", "inputs": {}}},
    }
    with patch("tools._comfyui.vrgdg.requests.post", return_value=FakeResponse(payload)):
        graph = _client().build(
            "zimage",
            {
                "prompt": "a cat",
                "unet_name": "z.safetensors",
                "clip_name": "q.safetensors",
                "vae_name": "ae.safetensors",
            },
        )
    assert graph.used_seed == 4242
    assert graph.workflow_path.endswith("text2image_zimage_API.json")
    assert graph.output_node() == "9"
    assert "prompt" not in graph.raw


def test_build_without_a_graph_is_an_error():
    with patch(
        "tools._comfyui.vrgdg.requests.post",
        return_value=FakeResponse({"ok": True, "used_seed": 1}),
    ):
        with pytest.raises(VRGDGError, match="returned no graph"):
            _client().build(
                "zimage",
                {
                    "prompt": "a cat",
                    "unet_name": "z",
                    "clip_name": "q",
                    "vae_name": "ae",
                },
            )


# ---------------------------------------------------------------------------
# output-node resolution
# ---------------------------------------------------------------------------

def test_a_real_saver_beats_a_preview():
    graph = {
        "1": {"class_type": "PreviewImage", "inputs": {}},
        "2": {"class_type": "VRGDG_ImageCompare", "inputs": {}},
        "3": {"class_type": "SaveImage", "inputs": {}},
    }
    assert resolve_output_node(graph) == "3"


def test_preview_is_used_when_the_graph_has_no_saver():
    # This is the real shape of VRGDG's image templates: text2image_zimage_API
    # ends in PreviewImage (node 975) and the Builder UI persists it afterwards
    # through /vrgdg/workflow_runner/save_image. ComfyUI reports the artifact
    # under type "temp", which ComfyUIClient.download already honours.
    graph = {
        "972": {"class_type": "UNETLoader", "inputs": {}},
        "975": {"class_type": "PreviewImage", "inputs": {}},
    }
    assert resolve_output_node(graph, prefer="image") == "975"


def test_comparison_nodes_never_win_even_with_no_saver():
    graph = {
        "1": {"class_type": "VRGDG_ImageCompare", "inputs": {}},
        "2": {"class_type": "VRGDG_VideoCompareSlider", "inputs": {}},
    }
    with pytest.raises(VRGDGError):
        resolve_output_node(graph)


def test_video_saver_beats_a_preview_in_the_same_graph():
    # Singlei2vForUI_API carries PreviewImage 931 and VHS_VideoCombine 273.
    graph = {
        "273": {"class_type": "VHS_VideoCombine", "inputs": {}},
        "931": {"class_type": "PreviewImage", "inputs": {}},
        "932": {"class_type": "PreviewAudio", "inputs": {}},
    }
    assert resolve_output_node(graph, prefer="video") == "273"


def test_video_saver_wins_when_video_is_preferred():
    graph = {
        "10": {"class_type": "SaveImage", "inputs": {}},
        "20": {"class_type": "VHS_VideoCombine", "inputs": {}},
    }
    assert resolve_output_node(graph, prefer="video") == "20"
    assert resolve_output_node(graph, prefer="image") == "10"


def test_composite_node_ids_sort_numerically_not_lexically():
    # "271:9" must not beat "271:216" the way string ordering would.
    graph = {
        "271:9": {"class_type": "SaveVideo", "inputs": {}},
        "271:216": {"class_type": "SaveVideo", "inputs": {}},
    }
    assert resolve_output_node(graph) == "271:216"


def test_no_saver_or_preview_raises_rather_than_guessing():
    graph = {"1": {"class_type": "KSampler", "inputs": {}}}
    with pytest.raises(VRGDGError, match="No saver or preview"):
        resolve_output_node(graph)


def test_empty_graph_raises():
    with pytest.raises(VRGDGError):
        resolve_output_node({})


# ---------------------------------------------------------------------------
# provenance
# ---------------------------------------------------------------------------

def test_graph_hash_is_key_order_independent():
    a = {"1": {"class_type": "SaveImage", "inputs": {"x": 1, "y": 2}}}
    b = {"1": {"inputs": {"y": 2, "x": 1}, "class_type": "SaveImage"}}
    assert graph_hash(a) == graph_hash(b)


def test_graph_hash_changes_with_content():
    a = {"1": {"class_type": "SaveImage", "inputs": {"x": 1}}}
    b = {"1": {"class_type": "SaveImage", "inputs": {"x": 2}}}
    assert graph_hash(a) != graph_hash(b)


def test_provenance_pins_the_submitted_graph():
    graph = VRGDGGraph(
        kind="zimage",
        prompt={"9": {"class_type": "SaveImage", "inputs": {}}},
        workflow_path="C:/x/text2image_zimage_API.json",
        used_seed=7,
    )
    record = graph.provenance(pack_version="abc123")
    assert record["graph_source"] == "vrgdg_builder"
    assert record["vrgdg_route"] == BUILD_ROUTES["zimage"].path
    assert record["submitted_graph_hash"] == graph_hash(graph.prompt)
    assert record["used_seed"] == 7
    assert record["vrgdg_pack_version"] == "abc123"


# ---------------------------------------------------------------------------
# tool wiring
# ---------------------------------------------------------------------------

def test_image_tool_declares_the_mode():
    from tools.graphics.comfyui_image import ComfyUIImage

    tool = ComfyUIImage()
    assert tool.supports["vrgdg_builder"] is True
    assert "vrgdg_build" in tool.input_schema["properties"]


def test_video_tool_declares_the_mode():
    from tools.video.comfyui_video import ComfyUIVideo

    tool = ComfyUIVideo()
    assert tool.supports["vrgdg_builder"] is True
    assert "vrgdg_build" in tool.input_schema["properties"]


@pytest.mark.parametrize(
    "module_path,class_name",
    [
        ("tools.graphics.comfyui_image", "ComfyUIImage"),
        ("tools.video.comfyui_video", "ComfyUIVideo"),
    ],
)
def test_vrgdg_build_and_custom_workflow_are_mutually_exclusive(module_path, class_name):
    import importlib

    tool = getattr(importlib.import_module(module_path), class_name)()
    result = tool.execute(
        {
            "prompt": "a cat",
            "vrgdg_build": {"kind": "zimage"},
            "workflow_json": "{}",
        }
    )
    assert result.success is False
    assert "cannot be combined" in result.error


@pytest.mark.parametrize(
    "module_path,class_name",
    [
        ("tools.graphics.comfyui_image", "ComfyUIImage"),
        ("tools.video.comfyui_video", "ComfyUIVideo"),
    ],
)
def test_vrgdg_build_requires_a_kind(module_path, class_name):
    import importlib

    tool = getattr(importlib.import_module(module_path), class_name)()
    result = tool.execute({"prompt": "a cat", "vrgdg_build": {"payload": {}}})
    assert result.success is False
    assert "kind" in result.error


# ---------------------------------------------------------------------------
# pruning dead branches
# ---------------------------------------------------------------------------

def test_reachable_nodes_follows_links_transitively():
    from tools._comfyui.vrgdg import reachable_nodes

    graph = {
        "1": {"class_type": "Loader", "inputs": {}},
        "2": {"class_type": "Sampler", "inputs": {"model": ["1", 0]}},
        "3": {"class_type": "SaveImage", "inputs": {"images": ["2", 0]}},
        "9": {"class_type": "RAMCleanup", "inputs": {"anything": ["2", 0]}},
    }
    assert reachable_nodes(graph, "3") == {"1", "2", "3"}


def test_prune_drops_the_dead_cleanup_branch():
    # This is the real Z-Image shape: PreviewImage 975 reads straight from
    # VAEDecode 963, while RAMCleanup 976 -> VRAMCleanup 977 dangles off 963 and
    # feeds nothing. ComfyUI still validates them, so an uninstalled pack there
    # blocks a render it cannot affect.
    from tools._comfyui.vrgdg import prune_to_output

    graph = {
        "963": {"class_type": "VAEDecode", "inputs": {}},
        "975": {"class_type": "PreviewImage", "inputs": {"images": ["963", 0]}},
        "976": {"class_type": "RAMCleanup", "inputs": {"anything": ["963", 0]}},
        "977": {"class_type": "VRAMCleanup", "inputs": {"anything": ["976", 0]}},
    }
    pruned, removed = prune_to_output(graph, "975")
    assert set(pruned) == {"963", "975"}
    assert removed == ["976", "977"]


def test_prune_keeps_literals_that_look_like_links():
    from tools._comfyui.vrgdg import prune_to_output

    graph = {
        "1": {"class_type": "Sampler", "inputs": {"sigmas": [0.9, 0.7, 0.4]}},
        "2": {"class_type": "SaveImage", "inputs": {"images": ["1", 0]}},
    }
    pruned, removed = prune_to_output(graph, "2")
    assert set(pruned) == {"1", "2"}
    assert removed == []


def test_pruning_is_recorded_in_provenance():
    graph = VRGDGGraph(
        kind="zimage",
        prompt={
            "963": {"class_type": "VAEDecode", "inputs": {}},
            "975": {"class_type": "PreviewImage", "inputs": {"images": ["963", 0]}},
            "976": {"class_type": "RAMCleanup", "inputs": {"anything": ["963", 0]}},
        },
    )
    graph.prune("975")
    record = graph.provenance()
    assert record["pruned_unreachable_nodes"] == ["976"]
    assert "missing node types" in record["pruned_reason"]


def test_missing_node_types_reports_class_and_ids():
    client = _client()
    graph = {
        "1": {"class_type": "KSampler", "inputs": {}},
        "976": {"class_type": "RAMCleanup", "inputs": {}},
    }

    def fake_get(url, **kwargs):
        cls = url.rsplit("/", 1)[-1]
        if cls == "RAMCleanup":
            return FakeResponse({}, 404)
        return FakeResponse({cls: {}}, 200)

    with patch("tools._comfyui.vrgdg.requests.get", side_effect=fake_get):
        missing = client.missing_node_types(graph)
    assert missing == {"RAMCleanup": ["976"]}


def test_unreachable_probe_does_not_block_a_valid_graph():
    # A flaky /object_info must not be read as "the node is missing".
    client = _client()
    graph = {"1": {"class_type": "KSampler", "inputs": {}}}
    with patch("tools._comfyui.vrgdg.requests.get", side_effect=OSError("boom")):
        assert client.missing_node_types(graph) == {}
