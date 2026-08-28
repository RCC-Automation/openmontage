"""Phase 3: building a character dataset as a ladder, not a batch.

The anchor from Phase 2 is one close-up. A LoRA needs 20-40 images that are the
same person across framings, and the naive move - generate forty against that one
close-up - is the move our own measurement says fails.

**A reference image is shot-family-local.** We measured a close-up reference
holding identity at 0.932 on a matched close-up, then collapsing to 0.301 on a
medium and 0.493 on a wide (DECISIONS #30). So the ladder: build the close-up
family against the anchor, promote one of its members to anchor the mediums,
promote again for the wides. Each rung conditions on a reference of its own
framing.

That collapse was measured through the *latent* reference path (Flux Klein).
Phase 3 runs the *embedding* path instead - IP-Adapter FaceID, a pose-normalised
ArcFace vector rather than image tokens - which the research says should survive
a framing change where the latent path cannot. That is the untested claim on this
machine, and the wide family is where it gets tested.

**Two anchors, two different jobs.** Every candidate is scored against both:

    family anchor   what it was conditioned on. Measures whether this rung works.
    root anchor     the Phase 2 medoid. Measures whether it is still HER.

Acceptance gates on the **root**. Gating on the family anchor alone is how ladder
bootstrapping drifts: each rung passes against the rung below it, and family
three is a different woman from family one with no single step to blame. Both
numbers are recorded, because when they disagree the disagreement is the finding.

Everything is raw ArcFace cosine. `face_identity.face_identity_stability`
rescales 0.21-0.70 onto 0-1 for reporting; a raw 0.80 clamps to 1.0 there. The
two must never be compared to each other.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable, Sequence

import numpy as np

__all__ = [
    "ACCEPT_AT",
    "HOLD_AT",
    "LADDER",
    "MAX_FAMILY_SHARE",
    "PHASH_DISTANCE",
    "SEMANTIC_DUPLICATE",
    "Family",
    "ShotSpec",
    "balance",
    "classify",
    "find_phash_duplicates",
    "find_semantic_duplicates",
    "hamming",
    "phash",
    "plan_dataset",
]

#: Accept at or above, hold between, reject below. Raw ArcFace cosine against
#: the root anchor. The hold band exists because a 0.65 image is not evidence of
#: a different person, it is evidence of a hard framing - and throwing it away
#: silently would hide which framings are hard.
#:
#: **Recalibrated twice on 2026-08-26. Both moves are worth knowing about.**
#:
#: The runbook's 0.80 came from a *latent* reference measurement - Flux Klein at
#: 0.932 on matched framing (DECISIONS #30). The embedding path's ceiling here is
#: 0.786, so 0.80 was a gate nothing could pass: it would have rejected every
#: render, spent the whole budget and produced nothing.
#:
#: 0.70 replaced it, calibrated against the *maximum-strength* setting. But the
#: dataset now runs at `lora_strength` 0.3 - the gentlest reference that works,
#: chosen because stronger settings idealise skin and the LoRA learns whatever
#: texture it is shown. Measured on the real dataset prompts at that strength:
#:
#:     close_up   mean 0.667   range 0.615-0.740
#:     medium     mean 0.623   range 0.590-0.669
#:     wide       mean 0.523   range 0.437-0.632
#:
#: So 0.55. It clears close-ups and mediums comfortably and makes the wide family
#: the one that has to work for it, which matches where the difficulty actually
#: is. Crucially it is still far above what the same *varied* prompts reach with
#: no reference at all - mean 0.374, of which 1.5% cleared 0.55 across 65
#: renders. An accepted image is evidence the adapter did the work.
#:
#: The lesson underneath both moves: a band has to be calibrated against the
#: mechanism AND the prompts it will actually run on. The first recalibration
#: used the right mechanism at the wrong strength; an earlier yield estimate used
#: the right strength at the wrong prompts and predicted 23% where the truth was
#: 1.4%.
ACCEPT_AT = 0.55
HOLD_AT = 0.50

#: No family may exceed this share of the accepted set. An over-represented
#: framing becomes the LoRA's default output, which is the failure where the
#: model can only render the shot size you happened to have most of.
MAX_FAMILY_SHARE = 0.40

#: Perceptual-hash Hamming distance at or below which two renders are the same
#: picture. 64-bit hash; 6 bits is the conventional near-duplicate threshold.
PHASH_DISTANCE = 6

#: CLIP cosine above which two renders are the *same* image semantically even
#: when their pixels differ. A generated set's duplicates are semantic - the
#: same pose rendered twice - and pHash alone will not see them.
SEMANTIC_DUPLICATE = 0.95


@dataclass(frozen=True)
class Family:
    """One rung of the ladder."""

    name: str
    #: Phrased for an image model. Empty for the variation family, which borrows
    #: its framing from the three below it.
    shot: str
    target: int
    #: Which family's promoted image conditions this one. None = the root anchor.
    anchored_on: str | None = None
    #: Fraction of the denoising trajectory to withhold face conditioning for.
    #:
    #: Measured on this machine, 2026-08-26. Composition is decided early, so
    #: FaceID applied from step zero overrides the requested shot size: a wide
    #: shot came back with a face 2.9x larger than the same prompt rendered with
    #: no reference at all. Holding conditioning off until 0.4 cut that to 1.8x
    #: and cost nothing in identity (0.792 -> 0.750). Close-ups want 0.0 - there
    #: the prompt and the adapter want the same framing, and delaying only lets
    #: the composition wander (drift fell to 0.59x, i.e. too far out).
    start_at: float = 0.0


#: The runbook's quota table. 36 images: three framings plus a spread of
#: expression and lighting variation. Write the quotas down before generating
#: anything and treat them as a checklist - that is the instruction, and it is
#: what makes a shortfall visible instead of quietly rebalancing the set.
LADDER: tuple[Family, ...] = (
    Family("close_up", "close-up portrait, head and shoulders", 10, None, 0.0),
    Family("medium", "medium shot from the waist up", 10, "close_up", 0.2),
    Family("wide", "wide shot, full figure in the environment", 10, "medium", 0.4),
    Family("variation", "", 6, "close_up", 0.0),
)

#: Every image gets a different one. Anything held constant across the set is
#: learned as part of the character - a LoRA trained on forty workshop shots
#: puts her in a workshop whatever you prompt.
BACKGROUNDS: tuple[str, ...] = (
    "in a cluttered clockmaker's workshop, brass gears racked on the wall behind",
    "against a rain-streaked window at dusk",
    "in front of a towering orrery of brass rings",
    "beside a furnace throwing orange light",
    "in a narrow alley of soot-stained brick",
    "on a balcony overlooking a city of copper rooftops",
    "in a library of leather-bound ledgers",
    "against a plain slate-grey studio backdrop",
    "in an engine room of pistons and drifting steam",
    "beneath a vaulted glass roof in pale daylight",
    "in a fog-filled cobbled street at night",
    "beside a workbench scattered with tools and loose springs",
    "in front of a wall of ticking clock faces",
    "on the open deck of an airship, sky behind her",
    "in a cellar lit by one hanging bulb",
    "among sun-bleached canvas tents at a street market",
    "in a marble hall with tall arched windows",
    "beside a spiral iron staircase",
)

LIGHTING: tuple[str, ...] = (
    "soft key light with gentle falloff",
    "dramatic low-key lighting with deep shadows",
    "strong backlight with rim separation",
    "warm lamplight from below",
    "cool blue window light",
    "harsh directional sunlight",
    "flat overcast diffusion",
)

ANGLES: tuple[str, ...] = (
    "facing the camera straight on",
    "three-quarter view",
    "side profile",
)

EXPRESSIONS: tuple[str, ...] = (
    "neutral expression",
    "a faint smile",
    "a determined set to her jaw",
    "weary, eyes lowered",
    "curious, head tilted",
    "laughing",
    "guarded, chin raised",
    "caught mid-thought",
)

#: What her body is doing. Added 2026-08-27 after a FaceID-generated set came
#: back with every image the same standing three-quarter smile: a reference
#: adapter overrides pose the way it overrides framing, so unless the prompt
#: names an action explicitly the dataset collapses to one stance - and a LoRA
#: trained on one stance reproduces that stance whatever you ask it for.
POSES: tuple[str, ...] = (
    "standing, hands at her sides",
    "walking toward the camera",
    "sitting on a crate, leaning forward",
    "dancing, arms raised",
    "leaning against a wall, one knee bent",
    "looking back over her shoulder",
    "crouching, forearms on her knees",
    "arms folded",
    "turning, hair swinging",
    "sitting cross-legged on the ground",
    "stretching, arms overhead",
    "hands on hips",
)

#: Strides are coprime with the vocabulary lengths so the four axes cycle
#: independently: no two shots in a 36-image plan share the whole tuple.
_STRIDES = {"background": 1, "lighting": 3, "angle": 1, "expression": 5, "pose": 7}

#: A prime, like the anchor sweep's, so seeds do not land on sampler structure.
SEED_STEP = 1009


@dataclass(frozen=True)
class ShotSpec:
    """One image to generate: what varies, and the seed that makes it repeatable."""

    index: int
    family: str
    shot: str
    background: str
    lighting: str
    angle: str
    expression: str
    seed: int
    pose: str = ""

    def prompt(self, brief: str) -> str:
        parts = [
            str(brief).strip(),
            self.shot,
            self.pose,
            self.expression,
            self.background,
            self.lighting,
        ]
        return ". ".join(p for p in parts if p)

    def descriptor(self) -> dict[str, str]:
        """The varying axes, kept beside the image for Phase 4's captions.

        Phase 4 captions what varies and omits what is constant about her. That
        is far easier when generation already recorded which axes it moved -
        re-deriving "medium shot, three-quarter, backlit" from a PNG is a
        vision-model round trip we do not need to make.
        """
        return {
            "family": self.family,
            "shot": self.shot,
            "pose": self.pose,
            "expression": self.expression,
            "background": self.background,
            "lighting": self.lighting,
            "angle": self.angle,
        }


def plan_dataset(
    families: Sequence[Family] = LADDER,
    *,
    seed_base: int = 500_000,
    backgrounds: Sequence[str] = BACKGROUNDS,
    lighting: Sequence[str] = LIGHTING,
    expressions: Sequence[str] = EXPRESSIONS,
    poses: Sequence[str] = POSES,
) -> list[ShotSpec]:
    """Expand the quota table into concrete shots, varying every axis.

    The variation family has no framing of its own: it borrows the three real
    ones in rotation, so "expression and lighting variation" spreads across the
    set rather than becoming a fourth look.

    The vocabularies are parameters because they are the character's world,
    not the pipeline's: the defaults are a clockwork heroine's workshops and
    orreries, and a festival character needs the playa.
    """
    real_shots = [f.shot for f in families if f.shot]
    specs: list[ShotSpec] = []
    index = 0
    for family in families:
        for position in range(family.target):
            shot = family.shot or real_shots[position % len(real_shots)] if real_shots else ""
            specs.append(
                ShotSpec(
                    index=index,
                    family=family.name,
                    shot=shot,
                    background=backgrounds[(index * _STRIDES["background"]) % len(backgrounds)],
                    lighting=lighting[(index * _STRIDES["lighting"]) % len(lighting)],
                    angle=ANGLES[(index * _STRIDES["angle"]) % len(ANGLES)],
                    expression=expressions[(index * _STRIDES["expression"]) % len(expressions)],
                    pose=poses[(index * _STRIDES["pose"]) % len(poses)] if poses else "",
                    seed=seed_base + index * SEED_STEP,
                )
            )
            index += 1
    return specs


def classify(cosine: float | None, *, accept_at: float = ACCEPT_AT, hold_at: float = HOLD_AT) -> str:
    """accept / hold / reject / unmeasured, from a raw cosine against the root anchor."""
    if cosine is None:
        return "unmeasured"
    if cosine >= accept_at:
        return "accept"
    if cosine >= hold_at:
        return "hold"
    return "reject"


# ---------------------------------------------------------------------------
# duplicate detection
# ---------------------------------------------------------------------------

def phash(path: Path | str, *, hash_size: int = 8, highfreq_factor: int = 4) -> int | None:
    """64-bit perceptual hash. None when the image cannot be read.

    DCT-II of a downscaled greyscale image, keeping the low-frequency corner and
    thresholding on its median. Catches the near-identical render: same pose,
    same crop, one resampled or lightly regraded.
    """
    try:
        from PIL import Image
        from scipy.fft import dct
    except Exception:
        return None
    try:
        size = hash_size * highfreq_factor
        with Image.open(path) as handle:
            image = handle.convert("L").resize((size, size), Image.Resampling.LANCZOS)
        pixels = np.asarray(image, dtype=np.float64)
    except Exception:
        return None
    transformed = dct(dct(pixels, axis=0, norm="ortho"), axis=1, norm="ortho")
    low = transformed[:hash_size, :hash_size]
    # The DC term is overall brightness and would drag the median around, so it
    # is excluded from the threshold but still occupies its bit.
    median = float(np.median(low.flatten()[1:]))
    bits = (low > median).flatten()
    value = 0
    for bit in bits:
        value = (value << 1) | int(bit)
    return value


def hamming(left: int, right: int) -> int:
    return int(bin(left ^ right).count("1"))


def find_phash_duplicates(
    paths: Sequence[Path | str], *, distance: int = PHASH_DISTANCE
) -> list[tuple[int, int, int]]:
    """Index pairs whose perceptual hashes are within `distance` bits."""
    hashes = [phash(p) for p in paths]
    pairs: list[tuple[int, int, int]] = []
    for i in range(len(hashes)):
        if hashes[i] is None:
            continue
        for j in range(i + 1, len(hashes)):
            if hashes[j] is None:
                continue
            gap = hamming(hashes[i], hashes[j])
            if gap <= distance:
                pairs.append((i, j, gap))
    return pairs


def find_semantic_duplicates(
    paths: Sequence[Path | str], *, threshold: float = SEMANTIC_DUPLICATE
) -> list[tuple[int, int, float]]:
    """Index pairs whose CLIP embeddings agree above `threshold`.

    The second dedup axis, and the one that matters for a generated set. Two
    renders of the same pose from different seeds differ in every pixel and are
    still an unrequested repeat count in the training data. Returns [] when CLIP
    is unavailable rather than pretending the set is clean.
    """
    try:
        from lib.clip_embedder import embed_images
    except Exception:
        return []
    usable = [str(p) for p in paths if Path(p).is_file()]
    if len(usable) < 2:
        return []
    try:
        vectors = np.asarray(embed_images(usable), dtype=np.float32)
    except Exception:
        return []
    norms = np.linalg.norm(vectors, axis=1, keepdims=True)
    norms[norms == 0] = 1.0
    unit = vectors / norms
    gram = unit @ unit.T
    pairs: list[tuple[int, int, float]] = []
    for i in range(gram.shape[0]):
        for j in range(i + 1, gram.shape[0]):
            if float(gram[i, j]) > threshold:
                pairs.append((i, j, float(gram[i, j])))
    return pairs


# ---------------------------------------------------------------------------
# composition
# ---------------------------------------------------------------------------

def balance(family_names: Iterable[str], *, max_share: float = MAX_FAMILY_SHARE) -> dict[str, Any]:
    """Family shares of the accepted set, and which exceed the ceiling."""
    counts: dict[str, int] = {}
    for name in family_names:
        counts[name] = counts.get(name, 0) + 1
    total = sum(counts.values())
    shares = {name: (count / total if total else 0.0) for name, count in counts.items()}
    over = sorted(name for name, share in shares.items() if share > max_share)
    return {
        "total": total,
        "counts": counts,
        "shares": {name: round(share, 4) for name, share in shares.items()},
        "max_share": max_share,
        "over_represented": over,
        "balanced": not over,
    }


@dataclass
class DatasetEntry:
    """One generated candidate and everything measured about it."""

    spec: ShotSpec
    path: Path
    faces: int = 0
    cos_root: float | None = None
    cos_family: float | None = None
    #: Face box as a share of the frame. Not a quality score - the witness that
    #: the requested shot size actually happened. A calibration sweep once
    #: reported that wide shots held identity beautifully; they had all come back
    #: as portraits, and cosine alone could not see it.
    face_fraction: float | None = None
    verdict: str = "unmeasured"
    seconds: float = 0.0
    notes: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {
            "index": self.spec.index,
            "family": self.spec.family,
            "seed": self.spec.seed,
            "path": str(self.path),
            "faces": self.faces,
            "cos_root": None if self.cos_root is None else round(self.cos_root, 4),
            "cos_family": None if self.cos_family is None else round(self.cos_family, 4),
            "face_fraction": (
                None if self.face_fraction is None else round(self.face_fraction, 5)
            ),
            "verdict": self.verdict,
            "seconds": round(self.seconds, 2),
            "descriptor": self.spec.descriptor(),
            "notes": list(self.notes),
        }
