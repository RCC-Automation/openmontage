"""Did the render actually deliver the shot you asked for?

The bench could tell you a model rendered the character badly. It could not tell
you the model rendered a *different shot* - a medium when you asked for a full
body, or a crowd when you asked for one person. Those failed silently, and they
are not the same defect as a poor likeness: one is the model ignoring an
instruction, the other is it following the instruction imperfectly.

Two cheap measurements catch both, and both come free from the face detector
already being run for identity:

  * **face fraction** - the face box over the frame area. It is the witness that
    the shot size happened. A "full body" whose face fills a quarter of the
    frame is a portrait wearing the wrong label.
  * **face count** - a "close-up portrait" holding four faces is a crowd shot.

The bands below are MEASURED, not guessed, from 36 renders of one subject across
18 models at two framings (2026-08-28). DECISIONS #27: every guessed band this
project ever used was wrong when checked, so `medium` is deliberately left
uncalibrated rather than interpolated.

    from lib.shot_size import check_shot
    check_shot(Path("render.png"), "fullbody")
    -> ShotCheck(asked='fullbody', obeyed=False, verdict='tighter than asked', ...)
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

__all__ = ["BANDS", "ShotCheck", "check_shot", "measure_shot"]

#: (low, high) face-fraction bounds per shot size, and whether the band is
#: measured here or still an open guess. Measured spans, prompt-only renders:
#:   close-up  12.02% - 56.23%, median 24.45%  (n=18)
#:   full body  0.35% -  5.20%, median  2.12%  (n=18)
#: The two do not overlap, so the boundary sits in the empty gap between them.
BANDS: dict[str, dict[str, Any]] = {
    "closeup": {"low": 0.10, "high": 1.00, "calibrated": True,
                "note": "measured 12.0-56.2% over 18 models"},
    "fullbody": {"low": 0.0, "high": 0.06, "calibrated": True,
                 "note": "measured 0.35-5.2% over 18 models"},
    # No medium-shot renders have been swept, so this band is the untested gap
    # between the two that were. It is reported as uncalibrated so a caller
    # cannot mistake it for evidence.
    "medium": {"low": 0.04, "high": 0.14, "calibrated": False,
               "note": "NOT CALIBRATED - the untested gap between close-up and full body"},
}

#: Below this the face is too few pixels for ArcFace to mean anything, so an
#: identity score taken from the same frame is noise (DECISIONS #40).
MEASURABLE_FACE_FRACTION = 0.01


@dataclass
class ShotCheck:
    asked: str
    face_fraction: float | None = None
    faces: int = 0
    obeyed: bool = False
    verdict: str = ""
    identity_measurable: bool = False
    calibrated: bool = True

    def as_dict(self) -> dict[str, Any]:
        return {"asked": self.asked, "faces": self.faces, "obeyed": self.obeyed,
                "verdict": self.verdict, "calibrated": self.calibrated,
                "identity_measurable": self.identity_measurable,
                "face_fraction": (None if self.face_fraction is None
                                  else round(self.face_fraction, 5))}


def measure_shot(path: Path | str) -> tuple[float | None, int]:
    """Face fraction of the largest face, and how many faces are in the frame."""
    from lib.face_identity import faces_in

    detected = faces_in(path)
    if not detected:
        return None, 0
    try:
        from PIL import Image

        with Image.open(path) as handle:
            frame = float(handle.width * handle.height)
    except Exception:
        return None, len(detected)
    if not frame:
        return None, len(detected)
    x1, y1, x2, y2 = detected[0].bbox
    return float(abs((x2 - x1) * (y2 - y1)) / frame), len(detected)


def check_shot(path: Path | str, asked: str, *, expect_people: int = 1) -> ShotCheck:
    """Compare a render against the shot size and subject count it was asked for.

    `expect_people` defaults to 1 because that is what a character sweep asks
    for. A festival or street prompt reliably puts bystanders in frame, so a
    count above the expectation is worth surfacing rather than treating as
    failure - the subject is usually still the largest face.
    """
    band = BANDS.get(asked)
    fraction, faces = measure_shot(path)
    check = ShotCheck(asked=asked, face_fraction=fraction, faces=faces,
                      calibrated=bool(band and band["calibrated"]),
                      identity_measurable=bool(
                          fraction is not None and fraction >= MEASURABLE_FACE_FRACTION))
    if band is None:
        check.verdict = f"unknown shot size {asked!r}"
        return check
    if fraction is None:
        # No face at all. For a wide establishing shot that may be correct; for
        # a portrait it is a failure. The caller knows which, so say what was
        # seen rather than guessing a verdict.
        check.verdict = "no face detected"
        return check
    if fraction < band["low"]:
        check.verdict = "wider than asked"
    elif fraction > band["high"]:
        check.verdict = "tighter than asked"
    else:
        check.obeyed = True
        check.verdict = "as asked"
    if faces > expect_people:
        check.obeyed = False
        check.verdict = f"{check.verdict}, {faces} people not {expect_people}"
    return check
