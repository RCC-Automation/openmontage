"""State for the loops where a human picks: casting, score, scene look.

Three of the film's ten steps are the same shape. The agent proposes a round of
candidates, the human reacts in their own words, that reaction becomes the next
round, and eventually they say "that's it". Only the subject changes - who she
is, what the film sounds like, what a scene looks like.

The shape is worth holding in one place because the *history* is the valuable
part. "More like #3, warmer, keep the collar" is a creative decision, and a
decision that vanishes when the terminal closes is a decision the record does
not have. A loop that cannot say why round 4 looks the way it does cannot be
resumed by anyone, including the person who ran it.

Two rules from the repo's constitution shape this file:

* **The machine narrows, the human picks** (DECISIONS #15). Nothing here
  chooses. A round can be ranked and scored; the pick is always recorded as
  having come from a person, and ``chosen_by`` says so.
* **Python is tools and persistence, never orchestration.** This module stores
  and reads. It has no idea what a round contains, how to build one, or when a
  loop should end - those are the skill's job.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping

SESSION_VERSION = "1.0"
SESSION_FILENAME = "session.json"

#: The three loops. The value is the subdirectory under the project, so a film
#: can carry a casting history and a scene-look history side by side without
#: either knowing about the other.
LOOP_KINDS = ("casting", "score", "scene_look")


class LoopSessionError(ValueError):
    """Raised when a loop session cannot be read or is asked for nonsense."""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


@dataclass
class Round:
    """One pass of narrow-and-show.

    ``candidates`` is whatever the loop's instrument produced - a screen test's
    ranked results, a set of generated tracks, a sheet of scene directions. This
    module never looks inside them, which is what lets one class serve loops
    that have nothing else in common.
    """

    number: int
    kind: str
    started: str = field(default_factory=_now)
    spec: dict[str, Any] = field(default_factory=dict)
    candidates: list[dict[str, Any]] = field(default_factory=list)
    contact_sheet: str | None = None
    #: What the human said, verbatim. Kept exactly as typed - paraphrasing a
    #: reaction into the parameters it produced loses the part a later reader
    #: needs, which is what they were reaching for.
    reaction: str | None = None
    #: What the skill did with that reaction. The pair (reaction, applied) is
    #: the audit trail: it shows both the intent and the interpretation, so a
    #: misreading is visible rather than buried in the next round's spec.
    applied: dict[str, Any] = field(default_factory=dict)
    #: Candidate ids the human favoured this round. Not a final pick.
    favourites: list[str] = field(default_factory=list)
    notes: str | None = None
    cost_usd: float = 0.0
    seconds: float = 0.0

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class LoopSession:
    """A whole loop: every round, every reaction, and the verdict if there is one."""

    kind: str
    project_dir: Path
    subject: str = ""
    brief: str = ""
    rounds: list[Round] = field(default_factory=list)
    verdict: dict[str, Any] | None = None
    created: str = field(default_factory=_now)
    updated: str = field(default_factory=_now)

    # -- lifecycle -------------------------------------------------------

    @classmethod
    def path_for(cls, project_dir: Path | str, kind: str) -> Path:
        if kind not in LOOP_KINDS:
            raise LoopSessionError(
                f"Unknown loop kind {kind!r}. Known: {', '.join(LOOP_KINDS)}"
            )
        return Path(project_dir) / kind / SESSION_FILENAME

    @classmethod
    def load(cls, project_dir: Path | str, kind: str) -> "LoopSession":
        """Read a loop, or start an empty one.

        A missing file is a loop that has not run yet, not an error - that is
        the normal state the first time a skill is invoked.
        """
        path = cls.path_for(project_dir, kind)
        if not path.is_file():
            return cls(kind=kind, project_dir=Path(project_dir))
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise LoopSessionError(f"Unreadable loop session at {path}: {exc}") from exc
        if not isinstance(data, dict):
            raise LoopSessionError(f"Loop session at {path} is not an object")
        session = cls(
            kind=data.get("kind", kind),
            project_dir=Path(project_dir),
            subject=data.get("subject", ""),
            brief=data.get("brief", ""),
            verdict=data.get("verdict"),
            created=data.get("created", _now()),
            updated=data.get("updated", _now()),
        )
        for raw in data.get("rounds", []) or []:
            if isinstance(raw, dict):
                session.rounds.append(Round(**{**Round(0, kind).as_dict(), **raw}))
        return session

    def save(self) -> Path:
        path = self.path_for(self.project_dir, self.kind)
        path.parent.mkdir(parents=True, exist_ok=True)
        self.updated = _now()
        path.write_text(json.dumps(self.as_dict(), indent=2), encoding="utf-8")
        return path

    def as_dict(self) -> dict[str, Any]:
        return {
            "version": SESSION_VERSION,
            "kind": self.kind,
            "subject": self.subject,
            "brief": self.brief,
            "created": self.created,
            "updated": self.updated,
            "rounds": [r.as_dict() for r in self.rounds],
            "verdict": self.verdict,
        }

    # -- rounds ----------------------------------------------------------

    def start_round(self, spec: Mapping[str, Any] | None = None) -> Round:
        """Open the next round. Numbering is 1-based and never reused."""
        if self.verdict is not None:
            raise LoopSessionError(
                f"This {self.kind} loop is already decided. Call reopen() first if "
                f"the verdict is being revisited - the history should show that it "
                f"was, not pretend the loop never ended."
            )
        rnd = Round(number=len(self.rounds) + 1, kind=self.kind, spec=dict(spec or {}))
        self.rounds.append(rnd)
        return rnd

    @property
    def current(self) -> Round | None:
        return self.rounds[-1] if self.rounds else None

    def record_reaction(
        self,
        reaction: str,
        *,
        applied: Mapping[str, Any] | None = None,
        favourites: Iterable[str] | None = None,
    ) -> Round:
        """Attach what the human said to the round they said it about.

        Both halves are kept: their words, and what the skill made of them.
        """
        rnd = self.current
        if rnd is None:
            raise LoopSessionError("No round to react to - start one first")
        rnd.reaction = reaction
        if applied is not None:
            rnd.applied = dict(applied)
        if favourites is not None:
            rnd.favourites = [str(f) for f in favourites]
        return rnd

    def decide(
        self, pick: Mapping[str, Any], *, chosen_by: str = "human", notes: str = ""
    ) -> dict[str, Any]:
        """Close the loop on a pick.

        ``chosen_by`` defaults to ``human`` because that is the only value that
        makes a verdict final (DECISIONS #15). An agent-chosen verdict is a
        draft, and recording it as anything else would let a ranking quietly
        become a decision.
        """
        if chosen_by not in {"human", "agent"}:
            raise LoopSessionError(
                f"chosen_by must be 'human' or 'agent', not {chosen_by!r}"
            )
        self.verdict = {
            "pick": dict(pick),
            "chosen_by": chosen_by,
            "decided": _now(),
            "after_rounds": len(self.rounds),
            "notes": notes,
        }
        return self.verdict

    def reopen(self, why: str = "") -> None:
        """Revisit a decided loop, leaving the trail visible.

        The old verdict is not deleted - it becomes a note on the round that
        was current when it was made. A history that quietly loses a reversed
        decision is worse than no history, because it reads as if the loop went
        straight there.
        """
        if self.verdict is None:
            return
        superseded = dict(self.verdict)
        superseded["superseded"] = _now()
        if why:
            superseded["why"] = why
        rnd = self.current
        if rnd is not None:
            rnd.notes = " | ".join(
                filter(None, [rnd.notes, f"verdict reopened: {json.dumps(superseded)}"])
            )
        self.verdict = None

    # -- reading ---------------------------------------------------------

    @property
    def decided(self) -> bool:
        return self.verdict is not None

    def total_cost_usd(self) -> float:
        return round(sum(r.cost_usd for r in self.rounds), 4)

    def total_seconds(self) -> float:
        return round(sum(r.seconds for r in self.rounds), 1)

    def favourites_so_far(self) -> list[str]:
        """Every candidate the human has favoured, newest first, deduplicated.

        The running shortlist a next round is usually built from.
        """
        seen: list[str] = []
        for rnd in reversed(self.rounds):
            for fav in rnd.favourites:
                if fav not in seen:
                    seen.append(fav)
        return seen

    def history(self) -> list[dict[str, str]]:
        """The loop as a person would retell it: round, what they said, what happened."""
        out: list[dict[str, str]] = []
        for rnd in self.rounds:
            out.append(
                {
                    "round": str(rnd.number),
                    "candidates": str(len(rnd.candidates)),
                    "reaction": rnd.reaction or "",
                    "applied": ", ".join(f"{k}={v}" for k, v in rnd.applied.items()),
                    "favourites": ", ".join(rnd.favourites),
                }
            )
        return out

    def summary(self) -> dict[str, Any]:
        """What a checkpoint or a board panel needs, without the candidate bulk."""
        return {
            "kind": self.kind,
            "subject": self.subject,
            "rounds": len(self.rounds),
            "decided": self.decided,
            "chosen_by": (self.verdict or {}).get("chosen_by"),
            "favourites": self.favourites_so_far(),
            "cost_usd": self.total_cost_usd(),
            "seconds": self.total_seconds(),
        }
