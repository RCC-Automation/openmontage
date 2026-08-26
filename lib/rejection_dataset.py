"""Phase 3 without a reference adapter: generate natively, keep what matches.

The ladder in `character_dataset` conditions each render on a reference face.
That reliably lifts identity - measured 0.413 with no reference to 0.745 at
`lora_strength` 1.0 - and it costs the thing the dataset exists to carry. Every
FaceID render on this machine came back glossier, warmer and more idealised than
the base model's own output: uniform skin tone where real skin is blotchy, heavy
specular sheen, freckles gone. A two-pass refinement at low denoise was tried and
kept the identity (0.735) without recovering any of the look.

**So the mechanism is inverted. Generate with nothing pulling on the model, and
use ArcFace as a filter rather than as a target.**

The reasoning is DECISIONS #38 applied one level down. That decision cast a model
that renders brass but drifts, because *identity is addable and the look is not*.
The same asymmetry decides this: the LoRA trained on this dataset is precisely
the thing that adds identity, and it cannot add realism it was never shown. A
dataset of plastic faces produces a model that can only render plastic faces.

What it costs, measured against the anchor over 48 description-only renders:

    threshold   pass rate   renders per 10 images
    0.55        38.3%       26
    0.60         6.4%       157
    0.65         0%         unreachable

So the band has to sit near 0.55, well below the 0.70 a reference could deliver.
That is the trade, stated rather than hidden. The dataset will be a looser
likeness of one person, every image of which looks photographed.

**Yield is the whole design problem here**, which is why this module is mostly
about accounting: how many renders a family costs, when to stop paying, and how
to report a family that could not be filled rather than quietly rebalancing the
quotas around it.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Sequence

import numpy as np

__all__ = [
    "REJECTION_ACCEPT",
    "REJECTION_HOLD",
    "FamilyBudget",
    "YieldEstimate",
    "estimate_yield",
    "plan_budget",
    "threshold_for_yield",
]

#: Raw ArcFace cosine against the anchor. Far below the reference-conditioned
#: bands in `character_dataset` and deliberately so - nothing generated without a
#: reference reached 0.65 in 48 attempts, so a higher band is not a stricter
#: standard, it is an empty dataset.
#:
#: 0.55 sits above the description-only population mean against the anchor
#: (0.522), so an accepted image is at least better than the average render of
#: the same prompt - and comfortably above the 0.10-0.21 different-people band.
REJECTION_ACCEPT = 0.55
REJECTION_HOLD = 0.50


@dataclass
class YieldEstimate:
    """What a threshold costs, from a measured population."""

    threshold: float
    pass_rate: float
    sample_size: int
    #: Renders needed per accepted image. Infinite when nothing passed, which is
    #: a real answer and not a division to be guarded away.
    cost_per_image: float

    @property
    def reachable(self) -> bool:
        return self.pass_rate > 0.0

    def renders_for(self, wanted: int) -> float:
        return float("inf") if not self.reachable else wanted * self.cost_per_image

    def as_dict(self) -> dict[str, Any]:
        return {
            "threshold": round(self.threshold, 3),
            "pass_rate": round(self.pass_rate, 4),
            "sample_size": self.sample_size,
            "cost_per_image": (
                None if not self.reachable else round(self.cost_per_image, 2)
            ),
            "reachable": self.reachable,
        }


def estimate_yield(
    similarities: Sequence[float], threshold: float
) -> YieldEstimate:
    """Pass rate and cost per image at a threshold, from observed scores."""
    values = np.asarray([s for s in similarities if s is not None], dtype=np.float64)
    if values.size == 0:
        return YieldEstimate(threshold, 0.0, 0, float("inf"))
    passed = int((values >= threshold).sum())
    rate = passed / values.size
    return YieldEstimate(
        threshold=threshold,
        pass_rate=rate,
        sample_size=int(values.size),
        cost_per_image=float("inf") if rate == 0 else 1.0 / rate,
    )


def threshold_for_yield(
    similarities: Sequence[float],
    *,
    min_rate: float = 0.2,
    candidates: Sequence[float] = (0.70, 0.65, 0.60, 0.575, 0.55, 0.525, 0.50),
) -> tuple[float, YieldEstimate]:
    """The strictest threshold whose yield is still affordable.

    Walks from strict to lenient and stops at the first that clears `min_rate`.
    This is the honest direction to search: it takes the best identity the
    population can actually supply, rather than picking a number first and
    discovering afterwards that nothing reaches it - which is exactly how the
    0.80 band from the runbook produced an empty dataset.
    """
    best = estimate_yield(similarities, candidates[-1])
    for threshold in candidates:
        estimate = estimate_yield(similarities, threshold)
        if estimate.pass_rate >= min_rate:
            return threshold, estimate
        best = estimate
    return candidates[-1], best


@dataclass
class FamilyBudget:
    """How many renders a family is allowed before it is declared short."""

    family: str
    wanted: int
    threshold: float
    estimate: YieldEstimate
    #: Headroom over the point estimate. A pass rate measured on 48 samples has
    #: real error, and a family that stops one image short because the estimate
    #: was slightly optimistic wastes the whole run.
    slack: float = 1.6
    spent: int = 0
    accepted: int = 0
    notes: list[str] = field(default_factory=list)

    @property
    def budget(self) -> int:
        if not self.estimate.reachable:
            # Unmeasured or unreachable: allow a fixed exploration rather than
            # zero. A family with no prior is not a family that cannot be filled.
            return self.wanted * 12
        return int(round(self.estimate.renders_for(self.wanted) * self.slack))

    @property
    def exhausted(self) -> bool:
        return self.spent >= self.budget

    @property
    def complete(self) -> bool:
        return self.accepted >= self.wanted

    def as_dict(self) -> dict[str, Any]:
        return {
            "family": self.family,
            "wanted": self.wanted,
            "accepted": self.accepted,
            "threshold": round(self.threshold, 3),
            "renders_spent": self.spent,
            "budget": self.budget,
            "short_by": max(0, self.wanted - self.accepted),
            "yield": self.estimate.as_dict(),
            "notes": list(self.notes),
        }


def plan_budget(
    families: Sequence[tuple[str, int]],
    similarities: Sequence[float],
    *,
    threshold: float = REJECTION_ACCEPT,
    slack: float = 1.6,
    penalty: dict[str, float] | None = None,
) -> list[FamilyBudget]:
    """A render budget per family, from one measured population.

    `penalty` scales the expected yield per family, because the measured
    population is close-ups at the anchor's own condition and every other framing
    is harder: changing the prompt drifts the face more than changing the seed
    does (DECISIONS #29). Without it the wide family would be given a close-up's
    budget and reported as a failure when it was simply underfunded.
    """
    penalty = penalty or {}
    budgets: list[FamilyBudget] = []
    for name, wanted in families:
        estimate = estimate_yield(similarities, threshold)
        factor = float(penalty.get(name, 1.0))
        if factor != 1.0 and estimate.reachable:
            estimate = YieldEstimate(
                threshold=estimate.threshold,
                pass_rate=estimate.pass_rate * factor,
                sample_size=estimate.sample_size,
                cost_per_image=estimate.cost_per_image / factor,
            )
        budget = FamilyBudget(
            family=name,
            wanted=wanted,
            threshold=threshold,
            estimate=estimate,
            slack=slack,
        )
        if factor != 1.0:
            budget.notes.append(
                f"expected yield scaled by {factor:g} - this framing is not the "
                "one the pass rate was measured on"
            )
        budgets.append(budget)
    return budgets
