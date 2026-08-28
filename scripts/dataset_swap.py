"""The dataset, built the way that actually works: render freely, then swap the face.

    python scripts/dataset_swap.py --project burningman
    python scripts/dataset_swap.py --project burningman --measure-only

Two stages, because the two halves of "a photo of her" are best solved apart:

  1. **Render the body.** Klein multi-reference off the three masters, full
     prompt, twelve poses, eighteen backgrounds. Whatever the base model does
     with the brief is kept - the adult woman, the wardrobe, the light.
  2. **Transplant the face.** ReActor puts the anchor's actual face on each
     render, then GFPGAN re-details it. No generation, so nothing re-imagines
     her.

Measured on this machine, against the face master:

    Klein reference alone        0.53 - 0.68   a family resemblance
    IP-Adapter FaceID            0.75 - 0.84   consistent, but it normalised an
                                               adult woman into a teenager
    Klein + ReActor swap         **0.88**      her, on the right body

Every candidate is scored before and after the swap, so the report shows what
the swap was worth per image rather than asserting it.
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

from lib.character_dataset import LADDER, balance, find_phash_duplicates, plan_dataset  # noqa: E402
from lib.face_identity import faces_in  # noqa: E402
from lib.sheets import ACCENTS, SheetItem, labelled_sheet  # noqa: E402
from scripts.dataset_klein import (  # noqa: E402
    FESTIVAL_BACKGROUNDS,
    SOLO,
    _payload,
    _references,
    _sheet_parts,
)
from scripts.masters import _reference_guard  # noqa: E402
from tools._comfyui.client import ComfyUIClient  # noqa: E402
from tools._comfyui.faceswap import OUTPUT_NODE as SWAP_OUT, build_faceswap_graph  # noqa: E402
from tools._comfyui.vrgdg import VRGDGClient, node_class_types  # noqa: E402

SEED_MAX = 18_446_744_073_709_551_615


def _face(path: Path) -> tuple[int, np.ndarray | None, float | None]:
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


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project", required=True)
    parser.add_argument("--brief", default=None)
    parser.add_argument("--multiplier", type=float, default=1.2, help="Candidates per wanted image.")
    parser.add_argument("--seed", type=int, default=90210)
    parser.add_argument("--width", type=int, default=832)
    parser.add_argument("--height", type=int, default=1216)
    parser.add_argument("--restore-visibility", type=float, default=0.5)
    parser.add_argument(
        "--accept-at", type=float, default=0.75,
        help="Raw ArcFace to the face master, AFTER the swap. The swap makes 0.75 reachable.",
    )
    parser.add_argument("--boost-model", default="codeformer-v0.1.0.pth",
                        help="Face upscaler applied before the blend. 'none' disables it.")
    parser.add_argument("--boost-codeformer-weight", type=float, default=0.7)
    parser.add_argument("--measure-only", action="store_true")
    args = parser.parse_args()

    project = ROOT / "projects" / args.project
    masters = json.loads((project / "masters" / "masters.json").read_text(encoding="utf-8"))
    brief = args.brief or masters.get("brief")
    anchor = Path(masters["face"])
    out = project / "dataset"
    raw_dir, swap_dir, sheets_dir = out / "raw", out / "swapped", out / "sheets"
    for d in (raw_dir, swap_dir, sheets_dir):
        d.mkdir(parents=True, exist_ok=True)

    _, master_vec, _ = _face(anchor)
    if master_vec is None:
        print("FAIL: the face master has no single detectable face")
        return 1

    vrgdg, client = VRGDGClient(), ComfyUIClient()
    if not vrgdg.is_available():
        print("FAIL:", vrgdg.unavailable_reason())
        return 1
    added = _reference_guard(vrgdg, f"{brief}. full body shot", anchor, args.width, args.height)
    if not added:
        print("FAIL: the Klein reference was silently dropped; see HANDOFF")
        return 1

    scaled = [
        type(f)(f.name, f.shot, max(1, round(f.target * args.multiplier)), f.anchored_on, f.start_at)
        for f in LADDER
    ]
    specs = plan_dataset(scaled, seed_base=0, backgrounds=FESTIVAL_BACKGROUNDS)
    rng = np.random.default_rng(args.seed)
    seeds = [int(s) for s in rng.integers(0, SEED_MAX, size=len(specs), dtype=np.uint64)]
    print(f"reference guard: {sorted(added)}")
    print(f"plan: {len(specs)} candidates - " + ", ".join(f"{f.name} {f.target}" for f in scaled))
    print(f"accept at {args.accept_at:g} after swap, restore visibility {args.restore_visibility:g}\n")

    rows: list[dict] = []
    started = time.time()
    per_family: dict[str, int] = {}
    for spec, seed in zip(specs, seeds):
        fam = spec.family
        per_family[fam] = per_family.get(fam, 0) + 1
        index = per_family[fam]
        (raw_dir / fam).mkdir(parents=True, exist_ok=True)
        (swap_dir / fam).mkdir(parents=True, exist_ok=True)
        raw = raw_dir / fam / f"{index:02d}_s{seed}.png"
        swapped = swap_dir / fam / f"{index:02d}_s{seed}.png"
        refs = _references(fam, spec.angle, masters)
        prompt = spec.prompt(brief) + ". " + spec.angle + ". " + SOLO
        elapsed = 0.0

        if not raw.is_file() and not args.measure_only:
            graph = vrgdg.build("flux_klein", _payload(prompt, seed, refs, args.width, args.height))
            if not (node_class_types(graph.prompt) & added):
                print(f"  {fam:10s} {index:>2}: reference dropped; skipped")
                continue
            node = graph.output_node(prefer="image")
            graph.prune(node)
            t = time.time()
            try:
                client.generate(graph.prompt, output_node=node, dest=raw, timeout=600)
            except Exception as exc:
                print(f"  {fam:10s} {index:>2}: render FAILED {str(exc)[:80]}")
                continue
            elapsed = time.time() - t
        if not raw.is_file():
            continue

        n_before, v_before, _ = _face(raw)
        cos_before = None if v_before is None else float(np.dot(master_vec, v_before))
        if v_before is None:
            print(f"  {fam:10s} {index:>2}: no face in the render; cannot swap")
            rows.append({"family": fam, "index": index, "seed": seed, "raw": str(raw),
                         "path": None, "cos_before": None, "cos_after": None, "verdict": "reject"})
            continue

        if not swapped.is_file() and not args.measure_only:
            # Boost is not optional: without it inswapper's 128px face pastes
            # into a 1216px frame and reads blurred against a sharp body -
            # measured sharpness 0.099 against the render's own 0.326. CodeFormer
            # as the boost model restores real skin texture where GFPGAN alone
            # over-sharpens an already-smooth face.
            g = build_faceswap_graph(source_face=anchor, target_image=raw,
                                     face_restore_visibility=args.restore_visibility,
                                     boost_model=args.boost_model,
                                     boost_codeformer_weight=args.boost_codeformer_weight)
            t = time.time()
            try:
                client.generate(g, output_node=SWAP_OUT, dest=swapped, timeout=600)
            except Exception as exc:
                print(f"  {fam:10s} {index:>2}: swap FAILED {str(exc)[:80]}")
                continue
            elapsed += time.time() - t
        if not swapped.is_file():
            continue

        n_after, v_after, share = _face(swapped)
        cos_after = None if v_after is None else float(np.dot(master_vec, v_after))
        verdict = "accept" if (cos_after is not None and cos_after >= args.accept_at) else "reject"
        rows.append({
            "family": fam, "index": index, "seed": seed, "raw": str(raw), "path": str(swapped),
            "cos_before": None if cos_before is None else round(cos_before, 4),
            "cos_after": None if cos_after is None else round(cos_after, 4),
            "gain": None if (cos_before is None or cos_after is None) else round(cos_after - cos_before, 4),
            "faces": n_after, "face_fraction": None if share is None else round(share, 5),
            "descriptor": spec.descriptor(), "verdict": verdict,
        })
        b = "n/a" if cos_before is None else f"{cos_before:.3f}"
        a = "n/a" if cos_after is None else f"{cos_after:.3f}"
        print(f"  {fam:10s} {index:>2}  {elapsed:5.1f}s  {b} -> {a}  {verdict}")

    accepted = [r for r in rows if r["verdict"] == "accept"]
    if not accepted:
        print("\nFAIL: nothing cleared the gate")
        return 1

    dupes = {j for _, j, _ in find_phash_duplicates([Path(r["path"]) for r in accepted])}
    final = [r for i, r in enumerate(accepted) if i not in dupes]
    acc_dir = out / "accepted"
    if acc_dir.exists():
        shutil.rmtree(acc_dir)
    acc_dir.mkdir(parents=True)
    images = []
    for i, r in enumerate(final):
        target = acc_dir / f"{i:03d}_{r['family']}.png"
        shutil.copyfile(r["path"], target)
        images.append({"path": str(target), "source": r["path"], "raw": r["raw"],
                       "family": r["family"], "seed": r["seed"], "cos_face": r["cos_after"],
                       "face_fraction": r["face_fraction"], "descriptor": r["descriptor"],
                       "caption": None})

    vecs = [v for v in (_face(Path(i["path"]))[1] for i in images) if v is not None]
    mutual = None
    if len(vecs) >= 2:
        M = np.stack(vecs)
        G = M @ M.T
        mutual = float(G[np.triu_indices(len(vecs), k=1)].mean())
    comp = balance([i["family"] for i in images])
    minutes = (time.time() - started) / 60

    (out / "dataset.json").write_text(json.dumps({
        "version": "1.0", "character": args.project, "trigger": None, "brief": brief,
        "masters": {k: masters[k] for k in ("face", "body_front", "body_three_quarter")},
        "engine": "flux_klein render + ReActor face swap + GFPGAN restore",
        "accept_at": args.accept_at, "restore_visibility": args.restore_visibility,
        "mutual_consistency": None if mutual is None else round(mutual, 4),
        "balance": comp, "minutes": round(minutes, 1), "images": images,
    }, indent=2), encoding="utf-8")
    (out / "dataset_report.json").write_text(json.dumps({
        "counts": {"rendered": len(rows), "accepted": len(accepted),
                   "duplicates": len(dupes), "final": len(final)},
        "mean_gain_from_swap": round(float(np.mean([r["gain"] for r in rows if r.get("gain") is not None])), 4),
        "rows": rows,
    }, indent=2), encoding="utf-8")

    sheet = labelled_sheet(
        [SheetItem(Path(i["path"]), i["family"], f"cos {i['cos_face']:.2f}", ACCENTS[0]) for i in images],
        sheets_dir / "accepted.png", columns=6, cell=340,
        title=f"{args.project} - Klein render + face swap: {len(images)} images, mutual {mutual:.3f}" if mutual else "dataset",
    )
    parts = _sheet_parts(sheet, 6, 340, len(images)) if sheet else []
    gains = [r["gain"] for r in rows if r.get("gain") is not None]
    print(f"\n{len(rows)} rendered in {minutes:.0f} min | accepted {len(accepted)} | "
          f"duplicates {len(dupes)} | final {len(final)}")
    print(f"mean identity gain from the swap: {np.mean(gains):+.3f}")
    print(f"mutual consistency: {mutual:.3f}" if mutual else "")
    print(f"balance: {comp['counts']}")
    for p in (parts or ([sheet] if sheet else [])):
        print("sheet:", p)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
