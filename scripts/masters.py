"""Step 2 of the character workflow: the two body masters, from the face.

    python scripts/masters.py --project burningman --brief "..."          # generate + sheet
    python scripts/masters.py --project burningman --pick front=3 three_quarter=7

The face anchor comes from step 1 (`anchor_select.py` + `anchor_chooser.py`).
This makes the other two thirds of the character definition: a full-body front
view and a full-body three-quarter view, each generated from the face alone on
FLUX.2 Klein's multi-reference route - the strongest identity mechanism measured
on this machine (0.932 on matched framing, DECISIONS #30) - and each chosen by a
person from a numbered sheet.

Why Klein and not the engine we will train for: the masters are references,
not training data. What matters is that they are *her*; the dataset builder
reads them next and it also runs on Klein. The Juggernaut LoRA is trained on
what the builder makes, which is the "generator need not be the training model"
point of the plan.

The one guard that is not optional: when the reference key is wrong, VRGDG
deletes the conditioning node instead of erroring and hands back a plain
text-to-image graph (HANDOFF trap). So the graph is built twice - with and
without the reference - and the class types that appear only with it are
asserted present before anything renders. Self-calibrating; no magic node count.
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
import time
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from lib.face_identity import faces_in  # noqa: E402
from lib.sheets import ACCENTS, SheetItem, labelled_sheet  # noqa: E402
from tools._comfyui.client import ComfyUIClient  # noqa: E402
from tools._comfyui.vrgdg import VRGDGClient, node_class_types  # noqa: E402

#: The two framings that complete a character definition. Phrased for Klein.
FRAMINGS = {
    "front": "full body shot, standing, facing the camera straight on, whole figure visible head to feet",
    "three_quarter": "full body shot, standing, three-quarter view, whole figure visible head to feet",
}

#: Klein on this machine, from the Builder's saved defaults - never the template's.
KLEIN = {
    "unet_name": "flux-2-klein-4b-fp8.safetensors",
    "clip_name": "qwen3_4b_fp8_scaled.safetensors",
    "vae_name": "flux2-vae.safetensors",
}

SEED_STEP = 1009


def _face(path: Path) -> tuple[int, np.ndarray | None, float | None]:
    """Count, the LARGEST face's vector, and its share of the frame.

    Largest, not only: a festival prompt puts bystanders in most frames and the
    subject is still the biggest face. Scoring only single-face renders blanked
    every full-body candidate for the Burning Man character. The count is
    returned so a sheet can say "+N in frame" and the human can weigh it.
    """
    found = faces_in(path)
    if not found:
        return 0, None, None
    vector = getattr(found[0], "normed_embedding", None)
    share = None
    try:
        from PIL import Image

        with Image.open(path) as handle:
            frame = float(handle.width * handle.height)
        x1, y1, x2, y2 = found[0].bbox
        share = float(abs((x2 - x1) * (y2 - y1)) / frame) if frame else None
    except Exception:
        pass
    return len(found), (None if vector is None else np.asarray(vector, dtype=np.float32)), share


def _payload(prompt: str, seed: int, anchor: Path | None, width: int, height: int) -> dict:
    payload = {
        **KLEIN,
        "prompt": prompt,
        "seed": int(seed),
        "seed_mode": "fixed",
        "width": width,
        "height": height,
    }
    if anchor is not None:
        payload["images"] = [{"path": str(anchor.resolve())}]
    return payload


def _reference_guard(vrgdg: VRGDGClient, prompt: str, anchor: Path, width: int, height: int) -> set[str]:
    """Class types the reference adds. Empty means the reference was dropped."""
    with_ref = node_class_types(vrgdg.build("flux_klein", _payload(prompt, 1, anchor, width, height)).prompt)
    without = node_class_types(vrgdg.build("flux_klein", _payload(prompt, 1, None, width, height)).prompt)
    return with_ref - without


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project", required=True)
    parser.add_argument("--brief", default=None, help="Defaults to the anchor sweep's brief.")
    parser.add_argument("--anchor", default=None, help="Defaults to <project>/anchor/anchor.png")
    parser.add_argument("--n", type=int, default=8, help="Candidates per framing.")
    parser.add_argument("--seed-base", type=int, default=300_000)
    parser.add_argument("--width", type=int, default=832)
    parser.add_argument("--height", type=int, default=1216)
    parser.add_argument("--pick", nargs="*", default=None, help="front=N three_quarter=M")
    args = parser.parse_args()

    project = ROOT / "projects" / args.project
    anchor = Path(args.anchor) if args.anchor else project / "anchor" / "anchor.png"
    out = project / "masters"
    candidates_dir = out / "candidates"
    candidates_dir.mkdir(parents=True, exist_ok=True)

    if not anchor.is_file():
        print(f"FAIL: no face anchor at {anchor}. Run anchor_select then anchor_chooser --pick first.")
        return 1
    count, anchor_vector, _ = _face(anchor)
    if anchor_vector is None:
        print(f"FAIL: anchor has {count} faces; need exactly one.")
        return 1

    brief = args.brief
    if brief is None:
        report = project / "anchor" / "anchor_report.json"
        if report.is_file():
            brief = json.loads(report.read_text(encoding="utf-8")).get("brief")
    if not brief:
        print("FAIL: no brief; pass --brief.")
        return 1

    # ------------------------------------------------------------------ pick
    if args.pick:
        picks = dict(p.split("=", 1) for p in args.pick)
        listing = json.loads((out / "candidates.json").read_text(encoding="utf-8"))
        chosen: dict[str, dict] = {}
        for framing in FRAMINGS:
            if framing not in picks:
                print(f"FAIL: --pick needs {framing}=N")
                return 1
            rows = [r for r in listing["candidates"] if r["framing"] == framing]
            index = int(picks[framing])
            if not 1 <= index <= len(rows):
                print(f"FAIL: {framing} must be 1..{len(rows)}")
                return 1
            row = rows[index - 1]
            target = out / f"body_{framing}.png"
            shutil.copyfile(row["path"], target)
            chosen[framing] = {**row, "master": str(target), "tile": index}
            print(f"{framing:14s} tile {index}  seed {row['seed']}  cos {row['cos_anchor']}  -> {target}")
        shutil.copyfile(anchor, out / "face.png")
        (out / "masters.json").write_text(
            json.dumps(
                {
                    "version": "1.0",
                    "character": listing["character"],
                    "brief": brief,
                    "face": str(out / "face.png"),
                    "face_source": str(anchor),
                    "body_front": chosen["front"]["master"],
                    "body_three_quarter": chosen["three_quarter"]["master"],
                    "picks": chosen,
                    "engine": "flux_klein multi-reference",
                    "decided_by": "human",
                },
                indent=2,
            ),
            encoding="utf-8",
        )
        print(f"\nmasters: {out / 'masters.json'}")
        return 0

    # -------------------------------------------------------------- generate
    vrgdg = VRGDGClient()
    if not vrgdg.is_available():
        print("FAIL:", vrgdg.unavailable_reason())
        return 1
    client = ComfyUIClient()

    probe_prompt = f"{brief}. {FRAMINGS['front']}"
    added = _reference_guard(vrgdg, probe_prompt, anchor, args.width, args.height)
    if not added:
        print("FAIL: the reference image was silently dropped by the route - "
              "no node differs between the with- and without-reference graphs. "
              "Check the payload key ('images'), see HANDOFF.")
        return 1
    print(f"reference guard: the anchor adds {sorted(added)}\n")

    rows: list[dict] = []
    started = time.time()
    for framing, phrase in FRAMINGS.items():
        prompt = f"{brief}. {phrase}"
        print(f"=== {framing}: {args.n} candidates ===")
        for i in range(args.n):
            seed = args.seed_base + (0 if framing == "front" else 50_000) + i * SEED_STEP
            path = candidates_dir / f"{framing}_{i + 1:02d}_s{seed}.png"
            elapsed = 0.0
            if not path.is_file():
                graph = vrgdg.build("flux_klein", _payload(prompt, seed, anchor, args.width, args.height))
                if not (node_class_types(graph.prompt) & added):
                    print(f"  [{i + 1}/{args.n}] reference dropped on this build; skipping")
                    continue
                output_node = graph.output_node(prefer="image")
                graph.prune(output_node)
                t = time.time()
                try:
                    client.generate(graph.prompt, output_node=output_node, dest=path, timeout=600)
                except Exception as exc:
                    print(f"  [{i + 1}/{args.n}] seed {seed} FAILED: {str(exc)[:120]}")
                    continue
                elapsed = time.time() - t
            faces, vector, share = _face(path)
            cos = None if vector is None else float(np.dot(anchor_vector, vector))
            rows.append(
                {
                    "framing": framing,
                    "index": i + 1,
                    "seed": seed,
                    "path": str(path),
                    "faces": faces,
                    "cos_anchor": None if cos is None else round(cos, 4),
                    "face_fraction": None if share is None else round(share, 5),
                }
            )
            cos_text = "no face" if cos is None else f"{cos:.3f}"
            share_text = "" if share is None else f"  face {share * 100:4.1f}%"
            print(f"  [{i + 1}/{args.n}] seed {seed}  {elapsed:5.1f}s  cos {cos_text}{share_text}")

    sheets = {}
    for framing in FRAMINGS:
        items = [
            SheetItem(
                Path(r["path"]),
                f"{r['index']}.  cos {r['cos_anchor']:.3f}" if r["cos_anchor"] is not None else f"{r['index']}.  no face",
                (f"face {r['face_fraction'] * 100:.1f}%" if r["face_fraction"] else "")
                + (f"  +{r['faces'] - 1} in frame" if r["faces"] > 1 else ""),
                ACCENTS[0] if (r["cos_anchor"] or 0) >= 0.55 else ACCENTS[3],
            )
            for r in rows
            if r["framing"] == framing
        ]
        sheet = labelled_sheet(
            items,
            out / f"choose_{framing}.png",
            columns=4,
            cell=420,
            title=f"body master - {framing}. Pick by number: same person as the face? cos = ArcFace vs face anchor.",
        )
        sheets[framing] = None if sheet is None else str(sheet)

    (out / "candidates.json").write_text(
        json.dumps(
            {
                "version": "1.0",
                "character": args.project,
                "brief": brief,
                "anchor": str(anchor),
                "engine": "flux_klein",
                "reference_nodes": sorted(added),
                "minutes": round((time.time() - started) / 60, 2),
                "candidates": rows,
                "sheets": sheets,
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    print(f"\nsheets: {sheets['front']}\n        {sheets['three_quarter']}")
    print("pick with:  python scripts/masters.py --project", args.project, "--pick front=N three_quarter=M")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
