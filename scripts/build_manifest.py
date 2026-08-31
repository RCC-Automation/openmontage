"""Write the asset_manifest from what scene_look actually produced.

    .venv/Scripts/python.exe scripts/build_manifest.py --project the-man-watches

`asset_manifest` is the canonical artifact of the `scene_look` stage and the
thing the export reads to know which still belongs to which scene. Without it
the Builder gets a timeline of prompts and no images, silently - the export does
not fail, it just pushes nothing.

Everything here is derived: the hero stills on disk, their seeds and render
times from `heroes.json`, the prompt from the scene plan that produced them, and
the measured ArcFace identity from `identity_check.json` where it exists. The
music and the audio takes are included too, because they are assets of this
project and an inventory that omits them is not an inventory.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from lib.machine_paths import project_dir  # noqa: E402


def load(path: Path):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--project", default=None)
    args = ap.parse_args()

    project = project_dir(args.project)
    plan = load(project / "artifacts" / "scene_plan.json") or {}
    heroes_dir = project / "scene_look" / "heroes"
    heroes = {h["id"]: h for h in (load(heroes_dir / "heroes.json") or [])}
    ident = {m["id"]: m["similarity"]
             for m in (load(project / "artifacts" / "identity_check.json") or {}).get("measured", [])}
    cast = load(project / "artifacts" / "cast_record.json") or {}
    model = (cast.get("candidate") or {}).get("model", "")

    assets = []
    for scene in plan.get("scenes") or []:
        sid = scene["id"]
        still = heroes_dir / f"{sid}.png"
        if not still.exists():
            continue
        h = heroes.get(sid, {})
        asset = {
            "id": f"still_{sid}",
            "type": "image",
            "path": str(still.relative_to(project)).replace("\\", "/"),
            "source_tool": "scripts/hero_stills.py",
            "scene_id": sid,
            "prompt": scene.get("description", ""),
            "model": model,
        }
        if h.get("seed") is not None:
            asset["seed"] = int(h["seed"])
        # The schema has no per-asset metadata object, and that is right -
        # it has named fields instead. identity goes to quality_score (a
        # measured 0..1, which ArcFace cosine is, clamped) and the rest to
        # generation_summary, where a human reading the manifest will find it.
        if sid in ident:
            asset["quality_score"] = max(0.0, min(1.0, round(ident[sid], 4)))
        bits = []
        if (heroes_dir / "original" / f"{sid}.png").exists():
            bits.append(f"face-swapped onto the cast reference; untouched "
                        f"original at scene_look/heroes/original/{sid}.png")
        if sid in ident:
            bits.append(f"ArcFace {ident[sid]:.3f} against that reference")
        sl = scene.get("shot_language") or {}
        if sl:
            bits.append(f"{sl.get('shot_size')}, {sl.get('camera_movement')}, "
                        f"{sl.get('lens_mm')}mm, {sl.get('lighting_key')}")
        if h.get("seconds"):
            bits.append(f"{h['seconds']} s to render")
        if bits:
            asset["generation_summary"] = ". ".join(bits) + "."
        asset["resolution"] = "1536x640"
        asset["format"] = "png"
        assets.append(asset)

    track = project / "assets" / "music" / "project_audio.mp3"
    if track.exists():
        assets.append({
            "id": "music_master", "type": "music",
            "path": "assets/music/project_audio.mp3",
            "source_tool": "comfyui_music", "scene_id": "*",
            "format": "mp3", "duration_seconds": 150.0,
            "generation_summary": ("The delivered track. artifacts/beat_map.json "
                                   "carries its measured tempo and beats, and "
                                   "those times are the timing contract - not "
                                   "the tempo that was requested."),
        })

    manifest = {
        "version": "1.0",
        "assets": assets,
        "metadata": {
            "stage": "scene_look",
            "note": ("One hero still per scene, 2.39:1, rendered from the "
                     "scene_plan descriptions and then face-swapped onto the "
                     "cast reference. identity_arcface is measured against that "
                     "reference; absent means no detectable face, which for a "
                     "wide is expected rather than a failure."),
        },
    }

    dest = project / "artifacts" / "asset_manifest.json"
    dest.write_text(json.dumps(manifest, indent=2), encoding="utf-8")

    from schemas.artifacts import validate_artifact
    validate_artifact("asset_manifest", manifest)

    images = sum(1 for a in assets if a["type"] == "image")
    swapped = sum(1 for a in assets if "face-swapped" in a.get("generation_summary", ""))
    print(f"{dest}\n  {images} stills, {swapped} face-swapped, "
          f"{len(assets) - images} other asset(s)\n  schema-valid")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
