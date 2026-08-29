"""Convert a ComfyUI UI-format workflow into the API format /prompt accepts.

    python scripts/ui_to_api.py "<blueprint>.json" -o out.json
    python scripts/ui_to_api.py blueprints/*.json --outdir converted/

ComfyUI ships ~100 official blueprints under its install
(`ComfyUI/blueprints/`), and they are the authority on how to drive each model
family (`wiki/comfyui/image-recipes.md`). They are saved in **UI format** -
nodes with positional `widgets_values` and integer link ids - which `/prompt`
rejects. Normally you open one in the browser and use Workflow -> Export (API).
This does the same thing headlessly, so a blueprint can be driven from a script
without a human at the machine.

The conversion needs the server, because UI format does not record which widget
value belongs to which input name: `widgets_values` is a positional list and the
names live in `/object_info`. Everything hard about this is that mapping.

Three things that make a naive converter produce a graph ComfyUI silently
mis-runs:

**`control_after_generate` consumes an extra slot.** A seed widget serialises as
two entries - the value and the "randomize"/"fixed" control - so every widget
after a seed shifts by one if you do not skip it.

**A linked input has no widget value.** When an input is connected, the UI drops
it from `widgets_values` for some node types and keeps a stale placeholder for
others. Link-connected inputs are therefore resolved first and removed from the
widget queue by name.

**Reroute and muted nodes must be dissolved, not copied.** A Reroute has no
`class_type`; a node with `mode` 2 or 4 is muted or bypassed. Both have to be
followed through to the real upstream node or the graph fails validation.
"""

from __future__ import annotations

import argparse
import json
import sys
import urllib.request
from pathlib import Path
from typing import Any

SRV = "http://127.0.0.1:8188"

#: Nodes that exist only in the editor and never reach the backend.
UI_ONLY = {"Note", "MarkdownNote", "Reroute", "PrimitiveNode", "Anything Everywhere",
           "SubgraphInputNode", "SubgraphOutputNode"}


def object_info(server: str) -> dict[str, Any]:
    with urllib.request.urlopen(f"{server}/object_info", timeout=120) as r:
        return json.loads(r.read())


def widget_names(spec: dict[str, Any]) -> list[tuple[str, bool]]:
    """Ordered (name, eats_extra_slot) for a node class's widget inputs.

    A widget input is one whose declared type is a primitive or a combo list.
    Inputs declared as another node's output type (MODEL, LATENT, IMAGE, ...)
    are link-only and never appear in `widgets_values`.
    """
    out: list[tuple[str, bool]] = []
    for section in ("required", "optional"):
        for name, decl in (spec.get("input", {}).get(section) or {}).items():
            if not isinstance(decl, list) or not decl:
                continue
            kind, opts = decl[0], (decl[1] if len(decl) > 1 and isinstance(decl[1], dict) else {})
            is_widget = isinstance(kind, list) or kind in {
                "INT", "FLOAT", "STRING", "BOOLEAN", "COMBO"}
            if is_widget:
                out.append((name, bool(opts.get("control_after_generate"))))
    return out


def flatten_subgraphs(graph: dict[str, Any]) -> tuple[dict[str, Any], list[str]]:
    """Replace a blueprint's single subgraph instance with the subgraph itself.

    ComfyUI's newer official blueprints ship as ONE node whose `type` is a UUID,
    with the real 40-odd node graph parked in `definitions.subgraphs`. Converting
    the outer file yields an empty graph and a warning that a UUID class is not
    installed, which is true and useless.

    Only the self-contained case is handled - a blueprint whose subgraph carries
    its own loaders, which is what the official ones do. A subgraph that depends
    on values passed in from the parent is reported rather than half-converted.
    """
    subgraphs = {sg.get("id"): sg for sg in
                 (graph.get("definitions", {}).get("subgraphs") or [])}
    if not subgraphs:
        return graph, []

    instances = [n for n in graph.get("nodes", []) if n.get("type") in subgraphs]
    if len(instances) != 1:
        return graph, [f"{len(instances)} subgraph instances; only the single-instance "
                       "case is handled - export this one from the UI instead"]

    sg = subgraphs[instances[0]["type"]]
    notes = [f"flattened subgraph {sg.get('name', '?')!r}: "
             f"{len(sg.get('nodes') or [])} nodes"]
    if instances[0].get("inputs"):
        notes.append("the subgraph instance has inbound links; any value the parent "
                     "supplied is lost and must be set on the flattened graph")
    return {"nodes": sg.get("nodes") or [], "links": sg.get("links") or []}, notes


def convert(graph: dict[str, Any], info: dict[str, Any]) -> tuple[dict[str, Any], list[str]]:
    graph, warnings = flatten_subgraphs(graph)
    nodes = {str(n["id"]): n for n in graph.get("nodes", [])}

    # link id -> (origin node id, origin output slot)
    links: dict[int, tuple[str, int]] = {}
    for link in graph.get("links", []):
        # [id, origin_id, origin_slot, target_id, target_slot, type]
        if isinstance(link, list) and len(link) >= 3:
            links[link[0]] = (str(link[1]), int(link[2]))

    def alive(node_id: str) -> bool:
        n = nodes.get(node_id)
        return bool(n) and n.get("type") not in UI_ONLY and n.get("mode", 0) not in (2, 4)

    def resolve(link_id: Any) -> list[Any] | None:
        """Follow a link back to a real node, hopping reroutes and muted nodes."""
        seen = set()
        while link_id is not None and link_id in links:
            origin, slot = links[link_id]
            if alive(origin):
                return [origin, slot]
            if origin in seen:
                return None
            seen.add(origin)
            up = nodes.get(origin, {}).get("inputs") or []
            link_id = up[0].get("link") if up else None
        return None

    api: dict[str, Any] = {}
    for node_id, node in nodes.items():
        if not alive(node_id):
            continue
        cls = node["type"]
        spec = info.get(cls)
        if spec is None:
            warnings.append(f"node {node_id}: class {cls!r} is not installed on this server")
            continue

        linked: dict[str, Any] = {}
        for inp in node.get("inputs") or []:
            resolved = resolve(inp.get("link"))
            if resolved is not None:
                linked[inp["name"]] = resolved

        # Positional widget values, in the schema's own order, skipping any
        # input that arrived over a link and accounting for the extra slot a
        # control_after_generate widget serialises.
        values = list(node.get("widgets_values") or [])
        if isinstance(node.get("widgets_values"), dict):
            # Newer frontends sometimes serialise widgets by name already.
            widgets = dict(node["widgets_values"])
        else:
            widgets = {}
            queue = list(values)
            for name, extra in widget_names(spec):
                if name in linked:
                    continue
                if not queue:
                    break
                widgets[name] = queue.pop(0)
                if extra and queue:
                    queue.pop(0)

        api[node_id] = {"class_type": cls, "inputs": {**widgets, **linked},
                        "_meta": {"title": node.get("title") or cls}}

    if not api:
        warnings.append("nothing converted - is this really a UI-format workflow?")
    return api, warnings


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("paths", nargs="+", type=Path)
    ap.add_argument("-o", "--out", type=Path, help="output file (single input only)")
    ap.add_argument("--outdir", type=Path, help="output directory for several inputs")
    ap.add_argument("--server", default=SRV)
    args = ap.parse_args()

    try:
        info = object_info(args.server)
    except Exception as exc:
        print(f"cannot reach {args.server}: {exc}", file=sys.stderr)
        print("The conversion needs a running ComfyUI - widget names come from "
              "/object_info and exist nowhere in the file.", file=sys.stderr)
        return 1

    for path in args.paths:
        graph = json.loads(path.read_text(encoding="utf-8"))
        api, warnings = convert(graph, info)
        dest = args.out if (args.out and len(args.paths) == 1) else \
            (args.outdir or path.parent) / (path.stem + ".api.json")
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(json.dumps(api, indent=1), encoding="utf-8")
        print(f"{path.name}: {len(api)} nodes -> {dest}")
        for w in warnings:
            print(f"   WARN {w}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
