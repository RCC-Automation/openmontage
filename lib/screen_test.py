"""Screen test: casting a look by measured comparison rather than by squinting.

An actor's screen test is the same scene shot with several candidates so they
can be compared side by side before one is committed to the whole picture. This
is that, for generation stacks: run one character brief across a matrix of
models, LoRAs and settings, in the conditions the film will actually use, and
produce a ranked contact sheet plus a locked cast record.

**What this module will and will not judge.** It measures identity stability,
prompt adherence, technical quality and cost. It does not decide whether a face
is right for the part - that is taste, it is the whole job, and it stays with the
human. The ranking exists to remove candidates that were never viable, so the
person only spends their eyes on the ones worth looking at.

The metric that matters most is the one nobody tests for: **identity stability**.
A stack that produces one beautiful portrait but a different face every seed is
useless for a film, because that character has to appear in forty more shots.
"""

from __future__ import annotations

import hashlib
import itertools
import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

CAST_RECORD_VERSION = "1.0"

#: Shot sizes, lighting keys and angles worded for an image model. A face that
#: holds in close-up and falls apart in a wide shot is the wrong cast, so a
#: screen test covers a spread rather than one flattering portrait.
SHOT_SIZES: dict[str, str] = {
    "close_up": "close-up portrait, head and shoulders",
    "medium": "medium shot from the waist up",
    "wide": "wide shot, full figure in the environment",
}

LIGHTING: dict[str, str] = {
    "key": "soft key light, gentle falloff",
    "low_key": "dramatic low-key lighting with deep shadows",
    "backlit": "strong backlight with rim separation",
}

ANGLES: dict[str, str] = {
    "front": "facing the camera straight on",
    "three_quarter": "three-quarter view",
    "profile": "side profile",
}

DEFAULT_CONDITIONS: tuple[dict[str, str], ...] = (
    {"shot_size": "close_up", "lighting": "key", "angle": "front"},
    {"shot_size": "medium", "lighting": "low_key", "angle": "three_quarter"},
    {"shot_size": "wide", "lighting": "key", "angle": "front"},
)

#: The close-up is the single most diagnostic frame for a character - it is where
#: a model's handling of a face lives or dies - so a quick look uses only that.
_HEADLINE_CONDITION: dict[str, str] = {
    "shot_size": "close_up", "lighting": "key", "angle": "front"
}

#: Three rungs of the same ladder. Each is a different question, not just a
#: different size, and each says plainly what it cannot answer.
PRESETS: dict[str, dict[str, Any]] = {
    "quick": {
        "question": "what does each model do with my prompt?",
        "conditions": [dict(_HEADLINE_CONDITION)],
        "seeds": [7777],
        # One shared seed across every model is the whole point: same prompt,
        # same noise, only the model differs, so the comparison is clean.
        "settings": {
            "first_pass_width": 1024, "first_pass_height": 576,
            "second_pass_width": 1280, "second_pass_height": 720,
        },
        "cannot_measure": ["identity_stability"],
        "caveat": (
            "One seed per model compares looks; it cannot measure whether a model "
            "holds one identity across seeds. Use 'shortlist' before casting."
        ),
    },
    "shortlist": {
        "question": "which models hold an identity worth testing properly?",
        "conditions": [dict(_HEADLINE_CONDITION)],
        "seeds": [7777, 8888, 9999],
        "settings": {
            "first_pass_width": 1024, "first_pass_height": 576,
            "second_pass_width": 1280, "second_pass_height": 720,
        },
        "cannot_measure": [],
        "caveat": "One condition only - a face that holds in close-up may still fail in a wide.",
    },
    "full": {
        "question": "which stack should this character be cast with?",
        "conditions": [dict(c) for c in DEFAULT_CONDITIONS],
        "seeds": [7777, 8888, 9999],
        "settings": {},
        "cannot_measure": [],
        "caveat": "",
    },
}


def apply_preset(name: str, matrix: Mapping[str, Any], seeds: Sequence[int] | None):
    """Resolve a preset into conditions, seeds and setting overrides.

    Anything explicitly given by the caller wins over the preset, so a preset is
    a starting point rather than a cage.
    """
    if name not in PRESETS:
        raise ScreenTestError(
            f"unknown preset {name!r}; known: {', '.join(sorted(PRESETS))}"
        )
    preset = PRESETS[name]
    conditions = (
        resolve_conditions(matrix)
        if matrix.get("conditions")
        else [dict(c) for c in preset["conditions"]]
    )
    resolved_seeds = list(seeds) if seeds else list(preset["seeds"])
    settings = {**preset.get("settings", {}), **dict(matrix.get("settings") or {})}
    return conditions, resolved_seeds, settings, preset


class ScreenTestError(ValueError):
    """Raised when a screen-test matrix or result set cannot be interpreted."""


def slugify(value: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", str(value).strip().lower()).strip("-")
    return slug or "unnamed"


# ---------------------------------------------------------------------------
# the matrix
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class Candidate:
    """One generation stack under test: a model plus a LoRA configuration."""

    model: str
    loras: tuple[tuple[str, float], ...] = ()
    settings: tuple[tuple[str, Any], ...] = ()

    @property
    def id(self) -> str:
        """Short stable identity, safe as a filename and readable in a report."""
        lora_part = "+".join(f"{Path(n).stem}@{s:g}" for n, s in self.loras) or "none"
        digest = hashlib.sha1(repr((self.model, self.loras, self.settings)).encode()).hexdigest()[:6]
        return f"{slugify(Path(self.model).stem)}__{slugify(lora_part)}__{digest}"

    @property
    def label(self) -> str:
        if not self.loras:
            return Path(self.model).stem
        loras = ", ".join(f"{Path(n).stem} @ {s:g}" for n, s in self.loras)
        return f"{Path(self.model).stem} + {loras}"

    def as_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "label": self.label,
            "model": self.model,
            "loras": [{"name": n, "strength": s} for n, s in self.loras],
            "settings": dict(self.settings),
        }


def expand_matrix(spec: Mapping[str, Any]) -> list[Candidate]:
    """Turn a matrix spec into candidates.

    ``lora_sets`` is a list of LoRA *combinations*, not a list of LoRAs, because
    the thing under test is a whole stack. ``[[], [["a.safetensors", 0.6]]]``
    tests "no LoRA" against "a at 0.6".
    """
    models = spec.get("models")
    if not isinstance(models, list) or not models:
        raise ScreenTestError("matrix needs a non-empty 'models' list")

    lora_sets = spec.get("lora_sets") or [[]]
    if not isinstance(lora_sets, list):
        raise ScreenTestError("'lora_sets' must be a list of LoRA combinations")

    settings = spec.get("settings") or {}
    if not isinstance(settings, Mapping):
        raise ScreenTestError("'settings' must be an object")
    frozen_settings = tuple(sorted(settings.items()))

    candidates: list[Candidate] = []
    for model, lora_set in itertools.product(models, lora_sets):
        loras: list[tuple[str, float]] = []
        for entry in lora_set or []:
            if isinstance(entry, Mapping):
                loras.append((str(entry["name"]), float(entry.get("strength", 1.0))))
            elif isinstance(entry, (list, tuple)) and entry:
                loras.append((str(entry[0]), float(entry[1]) if len(entry) > 1 else 1.0))
            else:
                raise ScreenTestError(f"unreadable LoRA entry: {entry!r}")
        candidates.append(
            Candidate(model=str(model), loras=tuple(loras), settings=frozen_settings)
        )
    return candidates


def resolve_conditions(spec: Mapping[str, Any]) -> list[dict[str, str]]:
    conditions = spec.get("conditions")
    if conditions is None:
        return [dict(c) for c in DEFAULT_CONDITIONS]
    if not isinstance(conditions, list) or not conditions:
        raise ScreenTestError("'conditions' must be a non-empty list when given")
    resolved = []
    for c in conditions:
        if not isinstance(c, Mapping):
            raise ScreenTestError(f"unreadable condition: {c!r}")
        for axis, table in (("shot_size", SHOT_SIZES), ("lighting", LIGHTING), ("angle", ANGLES)):
            value = c.get(axis)
            if value is not None and value not in table:
                raise ScreenTestError(
                    f"unknown {axis} {value!r}; known: {', '.join(sorted(table))}"
                )
        resolved.append(dict(c))
    return resolved


def condition_id(condition: Mapping[str, str]) -> str:
    return "-".join(
        str(condition.get(axis, "any")) for axis in ("shot_size", "lighting", "angle")
    )


def build_prompt(character_brief: str, condition: Mapping[str, str]) -> str:
    """The character brief phrased for one shooting condition.

    Deliberately plain: the point of a screen test is to vary the *stack*, so
    everything else must stay identical between candidates.
    """
    parts = [str(character_brief).strip()]
    for axis, table in (("shot_size", SHOT_SIZES), ("lighting", LIGHTING), ("angle", ANGLES)):
        value = condition.get(axis)
        if value and value in table:
            parts.append(table[value])
    return ". ".join(p for p in parts if p)


# ---------------------------------------------------------------------------
# measurement
# ---------------------------------------------------------------------------

@dataclass
class Shot:
    """One rendered image in a screen test."""

    candidate_id: str
    condition: str
    seed: int
    path: Path
    seconds: float = 0.0


def _embeddings_available() -> bool:
    try:
        import torch  # noqa: F401
        import transformers  # noqa: F401
    except Exception:
        return False
    return True


def identity_stability(paths: Sequence[Path]) -> float | None:
    """How much the same character wanders across seeds. 0..1, higher is steadier.

    Mean pairwise cosine similarity of CLIP embeddings, rescaled so that the
    similarity range real faces occupy spreads across the scale. Returns None
    when embeddings are unavailable, so callers can report the gap rather than
    silently scoring on fewer axes.

    **This is the most important number in a screen test.** A stack that scores
    high here but merely good on looks beats a beautiful one that drifts,
    because the character has to survive the rest of the film.
    """
    usable = [p for p in paths if Path(p).is_file()]
    if len(usable) < 2 or not _embeddings_available():
        return None
    try:
        import numpy as np

        from lib.clip_embedder import embed_images

        vectors = embed_images(usable)
        similarities = []
        for i in range(len(vectors)):
            for j in range(i + 1, len(vectors)):
                similarities.append(float(np.dot(vectors[i], vectors[j])))
        if not similarities:
            return None
        mean = sum(similarities) / len(similarities)
    except Exception:
        return None
    # CLIP similarity between renders of one brief lives roughly in 0.6-1.0;
    # rescaling makes the differences that matter visible in the ranking.
    return max(0.0, min(1.0, (mean - 0.6) / 0.4))


def prompt_adherence(paths: Sequence[Path], prompt: str) -> float | None:
    """How well the renders match what was asked for. 0..1, or None if unavailable."""
    usable = [p for p in paths if Path(p).is_file()]
    if not usable or not _embeddings_available():
        return None
    try:
        import numpy as np

        from lib.clip_embedder import embed_images, embed_texts

        image_vectors = embed_images(usable)
        text_vector = embed_texts([prompt])[0]
        scores = [float(np.dot(v, text_vector)) for v in image_vectors]
        mean = sum(scores) / len(scores)
    except Exception:
        return None
    # CLIP text-image cosine sits far lower than image-image; 0.15-0.35 is the
    # working band for a detailed prompt.
    return max(0.0, min(1.0, (mean - 0.15) / 0.20))


# Detail measured on the sharpest tiles of the frame. Calibrated against eleven
# real renders from this machine: eight good ones (soft and crisp alike) fall
# between 0.0040 and 0.0137, while two colour-blown and one artefacted render
# sit between 0.0436 and 0.0612 - an order of magnitude clear, no overlap.
_BLURRED, _PLAUSIBLE_LOW, _PLAUSIBLE_HIGH, _NOISY = 0.0015, 0.0035, 0.020, 0.035


def subject_detail(path: Path) -> float | None:
    """High-frequency energy where the frame is sharpest, or None if unreadable.

    Whole-frame variance measures the wrong thing for portraiture: a shallow
    depth of field puts most of the image out of focus on purpose, so bokeh -
    a virtue - reads as blur. Tiling the frame and taking a high percentile
    finds whatever is actually in focus and ignores how much of the rest is not.
    """
    try:
        import numpy as np
        from PIL import Image

        with Image.open(path) as handle:
            grey = handle.convert("L")
            grey.thumbnail((768, 768))
            pixels = np.asarray(grey, dtype=np.float32) / 255.0
    except Exception:
        return None
    if pixels.size == 0 or pixels.std() < 0.01:
        return 0.0                                   # blank, flat or blown out
    laplacian = (
        -4 * pixels[1:-1, 1:-1]
        + pixels[:-2, 1:-1] + pixels[2:, 1:-1]
        + pixels[1:-1, :-2] + pixels[1:-1, 2:]
    )
    import numpy as np

    grid = 8
    height, width = laplacian.shape
    tile_h, tile_w = height // grid, width // grid
    if tile_h < 2 or tile_w < 2:
        return float(laplacian.var())
    tiles = [
        laplacian[r * tile_h:(r + 1) * tile_h, c * tile_w:(c + 1) * tile_w].var()
        for r in range(grid) for c in range(grid)
    ]
    return float(np.percentile(tiles, 90))


def technical_score(path: Path) -> float | None:
    """Whether an image is technically usable at all. 0..1, or None if unreadable.

    Deliberately a gate, not a ranking. Detail does not measure quality: a soft
    filmic portrait and a crisp editorial one are both correct, and which you
    want is a casting decision, not a measurement (DECISIONS.md #15). Scoring
    them against each other buried the two renders the human actually chose in
    11th and 12th place, while an artefacted render took the top score because
    speckle is high-frequency.

    So anything inside the band real renders occupy scores 1.0, and the axis
    only speaks up for output that is genuinely broken - blank, blurred, or
    noise-blasted. Ranking among usable images is left to the axes that can
    justify an opinion, and to the person looking at the sheet.
    """
    detail = subject_detail(path)
    if detail is None:
        return None
    if detail <= _BLURRED or detail >= _NOISY:
        return 0.0
    if detail < _PLAUSIBLE_LOW:                      # ramp out of "blurred"
        return (detail - _BLURRED) / (_PLAUSIBLE_LOW - _BLURRED)
    if detail <= _PLAUSIBLE_HIGH:
        return 1.0                                   # plausible: no opinion
    return 1.0 - (detail - _PLAUSIBLE_HIGH) / (_NOISY - _PLAUSIBLE_HIGH)


# ---------------------------------------------------------------------------
# ranking
# ---------------------------------------------------------------------------

DEFAULT_WEIGHTS: dict[str, float] = {
    "identity_stability": 0.45,
    "prompt_adherence": 0.25,
    "technical": 0.20,
    "speed": 0.10,
}


@dataclass
class CandidateResult:
    candidate: Candidate
    shots: list[Shot] = field(default_factory=list)
    scores: dict[str, float | None] = field(default_factory=dict)
    total: float = 0.0
    notes: list[str] = field(default_factory=list)

    @property
    def seconds_per_image(self) -> float:
        if not self.shots:
            return 0.0
        return sum(s.seconds for s in self.shots) / len(self.shots)

    def explain(self) -> str:
        parts = []
        for axis in ("identity_stability", "prompt_adherence", "technical", "speed"):
            value = self.scores.get(axis)
            parts.append(f"{axis}={'n/a' if value is None else f'{value:.2f}'}")
        return f"{self.total:.3f}  " + "  ".join(parts)


def score_candidates(
    results: Sequence[CandidateResult],
    *,
    prompt: str,
    weights: Mapping[str, float] | None = None,
    skip: Sequence[str] = (),
) -> list[CandidateResult]:
    """Measure and rank. Unavailable axes are dropped and the rest reweighted.

    Never invents a value for a metric it could not compute - a missing axis is
    reported in `notes` so the human knows the ranking rests on less.
    """
    weights = dict(weights or DEFAULT_WEIGHTS)
    slowest = max((r.seconds_per_image for r in results), default=0.0)

    for result in results:
        paths = [s.path for s in result.shots]
        result.scores["identity_stability"] = (
            None if "identity_stability" in skip else identity_stability(paths)
        )
        result.scores["prompt_adherence"] = (
            None if "prompt_adherence" in skip else prompt_adherence(paths, prompt)
        )

        technicals = [t for t in (technical_score(p) for p in paths) if t is not None]
        result.scores["technical"] = (
            sum(technicals) / len(technicals) if technicals else None
        )
        result.scores["speed"] = (
            1.0 - (result.seconds_per_image / slowest) if slowest > 0 else None
        )

        available = {k: v for k, v in result.scores.items() if v is not None}
        missing = [k for k, v in result.scores.items() if v is None and k not in skip]
        if skip:
            result.notes.append(
                "not applicable at this preset: " + ", ".join(sorted(skip))
            )
        if missing:
            result.notes.append(
                "not measured: " + ", ".join(sorted(missing))
                + (
                    " (CLIP unavailable - install torch and transformers to score "
                    "identity stability and prompt adherence)"
                    if not _embeddings_available()
                    else ""
                )
            )
        weight_sum = sum(weights.get(k, 0.0) for k in available) or 1.0
        result.total = sum(
            value * weights.get(axis, 0.0) for axis, value in available.items()
        ) / weight_sum

    return sorted(results, key=lambda r: r.total, reverse=True)


def shortlist(ranked: Sequence[CandidateResult], keep: int = 8) -> list[CandidateResult]:
    """The candidates worth a human's eyes. Never picks a winner."""
    return list(ranked[:keep])


# ---------------------------------------------------------------------------
# the cast record
# ---------------------------------------------------------------------------

def cast_record(
    character: str,
    brief: str,
    result: CandidateResult,
    *,
    reference_path: str | Path,
    seed: int,
) -> dict[str, Any]:
    """Lock a chosen look so every later shot can be generated against it.

    Casting is not choosing a model - it is fixing an identity. This record is
    what the continuity check later measures drift from.
    """
    return {
        "version": CAST_RECORD_VERSION,
        "character": character,
        "brief": brief,
        "candidate": result.candidate.as_dict(),
        "seed": seed,
        "reference": str(reference_path),
        "measured": {k: v for k, v in result.scores.items() if v is not None},
        "seconds_per_image": round(result.seconds_per_image, 1),
        "chosen_by": "human",
    }


def contact_sheet(
    ranked: Sequence[CandidateResult], destination: Path, *, columns: int = 4
) -> Path | None:
    """A grid of one representative render per candidate, best first.

    The artefact the human actually judges from. Returns None if Pillow cannot
    build it, which is not fatal - the report still lists every path.
    """
    try:
        from PIL import Image, ImageDraw
    except Exception:
        return None

    picks: list[tuple[CandidateResult, Path]] = []
    for result in ranked:
        existing = [s.path for s in result.shots if Path(s.path).is_file()]
        if existing:
            picks.append((result, Path(existing[0])))
    if not picks:
        return None

    cell_w, cell_h, label_h, pad = 384, 384, 34, 8
    columns = max(1, columns)
    rows = (len(picks) + columns - 1) // columns
    sheet = Image.new(
        "RGB",
        (columns * (cell_w + pad) + pad, rows * (cell_h + label_h + pad) + pad),
        (18, 18, 22),
    )
    draw = ImageDraw.Draw(sheet)

    for index, (result, path) in enumerate(picks):
        col, row = index % columns, index // columns
        x = pad + col * (cell_w + pad)
        y = pad + row * (cell_h + label_h + pad)
        try:
            with Image.open(path) as img:
                img = img.convert("RGB")
                img.thumbnail((cell_w, cell_h))
                sheet.paste(img, (x + (cell_w - img.width) // 2, y))
        except Exception:
            draw.rectangle([x, y, x + cell_w, y + cell_h], fill=(40, 40, 46))
        caption = f"{index + 1}. {result.candidate.label}"[:58]
        draw.text((x + 2, y + cell_h + 4), caption, fill=(225, 225, 232))
        draw.text((x + 2, y + cell_h + 18), result.explain()[:58], fill=(150, 150, 162))

    destination.parent.mkdir(parents=True, exist_ok=True)
    sheet.save(destination)
    return destination


def write_report(
    destination: Path,
    *,
    character: str,
    brief: str,
    ranked: Sequence[CandidateResult],
    conditions: Sequence[Mapping[str, str]],
    seeds: Sequence[int],
    elapsed_minutes: float,
    contact_sheet_path: Path | None,
) -> Path:
    payload = {
        "version": "1.0",
        "character": character,
        "brief": brief,
        "conditions": [dict(c) for c in conditions],
        "seeds": list(seeds),
        "elapsed_minutes": round(elapsed_minutes, 1),
        "contact_sheet": str(contact_sheet_path) if contact_sheet_path else None,
        "decided_by": "human - this report ranks and eliminates, it does not choose",
        "candidates": [
            {
                **result.candidate.as_dict(),
                "rank": index + 1,
                "total": round(result.total, 4),
                "scores": {
                    k: (None if v is None else round(v, 4)) for k, v in result.scores.items()
                },
                "seconds_per_image": round(result.seconds_per_image, 1),
                "notes": result.notes,
                "shots": [
                    {"condition": s.condition, "seed": s.seed, "path": str(s.path)}
                    for s in result.shots
                ],
            }
            for index, result in enumerate(ranked)
        ],
    }
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    return destination


def comparison_sheet(
    ranked: Sequence[CandidateResult],
    destination: Path,
    *,
    prompt: str,
    seed: int | None = None,
    columns: int = 3,
    cell: int = 512,
) -> Path | None:
    """A side-by-side model comparison, built to be read rather than skimmed.

    Different artefact from :func:`contact_sheet`. That one surveys a large sweep
    in small cells; this one answers "same prompt, same seed, what does each
    model do with it?" - so the cells are large, the model name sits above its
    image, and the shared prompt and seed are printed once at the top. Anyone
    opening the file later can see exactly what was held constant.
    """
    try:
        from PIL import Image, ImageDraw
    except Exception:
        return None

    picks: list[tuple[CandidateResult, Path]] = []
    for result in ranked:
        existing = [s.path for s in result.shots if Path(s.path).is_file()]
        if existing:
            picks.append((result, Path(existing[0])))
    if not picks:
        return None

    pad, name_h, foot_h = 14, 30, 26
    header_h = 74
    columns = max(1, min(columns, len(picks)))
    rows = (len(picks) + columns - 1) // columns
    width = columns * (cell + pad) + pad
    height = header_h + rows * (cell + name_h + foot_h + pad) + pad

    sheet = Image.new("RGB", (width, height), (16, 16, 20))
    draw = ImageDraw.Draw(sheet)

    draw.text((pad, 12), "Model comparison - same prompt, same seed", fill=(240, 240, 246))
    subtitle = prompt if len(prompt) <= 150 else prompt[:147] + "..."
    draw.text((pad, 32), subtitle, fill=(158, 158, 172))
    if seed is not None:
        draw.text((pad, 50), f"seed {seed}", fill=(158, 158, 172))
    draw.line([(pad, header_h - 6), (width - pad, header_h - 6)], fill=(52, 52, 62))

    for index, (result, path) in enumerate(picks):
        col, row = index % columns, index // columns
        x = pad + col * (cell + pad)
        y = header_h + row * (cell + name_h + foot_h + pad)

        name = Path(result.candidate.model).stem
        draw.text((x, y + 6), f"{index + 1}. {name}"[:60], fill=(238, 238, 244))

        box_top = y + name_h
        try:
            with Image.open(path) as img:
                img = img.convert("RGB")
                img.thumbnail((cell, cell))
                sheet.paste(img, (x + (cell - img.width) // 2, box_top + (cell - img.height) // 2))
        except Exception:
            draw.rectangle([x, box_top, x + cell, box_top + cell], fill=(38, 38, 46))
            draw.text((x + 8, box_top + 8), "image unreadable", fill=(200, 120, 120))

        technical = result.scores.get("technical")
        adherence = result.scores.get("prompt_adherence")
        footer = f"{result.seconds_per_image:.0f}s"
        if technical is not None:
            # The score is a gate, so printing it would read "1.00" beside every
            # usable image and say nothing. Flag only what it actually rejects.
            if technical < 1.0:
                footer += f"   TECHNICAL {technical:.2f}"
        if adherence is not None:
            footer += f"   prompt {adherence:.2f}"
        draw.text((x, box_top + cell + 6), footer, fill=(150, 150, 164))

    destination.parent.mkdir(parents=True, exist_ok=True)
    sheet.save(destination)
    return destination
