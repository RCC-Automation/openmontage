"""Face identity: is this the same person, across seeds and across shots?

The screen test's headline axis asks whether a stack holds one character. CLIP
cannot answer that. It embeds whole images, so two different women in matching
pink hair and matching light read as highly similar - which is precisely the
population a casting sweep is full of.

ArcFace can. InsightFace's ``buffalo_l`` detects a face, warps it to canonical
landmark positions, and embeds it with a recogniser trained so that the same
person scores high and different people score low, largely independent of pose,
expression and lighting. The alignment step is what makes a three-quarter angle
comparable with a front-on one, so identity can be measured across *shot sizes*
and not only across seeds.

The two measures answer different questions and neither replaces the other:

    ArcFace   the face.       Ignores hair colour, wardrobe, grade.
    CLIP      everything else. Cannot distinguish two similar faces.

A character brief like "pink hair and a brass filigree collar" needs both - a
render can keep the face and lose the character.

Runs on CPU through onnxruntime, deliberately: lib/clip_embedder makes the same
choice, and ROCm presents as CUDA, so a GPU provider would put this on the
device ComfyUI is rendering with.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Sequence

import numpy as np

__all__ = [
    "embeddings_available",
    "face_embeddings",
    "face_identity_stability",
    "faces_in",
]

_APP: Any | None = None
_MODEL_PACK = os.environ.get("OPENMONTAGE_FACE_MODEL", "buffalo_l")
# 640 is InsightFace's default and detects a portrait face comfortably. Smaller
# is faster but starts missing faces in wide shots, which would silently turn a
# measurable candidate into an unmeasured one.
_DET_SIZE = (640, 640)


def embeddings_available() -> bool:
    """True when InsightFace and its runtime can be imported."""
    try:
        import insightface  # noqa: F401
        import onnxruntime  # noqa: F401
    except Exception:
        return False
    return True


def _app() -> Any | None:
    """Load the analyser once per process; ~60s the first time, then cached."""
    global _APP
    if _APP is not None:
        return _APP
    if not embeddings_available():
        return None
    try:
        from insightface.app import FaceAnalysis

        app = FaceAnalysis(name=_MODEL_PACK, providers=["CPUExecutionProvider"])
        app.prepare(ctx_id=-1, det_size=_DET_SIZE)
    except Exception:
        return None
    _APP = app
    return _APP


def faces_in(path: Path | str) -> list[Any]:
    """Every face the detector finds, largest first."""
    app = _app()
    if app is None:
        return []
    try:
        import cv2

        image = cv2.imread(str(path))
        if image is None:
            return []
        faces = app.get(image)
    except Exception:
        return []

    def area(face: Any) -> float:
        x1, y1, x2, y2 = face.bbox
        return float((x2 - x1) * (y2 - y1))

    return sorted(faces, key=area, reverse=True)


def face_embeddings(paths: Sequence[Path]) -> list[np.ndarray | None]:
    """One normalised 512-d ArcFace vector per path, or None where no face.

    None is deliberate and distinct from a low score. A wide shot, a back view
    or a render that failed to produce a person is *missing data*, not evidence
    that the character drifted - scoring it zero would punish a stack for a
    framing choice the sweep asked for.

    Where several faces appear the largest is taken: in a portrait that is the
    subject, and a bystander in the background should not decide the verdict.
    """
    vectors: list[np.ndarray | None] = []
    for path in paths:
        faces = faces_in(path)
        if not faces:
            vectors.append(None)
            continue
        embedding = getattr(faces[0], "normed_embedding", None)
        vectors.append(
            np.asarray(embedding, dtype=np.float32) if embedding is not None else None
        )
    return vectors


def face_identity_stability(paths: Sequence[Path]) -> float | None:
    """How well one face survives across renders. 0..1, higher is steadier.

    Mean pairwise cosine between ArcFace embeddings. Returns None when fewer
    than two renders contain a detectable face, so the caller reports the gap
    rather than scoring on evidence it does not have.
    """
    usable = [Path(p) for p in paths if Path(p).is_file()]
    if len(usable) < 2:
        return None
    vectors = [v for v in face_embeddings(usable) if v is not None]
    if len(vectors) < 2:
        return None
    similarities = [
        float(np.dot(vectors[i], vectors[j]))
        for i in range(len(vectors))
        for j in range(i + 1, len(vectors))
    ]
    if not similarities:
        return None
    mean = sum(similarities) / len(similarities)
    return _rescale(mean)


# ArcFace cosine has a well-known working range - the same person typically
# lands far above different people - but the exact split depends on the
# detector, the pack and, here, on faces that were generated rather than
# photographed. NOT YET CALIBRATED against this machine's renders: measure a
# multi-seed run of one model for the "same person" population and a
# single-seed run across models for "different people", then set these from
# data. Two bands in this codebase were guessed rather than measured and both
# were wrong, one by an order of magnitude.
_DIFFERENT, _SAME = 0.20, 0.65


def _rescale(mean: float) -> float:
    return max(0.0, min(1.0, (mean - _DIFFERENT) / (_SAME - _DIFFERENT)))
