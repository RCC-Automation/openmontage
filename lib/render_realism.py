"""Does the skin look like skin? An axis we can see and cannot yet measure.

**Status: NOT CALIBRATED.** Three formulations were tried against renders from
this machine and all three failed to separate populations a human separated at a
glance. The functions are kept because the negative result is worth more than the
absence of a file: without it the next person spends the same afternoon.

---

## The problem this was built for

Tuning IP-Adapter FaceID to maximise ArcFace cosine produces waxy, idealised,
over-symmetric faces - and the cosine climbs *while* it happens, because a face
pushed toward an embedding converges on an average of that identity and averages
are smooth. Identity and realism are different axes; the first one rising says
nothing about the second.

It matters more here than elsewhere because Phase 3's output is training data. A
LoRA learns the texture of what it is shown, so a dataset of porcelain faces
yields a model that can only render porcelain faces, and no prompting at
generation time gets the pores back.

Raul spotted it in three renders. Every metric below disagreed with him, and he
was right.

## What was tried, and what each got wrong

Populations: 20 description-only renders (photographic) against 23 FaceID
renders at `lora_strength` 1.0 / `weight_faceidv2` 3.0 (plastic). Higher should
have meant more photographic in all three.

| attempt | photographic | plastic | verdict |
|---|---|---|---|
| high-frequency energy over the whole face crop | 0.168 | **0.191** | backwards |
| the same, restricted to low-gradient (flat skin) pixels | 0.055 | **0.063** | backwards, p=0.002 |
| mid-band (sigma 2-8) variation in flat skin - "mottling" | 0.160 | **0.242** | backwards |

The common error: **all three measure detail, and FaceID renders are not short of
detail.** They are *crisper* than the base model's - sharper eyeliner, harder
specular edges, more microcontrast. What reads as artificial is not missing
high-frequency energy, it is skin that is uniform in tone where real skin is
blotchy while staying razor-sharp at every edge. Signal statistics that do not
separate "surface" from "boundary" see the sharpness and score it as realism.

There was also a **confound in the populations**, and it is the more instructive
half. The photographic set came from the Phase 2 sweep - one plain dark
background, soft key light - and the plastic set from Phase 3, whose prompts add
busy clockwork backgrounds and varied lighting. So the comparison was never
FaceID-on against FaceID-off; it was two different prompts as well. The
controlled pair (`calibration/baseline_close_up.png` against
`calibration/close_up_w*.png`: one prompt, one seed, reference the only variable)
shows the real progression - each step of FaceID strength smooths and idealises -
and it is far subtler than the confounded comparison suggested.

## What would probably work

- **Skin-tone uniformity in colour**, not luminance. Real skin varies in hue
  across the face; idealised skin is one tone. Every attempt above threw the
  colour away by converting to greyscale first.
- **Facial symmetry.** Averaging toward an embedding should raise it, and it is
  cheap to measure off the landmarks InsightFace already returns.
- **A learned judge** - a CLIP or aesthetic-model prompt for "airbrushed" versus
  "photographic" - calibrated against a human-labelled set from this machine.

Whichever is tried next: build the populations from a **controlled** pair, one
prompt and one seed with the reference as the only variable. That is the mistake
that cost the most here.

Until one of them separates known-good from known-bad on this machine, realism is
judged by eye. DECISIONS #15 - the machine narrows, the human casts - and #27,
which says a metric is either calibrated against output from here or marked
NOT CALIBRATED with the population it needs. This is that mark.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Sequence

import numpy as np

__all__ = ["CALIBRATED", "face_crop", "separation", "skin_texture"]

#: False, and load-bearing. No caller may gate on `skin_texture` while this is
#: False - it does not measure what its name claims, and the three populations
#: above are the evidence.
CALIBRATED = False

_BLUR_SIGMA = 2.0


def face_crop(path: Path | str, *, pad: float = 0.1) -> np.ndarray | None:
    """The detected face box as greyscale float, or None when there is no face.

    Padded slightly because ArcFace's box is tight to the features while the skin
    that shows texture best - cheeks, forehead, jaw - sits just outside it. Still
    useful for whatever measure comes next, which is why it survives.
    """
    try:
        from PIL import Image

        from lib.face_identity import faces_in
    except Exception:
        return None

    detected = faces_in(path)
    if len(detected) != 1:
        return None
    try:
        with Image.open(path) as handle:
            image = handle.convert("L")
            width, height = image.size
            x1, y1, x2, y2 = detected[0].bbox
            box_w, box_h = abs(x2 - x1), abs(y2 - y1)
            left = max(0, int(min(x1, x2) - box_w * pad))
            top = max(0, int(min(y1, y2) - box_h * pad))
            right = min(width, int(max(x1, x2) + box_w * pad))
            bottom = min(height, int(max(y1, y2) + box_h * pad))
            if right - left < 16 or bottom - top < 16:
                return None
            return np.asarray(image.crop((left, top, right, bottom)), dtype=np.float64)
    except Exception:
        return None


def skin_texture(path: Path | str) -> float | None:
    """High-frequency energy in the face, as a share of its own contrast.

    **Does not measure realism.** Kept as a diagnostic and as the record of a
    failed hypothesis: on this machine it scores idealised FaceID renders
    *higher* than photographic ones (0.191 against 0.168), because they are
    crisper at the edges. Never gate on it.
    """
    crop = face_crop(path)
    if crop is None:
        return None
    try:
        from scipy.ndimage import gaussian_filter
    except Exception:
        return None
    contrast = float(crop.std())
    if contrast <= 1e-6:
        return 0.0
    detail = crop - gaussian_filter(crop, sigma=_BLUR_SIGMA)
    return float(detail.std() / contrast)


def separation(good: Sequence[float], bad: Sequence[float]) -> dict[str, Any]:
    """How cleanly two populations separate, and where a floor could sit.

    The harness a candidate metric has to pass before anything is allowed to gate
    on it. Reports overlap rather than returning a midpoint that hides it - all
    three attempts above overlapped, and two of them overlapped *inverted*.
    """
    good_array = np.asarray([v for v in good if v is not None], dtype=np.float64)
    bad_array = np.asarray([v for v in bad if v is not None], dtype=np.float64)
    if good_array.size == 0 or bad_array.size == 0:
        return {"separated": False, "reason": "a population was empty"}
    inverted = float(bad_array.mean()) > float(good_array.mean())
    overlap = float(bad_array.max()) >= float(good_array.min())
    return {
        "separated": not overlap,
        "inverted": inverted,
        "good": {
            "n": int(good_array.size),
            "min": round(float(good_array.min()), 4),
            "mean": round(float(good_array.mean()), 4),
            "max": round(float(good_array.max()), 4),
        },
        "bad": {
            "n": int(bad_array.size),
            "min": round(float(bad_array.min()), 4),
            "mean": round(float(bad_array.mean()), 4),
            "max": round(float(bad_array.max()), 4),
        },
        "suggested_floor": round(
            (float(good_array.min()) + float(bad_array.max())) / 2, 4
        )
        if not overlap
        else None,
    }
