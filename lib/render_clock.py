"""Render clock: budgeting local generation in GPU-minutes instead of dollars.

`tools/cost_tracker.py` budgets money. On a workstation doing local generation
the money is zero and the real currency is **time** - a Z-Image still is a
couple of minutes, a two-pass 14B video clip can be an hour. Nothing else in the
repo knows that, so nothing can answer the question that actually shapes an
evening's work: *this plan needs eleven hours and you have four; what do we cut?*

Two design choices matter:

**Estimates are measured, not guessed.** Every `BaseTool.execute()` already
appends `duration_s` to `projects/<id>/events.jsonl`. This module learns from
that history, so the numbers describe *this* machine rather than a generic one.
A seeded baseline from the first validated runs means it is useful before it has
learned anything.

**An unknown route stays unknown.** A route never run here produces no estimate
and is reported as such. Inventing a plausible number is worse than admitting the
gap, because the whole point is to make a plan's cost honest.
"""

from __future__ import annotations

import json
import math
import statistics
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

from lib.paths import PROJECTS_DIR

TIMINGS_VERSION = "1.0"

#: Timings are a property of the machine, not of one film, so they live beside
#: the projects rather than inside one.
DEFAULT_TIMINGS_PATH = PROJECTS_DIR / "_machine" / "render_timings.json"

#: Below this many samples an estimate is a hint, not a number to plan against.
_CONFIDENT_SAMPLES = 5

#: Real measurements from this workstation (AMD 8060S / ROCm 7.14), taken from
#: docs/COMFYUI_LOCAL_VALIDATION.md and the first VRGDG builder run. Seeded so a
#: fresh install can estimate immediately; measured samples outweigh these as
#: soon as any arrive.
BASELINE_SAMPLES: tuple[dict[str, Any], ...] = (
    {"route_key": "comfyui_image:vrgdg:zimage", "seconds": 161.6, "pixels": 1920 * 1080},
    {"route_key": "comfyui_image:custom:flux", "seconds": 115.4, "pixels": 768 * 1024},
    {"route_key": "comfyui_image:custom:flux", "seconds": 97.7, "pixels": 768 * 1024},
    {"route_key": "comfyui_video:custom:wan22-i2v", "seconds": 212.9, "pixels": 640 * 640, "frames": 81},
    {"route_key": "comfyui_video:custom:wan22-flf2v", "seconds": 178.9, "pixels": 640 * 640, "frames": 81},
    {"route_key": "comfyui_video:custom:wan-animate2", "seconds": 239.1, "pixels": 640 * 640, "frames": 81},
    {"route_key": "comfyui_video:custom:wan21-scail2", "seconds": 3963.8, "pixels": 640 * 640, "frames": 81},
)


def route_key(tool: str, source: str, variant: str) -> str:
    """Stable identity for a thing that takes time.

    ``source`` distinguishes how the graph was obtained (``vrgdg``, ``custom``,
    ``bundled``) because the same model through a different graph can have a
    very different cost.
    """
    return f"{tool}:{source}:{variant}"


# ---------------------------------------------------------------------------
# estimates
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class RouteEstimate:
    """What we expect one render on this route to cost, and how sure we are."""

    route_key: str
    samples: int
    seconds: float
    spread_seconds: float          # p80 - median; how unpredictable this route is
    scaled_by_pixels: bool
    known: bool = True

    @property
    def confident(self) -> bool:
        return self.known and self.samples >= _CONFIDENT_SAMPLES

    @property
    def minutes(self) -> float:
        return self.seconds / 60.0

    def describe(self) -> str:
        if not self.known:
            return f"{self.route_key}: never run here - no estimate"
        basis = "scaled by resolution" if self.scaled_by_pixels else "flat median"
        certainty = "" if self.confident else f", low confidence ({self.samples} sample(s))"
        return (
            f"{self.route_key}: ~{self.minutes:.1f} min ({basis}{certainty})"
        )


UNKNOWN = RouteEstimate(
    route_key="", samples=0, seconds=0.0, spread_seconds=0.0,
    scaled_by_pixels=False, known=False,
)


# ---------------------------------------------------------------------------
# the measured history
# ---------------------------------------------------------------------------

class RenderTimings:
    """Measured render durations for this machine, with persistence."""

    def __init__(self, samples: Iterable[Mapping[str, Any]] | None = None) -> None:
        self._samples: list[dict[str, Any]] = [dict(s) for s in (samples or ())]
        self._seen_events: set[str] = set()

    # -- persistence ---------------------------------------------------

    @classmethod
    def load(cls, path: Path | str | None = None) -> "RenderTimings":
        """Load stored timings, falling back to the seeded baseline."""
        target = Path(path or DEFAULT_TIMINGS_PATH)
        if not target.is_file():
            return cls(BASELINE_SAMPLES)
        try:
            payload = json.loads(target.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            # A corrupt timings file must never block a render.
            return cls(BASELINE_SAMPLES)
        instance = cls(payload.get("samples") or ())
        instance._seen_events = set(payload.get("seen_events") or ())
        if not instance._samples:
            instance._samples = [dict(s) for s in BASELINE_SAMPLES]
        return instance

    def save(self, path: Path | str | None = None) -> Path:
        target = Path(path or DEFAULT_TIMINGS_PATH)
        target.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "version": TIMINGS_VERSION,
            "updated": datetime.now(timezone.utc).isoformat(),
            "samples": self._samples[-2000:],       # bounded; old runs stop mattering
            "seen_events": sorted(self._seen_events)[-5000:],
        }
        target.write_text(
            json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
        )
        return target

    # -- recording -----------------------------------------------------

    def record(
        self,
        key: str,
        seconds: float,
        *,
        pixels: int | None = None,
        frames: int | None = None,
        event_id: str | None = None,
    ) -> bool:
        """Add one measurement. Returns False if it was a duplicate or nonsense."""
        if seconds <= 0 or not math.isfinite(seconds):
            return False
        if event_id is not None:
            if event_id in self._seen_events:
                return False
            self._seen_events.add(event_id)
        sample: dict[str, Any] = {"route_key": key, "seconds": float(seconds)}
        if pixels:
            sample["pixels"] = int(pixels)
        if frames:
            sample["frames"] = int(frames)
        self._samples.append(sample)
        return True

    def learn_from_events(self, project_dir: Path | str, *, source: str = "custom") -> int:
        """Ingest `duration_s` from a project's event stream. Returns new samples.

        Events carry the tool name but not which graph produced the render, so
        without better information they are filed under *source*. Callers that
        know the route should prefer :meth:`record`.
        """
        events_path = Path(project_dir) / "events.jsonl"
        if not events_path.is_file():
            return 0
        added = 0
        for line in events_path.read_text(encoding="utf-8", errors="replace").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                continue
            if event.get("event") != "finish" or not event.get("success"):
                continue
            duration = event.get("duration_s")
            tool = event.get("tool")
            if not isinstance(duration, (int, float)) or not isinstance(tool, str):
                continue
            marker = f"{event.get('ts')}|{tool}|{event.get('output_path')}"
            if self.record(
                route_key(tool, source, "unknown"), float(duration), event_id=marker
            ):
                added += 1
        return added

    # -- estimating ----------------------------------------------------

    def estimate(
        self, key: str, *, pixels: int | None = None, frames: int | None = None
    ) -> RouteEstimate:
        """Expected seconds for one render on this route."""
        matching = [s for s in self._samples if s.get("route_key") == key]
        if not matching:
            return RouteEstimate(key, 0, 0.0, 0.0, False, known=False)

        durations = [float(s["seconds"]) for s in matching]
        median = statistics.median(durations)
        spread = max(0.0, _percentile(durations, 0.8) - median)

        # Scale by pixel count only when the history actually spans resolutions;
        # extrapolating from a single resolution is a guess wearing a formula.
        scaled = False
        with_pixels = [s for s in matching if s.get("pixels")]
        if pixels and len(with_pixels) >= 2:
            ratios = {s["pixels"] for s in with_pixels}
            if len(ratios) >= 2:
                per_pixel = statistics.median(
                    float(s["seconds"]) / float(s["pixels"]) for s in with_pixels
                )
                median = per_pixel * pixels
                scaled = True

        # Frame count is close to linear for video; scale when the sample says so.
        sample_frames = statistics.median(
            [float(s["frames"]) for s in matching if s.get("frames")] or [0.0]
        )
        if frames and sample_frames > 0:
            median *= frames / sample_frames

        return RouteEstimate(key, len(matching), median, spread, scaled)

    def known_routes(self) -> list[str]:
        return sorted({s["route_key"] for s in self._samples if s.get("route_key")})


def _percentile(values: Sequence[float], q: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    index = min(len(ordered) - 1, max(0, int(round(q * (len(ordered) - 1)))))
    return ordered[index]


# ---------------------------------------------------------------------------
# plans and budgets
# ---------------------------------------------------------------------------

@dataclass
class PlanItem:
    """One line of intended work: N renders on one route."""

    label: str
    route_key: str
    count: int = 1
    pixels: int | None = None
    frames: int | None = None


@dataclass
class PlanLine:
    item: PlanItem
    estimate: RouteEstimate

    @property
    def total_seconds(self) -> float:
        return self.estimate.seconds * self.item.count

    @property
    def total_minutes(self) -> float:
        return self.total_seconds / 60.0


@dataclass
class PlanCost:
    lines: list[PlanLine] = field(default_factory=list)

    @property
    def known_lines(self) -> list[PlanLine]:
        return [l for l in self.lines if l.estimate.known]

    @property
    def unknown_lines(self) -> list[PlanLine]:
        return [l for l in self.lines if not l.estimate.known]

    @property
    def total_minutes(self) -> float:
        return sum(l.total_minutes for l in self.known_lines)

    @property
    def renders(self) -> int:
        return sum(l.item.count for l in self.lines)

    @property
    def has_unknowns(self) -> bool:
        return bool(self.unknown_lines)

    @property
    def low_confidence(self) -> bool:
        return any(not l.estimate.confident for l in self.known_lines)

    def heaviest(self, n: int = 3) -> list[PlanLine]:
        return sorted(self.known_lines, key=lambda l: l.total_seconds, reverse=True)[:n]


def estimate_plan(timings: RenderTimings, items: Sequence[PlanItem]) -> PlanCost:
    """Cost a list of intended renders against measured history."""
    return PlanCost(
        [
            PlanLine(item, timings.estimate(item.route_key, pixels=item.pixels, frames=item.frames))
            for item in items
        ]
    )


@dataclass
class BudgetVerdict:
    fits: bool
    budget_minutes: float
    plan_minutes: float
    over_by_minutes: float
    warnings: list[str] = field(default_factory=list)
    suggestions: list[str] = field(default_factory=list)

    def describe(self) -> str:
        head = (
            f"{self.plan_minutes:.0f} min of work against a {self.budget_minutes:.0f} min budget"
        )
        if self.fits:
            head += f" - fits, {self.budget_minutes - self.plan_minutes:.0f} min spare"
        else:
            head += f" - over by {self.over_by_minutes:.0f} min"
        parts = [head]
        parts += [f"  ! {w}" for w in self.warnings]
        parts += [f"  > {s}" for s in self.suggestions]
        return "\n".join(parts)


def check_budget(cost: PlanCost, budget_minutes: float) -> BudgetVerdict:
    """Does this plan fit, and if not, what would help?

    Suggestions name the specific heavy lines rather than advising "do less",
    because the useful decision is always *which* item to cut.
    """
    plan_minutes = cost.total_minutes
    over = max(0.0, plan_minutes - budget_minutes)
    warnings: list[str] = []
    suggestions: list[str] = []

    if cost.has_unknowns:
        names = ", ".join(sorted({l.item.route_key for l in cost.unknown_lines}))
        warnings.append(
            f"{len(cost.unknown_lines)} line(s) have never run on this machine "
            f"({names}); the real total will be higher than {plan_minutes:.0f} min"
        )
    if cost.low_confidence:
        warnings.append(
            "some estimates rest on fewer than "
            f"{_CONFIDENT_SAMPLES} samples - treat the total as a rough figure"
        )

    if over > 0:
        for line in cost.heaviest(3):
            share = line.total_minutes / plan_minutes if plan_minutes else 0
            suggestions.append(
                f"'{line.item.label}' is {line.total_minutes:.0f} min "
                f"({share:.0%} of the plan) - dropping it saves {line.total_minutes:.0f} min"
            )
        halved = plan_minutes / 2
        if halved <= budget_minutes:
            suggestions.append(
                "halving the seed count per candidate would bring the plan inside the budget"
            )

    return BudgetVerdict(
        fits=over <= 0,
        budget_minutes=budget_minutes,
        plan_minutes=plan_minutes,
        over_by_minutes=over,
        warnings=warnings,
        suggestions=suggestions,
    )


@dataclass
class RenderBudget:
    """A spend-down clock for one working session."""

    total_minutes: float
    spent_seconds: float = 0.0

    @property
    def spent_minutes(self) -> float:
        return self.spent_seconds / 60.0

    @property
    def remaining_minutes(self) -> float:
        return max(0.0, self.total_minutes - self.spent_minutes)

    @property
    def exhausted(self) -> bool:
        return self.remaining_minutes <= 0

    def spend(self, seconds: float) -> None:
        self.spent_seconds += max(0.0, seconds)

    def affords(self, estimate: RouteEstimate) -> bool:
        """Whether one more render of this kind fits in what is left.

        An unknown route is allowed through - refusing to run the very thing
        that would teach the clock its cost would make it permanently blind.
        """
        if not estimate.known:
            return not self.exhausted
        return estimate.minutes <= self.remaining_minutes

    def describe(self) -> str:
        return (
            f"{self.spent_minutes:.0f} of {self.total_minutes:.0f} min used, "
            f"{self.remaining_minutes:.0f} min left"
        )
