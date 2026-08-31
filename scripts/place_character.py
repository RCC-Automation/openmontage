"""Get a named character *small* in a crowd, when the model insists on a portrait.

    .venv/Scripts/python.exe scripts/place_character.py --project the-man-watches
    .venv/Scripts/python.exe scripts/place_character.py --project the-man-watches \
        --only crowd-subject scale-anchored

The problem
-----------

`The Man Watches` needs its character at roughly 60 px in a crowd wide - that is
her real size in most of the film, and the whole structure depends on the
audience finding her there. Both people-bearing look rounds put her **large in
the foreground with her back to camera** instead, despite "far from camera and
small in frame" being stated in the prompt. FLUX.1 dev appears to treat any
named individual as the subject of a portrait regardless of stated scale.

That is 14 L3 shots plus 6 night shots - over half the film - so it is worth
one careful test rather than 20 hopeful renders.

Five strategies, each a different theory of the cause
-----------------------------------------------------

``named``          the control. The exact phrasing that failed, re-run, so the
                   comparison is against something real rather than remembered.
``crowd-subject``  the crowd is the grammatical subject and she is a subordinate
                   detail. Theory: the model renders whatever the sentence is
                   *about*.
``scale-anchored`` explicit fractional scale and a position in the frame.
                   Theory: "small" is too weak a word; a fraction is not.
``zbase-negative`` Z-Image **Base**, which takes a live negative prompt, pushing
                   against portrait framing directly. FLUX.1 dev cannot do this:
                   its negative is hard-zeroed by `ConditioningZeroOut`, so the
                   fix that worked for the bystander problem (DECISIONS #42) is
                   *absent* here, not weak.
``img2img``        the approved plate re-sampled at low denoise with her named.
                   Theory: keep the crowd, ground and light that were already
                   picked, and only let the sampler add a person. This is the
                   only strategy that preserves the approved keyframe, which the
                   reuse discipline needs.

What gets measured
------------------

The scarf is the identity carrier - measured, not assumed: at 60 px colour finds
her and brightness does not. So the metric is the **tallest saturated-red blob**
as a percentage of frame height:

    ~3-6%    she is in the crowd at roughly the right scale
    >15%     a foreground portrait - the failure being tested

It is a proxy, not a person detector, and it is stated as one. Anything red in
frame counts. Judgement about a rendered image is still made by looking at it
(DECISIONS #40); this exists so the looking is guided to the right frames.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from lib.machine_paths import project_dir, repo_root  # noqa: E402

REPO = repo_root()
sys.path.insert(0, str(REPO / "workflows" / "image-bench"))
from graphs import MODELS, build  # noqa: E402

#: The WSL server. Not where image work normally runs - the split puts Wan in
#: WSL and everything else on Windows - but `flux1-dev.safetensors` and both
#: encoders are present there, and switching servers is the human's call, not
#: this script's. WSL is ~20% slower warm on images (22.1 s against 18.3 s) and
#: much slower cold (216 s against 33 s) because of the 9p filesystem.
DEFAULT_SERVER = "http://127.0.0.1:8189"

WIDTH, HEIGHT, SEED = 1024, 1024, 4402

#: The L3 plate that was picked, minus the sentence that places her. Every
#: strategy re-states this so only the way she is named differs.
SETTING = (
    "Elevated view from forty feet up over the open dusty apron between a modern "
    "desert festival city and open playa, a dense crowd of several hundred people "
    "in modern clothing - shorts, tank tops, boots, dust goggles, utility jackets "
    "- bicycles and small art vehicles among them, tents and scaffolding along the "
    "far edge, dust haze, low afternoon sun, documentary photograph, locked off, "
    "no tilt. The crowd streams left to right across the middle of frame, bare "
    "dust ground in the foreground, camps along the top edge")

STRATEGIES = {
    "named": {
        "model": "flux1_dev",
        "why": "The control - the exact phrasing that produced a foreground portrait.",
        "prompt": SETTING + (
            ". Far from camera and small in frame, one woman with a bright red "
            "scarf around her neck and shoulders stands still while the crowd "
            "moves past her"),
    },
    "crowd-subject": {
        "model": "flux1_dev",
        "why": "The crowd is what the sentence is about; she is a detail inside it.",
        "prompt": (
            "A dense crowd of several hundred people walking left to right across "
            "a dusty desert street, seen from forty feet above, shorts, tank tops, "
            "boots, dust goggles, utility jackets, bicycles and small art vehicles "
            "among them, tents and scaffolding along the far edge, dust haze, low "
            "afternoon sun, documentary photograph, locked off, no tilt, bare dust "
            "ground in the foreground, camps along the top edge. Among the walkers, "
            "one of them wears a deep red scarf"),
    },
    "scale-anchored": {
        "model": "flux1_dev",
        "why": "'Small' is a weak word. A fraction of the frame is not.",
        "prompt": SETTING + (
            ". Somewhere in the middle distance of the crowd, one of the small "
            "distant figures wears a deep red scarf; her whole body is no taller "
            "than one twentieth of the frame height, the same size as the people "
            "around her, seen from above and behind, her face not visible"),
    },
    "zbase-negative": {
        "model": "zImageBase",
        "real_negative": True,
        "why": ("Z-Image Base takes a live negative. FLUX.1 dev cannot - its "
                "negative is zeroed - so this tests whether the fix is available "
                "at all on a model that has it."),
        "prompt": SETTING + (
            ". One of the distant walkers in the crowd wears a deep red scarf"),
        "negative": ("portrait, close-up, foreground subject, large figure, person "
                     "facing camera, person filling the frame, shallow depth of "
                     "field, bokeh"),
    },
    "detailer": {
        "model": "flux1_dev",
        "from_plate": "scene_look/place-her/scale-anchored.png",
        "crop_px": [256, 384],
        "why": ("Inpaint at her scale renders a person but not a scarf - there "
                "are too few pixels for the detail that carries her identity. "
                "So crop her patch of the plate, upscale it to the model's own "
                "working size, paint her there, and put the patch back."),
        "prompt": (
            "A long bright crimson red scarf, vivid saturated red fabric, hanging "
            "down the back of a woman who is walking away from camera across pale "
            "dust, seen from high above and behind, dark layered desert clothing "
            "under the red scarf, dark hair, the red is the brightest thing in "
            "frame, documentary photograph, low afternoon sun"),
    },
    "inpaint": {
        "model": "flux1_dev",
        "from_plate": "scene_look/place-her/scale-anchored.png",
        "mask_px": [120, 200],
        "why": ("Put her into a crowd plate that has no protagonist, by painting "
                "her into a small masked region. The only strategy that can set "
                "her size directly instead of asking for it."),
        "prompt": (
            "One person walking in a dense crowd on a dusty desert street, seen "
            "from forty feet above and slightly behind, wearing dark layered "
            "desert clothing and one long deep red scarf over her shoulders, dark "
            "hair, the same size as the people around her, documentary photograph, "
            "dust haze, low afternoon sun"),
    },
    "img2img": {
        "model": "flux1_dev",
        "from_plate": "scene_look/l3/01_flow-across.png",
        "denoise": [0.35, 0.55],
        "why": ("Keep the approved plate and let the sampler only add a person. "
                "The one strategy that preserves the picked keyframe."),
        "prompt": SETTING + (
            ". One of the distant walkers in the middle of the crowd wears a deep "
            "red scarf, the same size as the people around her"),
    },
}


# -------------------------------------------------------------------- comfy --

def upload(server: str, path: Path) -> str:
    boundary = "----openmontage"
    body = f"--{boundary}\r\n".encode()
    body += (f'Content-Disposition: form-data; name="image"; filename="{path.name}"\r\n'
             "Content-Type: image/png\r\n\r\n").encode()
    body += path.read_bytes() + b"\r\n"
    body += (f'--{boundary}\r\nContent-Disposition: form-data; name="overwrite"'
             "\r\n\r\ntrue\r\n").encode()
    body += f"--{boundary}--\r\n".encode()
    req = urllib.request.Request(
        f"{server}/upload/image", data=body,
        headers={"Content-Type": f"multipart/form-data; boundary={boundary}"})
    return json.loads(urllib.request.urlopen(req, timeout=600).read())["name"]


def render(server: str, graph: dict, dest: Path, minutes: float = 30.0) -> float | None:
    start = time.time()
    req = urllib.request.Request(f"{server}/prompt",
                                 data=json.dumps({"prompt": graph}).encode(),
                                 headers={"Content-Type": "application/json"})
    try:
        pid = json.loads(urllib.request.urlopen(req, timeout=120).read())["prompt_id"]
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode(errors="replace")
        try:
            d = json.loads(detail)
            errs = [f"node {n} ({v.get('class_type')}): {e.get('details') or e.get('message')}"
                    for n, v in (d.get("node_errors") or {}).items()
                    for e in v.get("errors") or []]
            detail = "; ".join(errs) or d.get("error", {}).get("message", detail)
        except Exception:
            pass
        print(f" HTTP {exc.code}: {detail[:300]}")
        return None

    while time.time() - start < minutes * 60:
        try:
            hist = json.loads(urllib.request.urlopen(
                f"{server}/history/{pid}", timeout=60).read())
            if pid in hist:
                break
        except Exception:
            pass
        time.sleep(3)
    else:
        print(f" no result after {minutes:.0f} min (prompt {pid[:8]})")
        return None

    for node in (hist[pid].get("outputs") or {}).values():
        for item in node.get("images") or []:
            q = urllib.parse.urlencode({
                "filename": item["filename"], "subfolder": item.get("subfolder", ""),
                "type": item.get("type", "output")})
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_bytes(urllib.request.urlopen(
                f"{server}/view?{q}", timeout=900).read())
            return round(time.time() - start, 1)
    print(f" finished but wrote no image ({hist[pid].get('status', {}).get('status_str')})")
    return None


def img2img_graph(spec: dict, *, image: str, prompt: str, seed: int,
                  denoise: float, prefix: str) -> dict:
    """Text-to-image graph with the empty latent swapped for a real one. The
    plate survives whatever `denoise` does not let the sampler touch."""
    g = build(spec, prompt=prompt, negative="", width=WIDTH, height=HEIGHT,
              seed=seed, prefix=prefix)
    g["20"] = {"class_type": "LoadImage", "inputs": {"image": image}}
    g["21"] = {"class_type": "VAEEncode",
               "inputs": {"pixels": ["20", 0], "vae": g["9"]["inputs"]["vae"]}}
    g["8"]["inputs"]["latent_image"] = ["21", 0]
    g["8"]["inputs"]["denoise"] = denoise
    g.pop("6", None)
    return g


def masked_plate(plate: Path, mask_px: int, out: Path) -> Path:
    """Copy the plate with a transparent hole where she should stand.

    ComfyUI's LoadImage returns `1 - alpha` as its MASK output, so a hole in the
    alpha channel is the region to repaint. The hole goes in the mid-ground
    crowd on the left third, where there is a walking lane rather than a face,
    and it is twice as tall as it is wide because a standing person is.
    """
    from PIL import Image

    im = Image.open(plate).convert("RGBA")
    w, h = im.size
    box_h = mask_px
    box_w = max(12, box_h // 3)
    # Left third, sitting on the crowd's mid-ground line at ~62% of frame
    # height. Not centre: the composition puts open ground on the left, which
    # is where a still figure in a moving crowd reads.
    cx, cy = int(w * 0.30), int(h * 0.62)
    # Paste a flat colour into the box with NO mask argument. Passing the
    # transparent tile as its own mask pastes nothing at all - the mask decides
    # *where* to paste, and an all-zero alpha means nowhere.
    x0, y0 = cx - box_w // 2, cy - box_h
    im.paste((0, 0, 0, 0), (x0, y0, x0 + box_w, y0 + box_h))
    out.parent.mkdir(parents=True, exist_ok=True)
    im.save(out)
    return out


def inpaint_graph(spec: dict, *, image: str, prompt: str, seed: int,
                  prefix: str) -> dict:
    """Repaint only the masked hole. Denoise stays 1.0 - VAEEncodeForInpaint
    hands the sampler pure noise inside the mask and the plate outside it."""
    g = build(spec, prompt=prompt, negative="", width=WIDTH, height=HEIGHT,
              seed=seed, prefix=prefix)
    g["20"] = {"class_type": "LoadImage", "inputs": {"image": image}}
    g["21"] = {"class_type": "VAEEncodeForInpaint",
               "inputs": {"pixels": ["20", 0], "vae": g["9"]["inputs"]["vae"],
                          "mask": ["20", 1], "grow_mask_by": 8}}
    g["8"]["inputs"]["latent_image"] = ["21", 0]
    g["8"]["inputs"]["denoise"] = 1.0
    g.pop("6", None)
    return g


def detail_patch(plate: Path, crop_px: int, work: Path) -> tuple[Path, tuple]:
    """Crop her patch of the plate and upscale it to the model's working size.

    An inpaint at her real scale gives the sampler about 60 px of person, which
    is enough for a silhouette and not enough for a scarf. Blowing the patch up
    to 1024 gives the same square of ground roughly four times the pixels, so
    the detail that carries her identity has somewhere to exist. The patch goes
    back down afterwards and the frame never changes size.
    """
    from PIL import Image

    im = Image.open(plate).convert("RGB")
    w, h = im.size
    cx, cy = int(w * 0.30), int(h * 0.55)
    half = crop_px // 2
    box = (max(0, cx - half), max(0, cy - half),
           min(w, cx + half), min(h, cy + half))
    patch = im.crop(box).resize((WIDTH, HEIGHT), Image.LANCZOS).convert("RGBA")

    # She stands on the ground line in the middle of the patch. Height is set as
    # a share of the upscaled patch so it scales back to about 60 px whatever
    # crop size is used.
    ph = int(HEIGHT * 60 / crop_px)
    # A person seen from forty feet up is nearly as wide as they are tall in the
    # shoulders, and much shorter than a standing profile. A 1:3 slot forces an
    # unnaturally thin figure; 1:1.8 leaves room for shoulders and a scarf.
    pw = max(24, int(ph / 1.8))
    px, py = WIDTH // 2, int(HEIGHT * 0.62)
    box = (px - pw // 2, py - ph, px + pw // 2, py)
    # Mid-grey, not black. VAEEncodeForInpaint encodes what is under the mask,
    # so a black hole biases the result dark - which is exactly how the first
    # attempt produced a featureless black silhouette.
    patch.paste((128, 128, 128, 0), box)
    work.parent.mkdir(parents=True, exist_ok=True)
    patch.save(work)
    return work, box


def paste_patch(plate: Path, painted: Path, box: tuple, dest: Path) -> Path:
    """Put the painted patch back, feathered, so no rectangle shows."""
    from PIL import Image, ImageFilter

    base = Image.open(plate).convert("RGB")
    bw, bh = box[2] - box[0], box[3] - box[1]
    patch = Image.open(painted).convert("RGB").resize((bw, bh), Image.LANCZOS)

    # A soft-edged alpha rather than a hard rectangle: the inpaint changed only
    # the middle of the patch, and the edges should hand back to the original.
    mask = Image.new("L", (bw, bh), 0)
    inset = max(4, min(bw, bh) // 8)
    mask.paste(255, (inset, inset, bw - inset, bh - inset))
    mask = mask.filter(ImageFilter.GaussianBlur(inset / 2))

    base.paste(patch, (box[0], box[1]), mask)
    base.save(dest)
    return dest


# -------------------------------------------------------------------- measure --

def red_blob(path: Path) -> dict:
    """Tallest saturated-red region, as a share of frame height.

    A proxy for 'how big is she', not a person detector: anything red counts.
    It is the right proxy here because colour is what was measured to carry her
    identity at distance - see wiki/character/what-we-measured.md.
    """
    try:
        import numpy as np
        from PIL import Image
    except ImportError:
        return {"error": "numpy/pillow not available - run with the repo venv"}

    im = Image.open(path).convert("RGB")
    a = np.asarray(im).astype(np.int16)
    r, g, b = a[..., 0], a[..., 1], a[..., 2]
    mx, mn = a.max(-1), a.min(-1)
    # Red-dominant, saturated, not near-black. Deliberately loose: a scarf in
    # dust haze desaturates, and missing her is worse than counting a red tent.
    mask = (r > g + 40) & (r > b + 40) & (mx - mn > 45) & (mx > 60)
    if not mask.any():
        return {"present": False, "tallest_pct": 0.0, "red_share_pct": 0.0}

    # Connected components by a simple two-pass flood over rows, which is
    # enough at this size and avoids a scipy dependency.
    h, w = mask.shape
    labels = np.zeros((h, w), np.int32)
    nxt, merges = 1, {}

    def root(x):
        while merges.get(x, x) != x:
            x = merges[x]
        return x

    for y in range(h):
        row = mask[y]
        for x in np.flatnonzero(row):
            up = labels[y - 1, x] if y else 0
            left = labels[y, x - 1] if x else 0
            if up and left and root(up) != root(left):
                merges[max(root(up), root(left))] = min(root(up), root(left))
            lab = root(up or left) if (up or left) else nxt
            if not (up or left):
                nxt += 1
            labels[y, x] = lab

    flat = np.vectorize(root)(labels) if nxt > 1 else labels
    tallest, biggest = 0, 0
    for lab in np.unique(flat):
        if lab == 0:
            continue
        ys, xs = np.nonzero(flat == lab)
        if len(ys) < 12:          # speckle, not a scarf
            continue
        tallest = max(tallest, ys.max() - ys.min() + 1)
        biggest = max(biggest, len(ys))

    # numpy scalars leak out of the comparisons above and are not JSON
    # serializable; cast at the boundary rather than at every use.
    return {"present": bool(tallest > 0),
            "tallest_pct": round(100 * float(tallest) / h, 2),
            "tallest_px": int(tallest),
            "red_share_pct": round(100 * float(biggest) / (h * w), 3)}


def verdict(m: dict) -> str:
    """Report her size. Do NOT rule on it.

    The criterion is not a share of frame height - it is whether she reads the
    same size as the people around her at her depth (Raul, 2026-08-30). A figure
    at 12% standing in a foreground lane is correct perspective; the original
    plate was wrong because she was 60% while nearby figures were 15%, a 4x
    mismatch. Only a person detector could judge that automatically, and this is
    not one, so the number is context and the verdict comes from looking.
    """
    if m.get("error") or not m.get("present"):
        return "no red found - either she is absent or the scarf did not render"
    pct = m["tallest_pct"]
    scale = ("very large - check her against the figures nearest her" if pct > 30
             else "check her against the figures nearest her" if pct > 20
             else "plausible for a figure in the crowd")
    return f"red spans {pct}% of frame height ({m['tallest_px']} px) - {scale}"


# ---------------------------------------------------------------------- main --

def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--project", default=None)
    ap.add_argument("--server", default=DEFAULT_SERVER)
    ap.add_argument("--only", nargs="+", choices=list(STRATEGIES))
    ap.add_argument("--measure-only", action="store_true")
    args = ap.parse_args()

    project = project_dir(args.project)
    out = project / "scene_look" / "place-her"
    out.mkdir(parents=True, exist_ok=True)
    chosen = args.only or list(STRATEGIES)

    print(f"Getting her into the crowd, not the foreground.\n"
          f"server {args.server}, {WIDTH}x{HEIGHT}, seed {SEED} held fixed\n")

    results = []
    for name in chosen:
        s = STRATEGIES[name]
        spec = next(m for m in MODELS if m["key"] == s["model"])
        if s.get("crop_px"):
            variants = [("crop", c) for c in s["crop_px"]]
        elif s.get("mask_px"):
            variants = [("mask", m) for m in s["mask_px"]]
        elif s.get("denoise"):
            variants = [("denoise", d) for d in s["denoise"]]
        else:
            variants = [(None, None)]

        for kind, dn in variants:
            tag = (name if kind is None else
                   f"{name}_c{dn:03d}" if kind == "crop" else
                   f"{name}_m{dn:03d}" if kind == "mask" else
                   f"{name}_d{int(dn * 100):03d}")
            dest = out / f"{tag}.png"
            secs = None

            if not args.measure_only and not dest.exists():
                print(f"  {tag:22} on {spec['label']} ...", end="", flush=True)
                if kind is None:
                    graph = build(spec, prompt=s["prompt"],
                                  negative=s.get("negative", ""),
                                  width=WIDTH, height=HEIGHT, seed=SEED,
                                  prefix=f"placeher_{tag}",
                                  real_negative=s.get("real_negative", False))
                else:
                    plate = project / s["from_plate"]
                    if not plate.exists():
                        print(f" missing plate {plate}")
                        continue
                    if kind == "crop":
                        work, box = detail_patch(plate, dn, out / f"_patch_{tag}.png")
                        graph = inpaint_graph(
                            spec, image=upload(args.server, work),
                            prompt=s["prompt"], seed=SEED, prefix=f"placeher_{tag}")
                        painted = out / f"_painted_{tag}.png"
                        secs = render(args.server, graph, painted)
                        if secs:
                            paste_patch(plate, painted, box, dest)
                        print(f" {secs}s" if secs else "")
                        row = {"strategy": name, "variant": kind, "denoise": dn,
                               "model": spec["label"], "why": s["why"],
                               "path": str(dest), "seconds": secs,
                               "prompt": s["prompt"], "negative": ""}
                        if dest.exists():
                            row["measure"] = red_blob(dest)
                            row["verdict"] = verdict(row["measure"])
                        results.append(row)
                        continue
                    if kind == "mask":
                        holed = masked_plate(plate, dn, out / f"_mask_{tag}.png")
                        graph = inpaint_graph(
                            spec, image=upload(args.server, holed),
                            prompt=s["prompt"], seed=SEED, prefix=f"placeher_{tag}")
                    else:
                        graph = img2img_graph(
                            spec, image=upload(args.server, plate),
                            prompt=s["prompt"], seed=SEED, denoise=dn,
                            prefix=f"placeher_{tag}")
                secs = render(args.server, graph, dest)
                print(f" {secs}s" if secs else "")
            elif dest.exists():
                print(f"  {tag:22} already on disk")

            row = {"strategy": name, "variant": kind, "denoise": dn,
                   "model": spec["label"],
                   "why": s["why"], "path": str(dest), "seconds": secs,
                   "prompt": s["prompt"], "negative": s.get("negative", "")}
            if dest.exists():
                row["measure"] = red_blob(dest)
                row["verdict"] = verdict(row["measure"])
            results.append(row)

    print("\nMeasured - tallest saturated-red blob as a share of frame height.")
    print("A proxy for her size, not a person detector. Look at the frames.\n")
    for r in results:
        tag = r["strategy"] + ("" if r["denoise"] is None
                               else f" {r['variant']} {r['denoise']}")
        print(f"  {tag:24} {r.get('verdict', 'not rendered')}")

    # Merge rather than overwrite. A strategy is usually run alone (--only), and
    # a file that holds only the last invocation loses every earlier arm of the
    # experiment - which is the whole record of what was tried and ruled out.
    ledger = out / "results.json"
    prior = {}
    if ledger.exists():
        try:
            for row in json.loads(ledger.read_text(encoding="utf-8")):
                prior[(row.get("strategy"), row.get("denoise"))] = row
        except Exception:
            pass
    for row in results:
        prior[(row["strategy"], row["denoise"])] = row
    merged = sorted(prior.values(), key=lambda r: (r["strategy"], r["denoise"] or 0))
    ledger.write_text(json.dumps(merged, indent=2), encoding="utf-8")
    print(f"\nwritten: {out / 'results.json'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
