"""Can a model write the words you asked for?

Text rendering is the capability that most separates current image models from
older ones, and it is the one axis in this bench that was being judged by
squinting. This turns it into a number: OCR the render, compare against the
string the prompt asked for.

RapidOCR is used rather than EasyOCR or Tesseract because it rides on the
`onnxruntime` already installed here - no torch dependency, no external binary,
and nothing that touches ComfyUI's own onnxruntime DLLs (HANDOFF trap).

    from lib.text_render import score_text
    score_text(Path("render.png"), "NIGHT OWL")
    -> TextResult(exact=True, ratio=1.0, found="NIGHT OWL", ...)
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any

__all__ = ["TextResult", "ocr_available", "read_text", "score_text"]

_READER: Any = None


def ocr_available() -> bool:
    try:
        import rapidocr_onnxruntime  # noqa: F401
    except Exception:
        return False
    return True


def _reader() -> Any | None:
    """One reader for the process. First call downloads nothing - the models
    ship inside the wheel - but it does take a second to construct."""
    global _READER
    if _READER is None:
        try:
            from rapidocr_onnxruntime import RapidOCR

            _READER = RapidOCR()
        except Exception:
            _READER = False
    return _READER or None


def _normalise(text: str) -> str:
    """Compare on letters and digits only.

    A model that renders NIGHT OWL as "NIGHT 0WL" has essentially succeeded and
    a strict comparison would call it a total failure; one that renders
    "night owl" has also succeeded. Case, spacing and punctuation are not what
    this axis is measuring.
    """
    return re.sub(r"[^a-z0-9]", "", text.lower())


@dataclass
class TextResult:
    """What the OCR found, and how close it is to what was asked for."""

    wanted: str
    found: str = ""
    ratio: float = 0.0
    exact: bool = False
    #: Every string the OCR read, in confidence order. Kept because the
    #: interesting failure is usually "it wrote something else", not "it wrote
    #: nothing", and the ratio alone hides which one happened.
    detections: list[str] = field(default_factory=list)
    ocr_ran: bool = True

    def as_dict(self) -> dict[str, Any]:
        return {"wanted": self.wanted, "found": self.found, "ratio": round(self.ratio, 3),
                "exact": self.exact, "detections": self.detections, "ocr_ran": self.ocr_ran}

    @property
    def verdict(self) -> str:
        if not self.ocr_ran:
            return "OCR unavailable"
        if self.exact:
            return "exact"
        if self.ratio >= 0.8:
            return "near miss"
        if self.detections:
            return "wrote something else"
        return "no text found"


def read_text(path: Path | str) -> list[str]:
    """Every string the OCR reads in an image, best confidence first."""
    reader = _reader()
    if reader is None:
        return []
    try:
        result, _elapsed = reader(str(path))
    except Exception:
        return []
    if not result:
        return []
    # RapidOCR returns [[box, text, confidence], ...]
    rows = [r for r in result if len(r) >= 3]
    rows.sort(key=lambda r: float(r[2]), reverse=True)
    return [str(r[1]) for r in rows]


def score_text(path: Path | str, wanted: str) -> TextResult:
    """Did this render write `wanted`? Exact match, plus a similarity ratio.

    The ratio is against the single best-matching detection rather than the
    concatenation of everything, because a poster with other words on it should
    not be penalised for them.
    """
    if not ocr_available():
        return TextResult(wanted=wanted, ocr_ran=False)
    detections = read_text(path)
    target = _normalise(wanted)
    if not target:
        return TextResult(wanted=wanted, detections=detections)

    # The OCR boxes words separately, so a two-word sign arrives as two
    # detections and matching each alone scores a correct render at 0.77.
    # Candidates therefore include the joined reading as well as each part.
    candidates = list(detections)
    if len(detections) > 1:
        candidates.append(" ".join(detections))

    best_text, best_ratio = "", 0.0
    for text in candidates:
        ratio = SequenceMatcher(None, target, _normalise(text)).ratio()
        if ratio > best_ratio:
            best_text, best_ratio = text, ratio
    return TextResult(wanted=wanted, found=best_text, ratio=best_ratio,
                      exact=_normalise(best_text) == target, detections=detections)
