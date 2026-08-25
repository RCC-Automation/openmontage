"""Run one round of casting, or react to the last one.

    python scripts/casting_round.py --project casting-wp2 --character Heroine \\
        --brief "a clockwork heroine with luminous pink hair..."

    python scripts/casting_round.py --project casting-wp2 --react "more like #3, warmer, keep the collar"

    python scripts/casting_round.py --project casting-wp2 --show
    python scripts/casting_round.py --project casting-wp2 --decide 3 --notes "that's her"

The loop is: propose a round, show a sheet, hear a reaction, propose the next
one. This script is the turn-taking around `screen_test`; the translation from
words to a matrix lives in `lib/casting_loop`, and the history in
`lib/loop_session`.

Nothing here decides. `--decide` records a choice a person made.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from lib.casting_loop import interpret, next_brief, next_matrix, phone_sheet  # noqa: E402
from lib.checkpoint import init_project  # noqa: E402
from lib.loop_session import LoopSession  # noqa: E402
from lib.model_registry import (  # noqa: E402
    ModelRegistry,
    default_ledger_path,
    default_models_root,
)
from tools._comfyui.client import ComfyUIClient  # noqa: E402
from tools._comfyui.vrgdg import VRGDGClient  # noqa: E402
from tools.graphics.screen_test import ScreenTest  # noqa: E402

#: Above this many renders in one round, warn. Not a limit - the render clock
#: owns budgeting - just the point past which a mixed-family round has actually
#: taken this machine's backend down.
_RENDERS_BEFORE_A_WARNING = 9


def _report(project_dir: Path) -> dict:
    """The newest casting report under the project, or an empty one."""
    reports = sorted(
        project_dir.glob("casting/**/casting_report.json"),
        key=lambda p: p.stat().st_mtime,
    )
    if not reports:
        return {}
    return json.loads(reports[-1].read_text(encoding="utf-8"))


def _picks_from_report(report: dict) -> list[tuple[str, str, str]]:
    """(image, label, detail) per candidate, in the report's ranked order.

    Sheet position is what a human types back, so the order here *is* the
    numbering. It must not be re-sorted after the sheet is built.
    """
    out: list[tuple[str, str, str]] = []
    for entry in report.get("candidates", []) or []:
        shots = entry.get("shots") or []
        image = next((s.get("path") for s in shots if s.get("path")), None)
        if not image:
            continue
        scores = entry.get("scores") or {}
        bits = []
        for key, short in (
            ("identity_stability", "face"),
            ("look_consistency", "look"),
            ("prompt_adherence", "prompt"),
        ):
            value = scores.get(key)
            if isinstance(value, (int, float)):
                bits.append(f"{short} {value:.2f}")
        seconds = entry.get("seconds_per_image")
        if isinstance(seconds, (int, float)):
            bits.append(f"{seconds:.0f}s")
        # Labels come from directory-ish candidate names carrying a dedup hash
        # and a recipe marker. Neither means anything to the person choosing,
        # and both eat the width that the model name needs.
        label = str(entry.get("label") or entry.get("model") or "?")
        label = re.sub(r"__none__[0-9a-f]+|__recipe$|\.safetensors$", "", label).strip("_ -")
        out.append((image, label, "  ".join(bits) or "not scored this round"))
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--project", default="casting-wp2")
    ap.add_argument("--character", default="Heroine")
    ap.add_argument("--brief", default="")
    ap.add_argument("--react", default="", help="What the human said about the last round.")
    ap.add_argument("--decide", default="", help="Sheet number to cast, e.g. 3")
    ap.add_argument("--notes", default="")
    ap.add_argument("--show", action="store_true", help="Print the loop so far and stop.")
    ap.add_argument("--sheet-only", action="store_true", help="Rebuild the sheet from the last report.")
    ap.add_argument("--budget", type=float, default=None)
    ap.add_argument(
        "--models", nargs="*", default=None,
        help=(
            "Force the matrix's models instead of resolving picks against the "
            "last report. For continuing ONE reaction across a split round - a "
            "pick of #7 means the sheet the human saw, and after a partial "
            "round the newest report is not that sheet."
        ),
    )
    args = ap.parse_args()

    project_dir = Path(init_project(args.project, title=f"Casting: {args.character}",
                                    pipeline_type="vrgdg-character-film"))
    session = LoopSession.load(project_dir, "casting")
    if args.character:
        session.subject = args.character
    if args.brief:
        session.brief = args.brief

    if args.show:
        print(json.dumps(session.summary(), indent=2))
        for row in session.history():
            print(f"  round {row['round']}: {row['candidates']} candidates | "
                  f"said {row['reaction']!r} | applied {row['applied']}")
        return 0

    report = _report(project_dir)
    picks = _picks_from_report(report)

    if args.sheet_only:
        n = len(session.rounds) or 1
        out = phone_sheet(picks, project_dir / "casting" / f"round_{n}_sheet.jpg",
                          title=f"{args.character} - round {n}")
        print("sheet:", out)
        return 0

    if args.decide:
        index = int(args.decide) - 1
        if not (0 <= index < len(picks)):
            print(f"FAIL: #{args.decide} is not on the sheet ({len(picks)} candidates)")
            return 1
        entry = (report.get("candidates") or [])[index]
        session.decide({"model": entry.get("model"), "label": entry.get("label"),
                        "seed": entry.get("seed"), "sheet_position": int(args.decide)},
                       chosen_by="human", notes=args.notes)
        session.save()
        print(f"cast: #{args.decide} {entry.get('label')}")
        print("Next: render a reference per shot family, then write the cast record.")
        return 0

    client = VRGDGClient()
    if not client.is_available():
        print("FAIL:", client.unavailable_reason())
        return 1
    # Timings are measured from submission, so a busy machine corrupts them.
    depth = ComfyUIClient(capability="image").queue_depth()
    if depth:
        print(f"FAIL: ComfyUI has {depth} job(s) queued. One GPU job at a time - "
              f"a round started now would both fight for the GPU and record "
              f"garbage timings.")
        return 1

    registry = ModelRegistry.load(default_models_root(), default_ledger_path())
    registry.scan()
    registry.save()

    # A loop can begin outside the loop. `quick_screen_test.py` is a perfectly
    # good way to start - render everything once, then decide it is worth a
    # conversation - and a run that happened is a round whether or not this
    # script recorded it. Adopting it beats refusing to react to work the user
    # can plainly see on their screen.
    if args.react and not session.rounds and report.get("candidates"):
        adopted = session.start_round({
            "models": [c.get("model") for c in report["candidates"]],
            "seeds": report.get("seeds") or [7777],
            "question": "what does each model do with this prompt?",
            "brief": report.get("brief", ""),
            "adopted_from": "screen_test run outside the loop",
        })
        adopted.candidates = report["candidates"]
        adopted.seconds = float(report.get("elapsed_minutes") or 0) * 60
        if not session.brief:
            session.brief = report.get("brief", "")
        print(f"adopted an existing round of {len(adopted.candidates)} candidates "
              f"as round 1")

    brief = session.brief
    if args.react:
        reading = interpret(args.react)
        if reading.unknown:
            print("I did not understand:", "; ".join(reading.unknown))
            print("Say it another way, or use: more like #N / warmer / darker / "
                  "keep the X / lose the X / different face / try the loras / that's her")
            session.record_reaction(args.react, applied={"not_understood": True})
            session.save()
            return 1
        if reading.done:
            print("That reads as a decision. Re-run with --decide N to cast it.")
            return 0
        session.record_reaction(args.react, applied=reading.as_dict(),
                                favourites=reading.picks)
        brief = next_brief(brief, reading)
        session.brief = brief
        # A pick is a position on the sheet the human was shown. When a round is
        # split for memory, the newest report is a slice of that round, not the
        # sheet - so resolving against it would silently cast the wrong models.
        pick_source = report.get("candidates") or []
        if args.models:
            pick_source = [{"model": m} for m in args.models]
            reading.picks = [f"#{i + 1}" for i in range(len(args.models))]
        matrix, question = next_matrix(
            (session.rounds[-1].spec if session.rounds else {}),
            reading,
            candidates=pick_source,
            lora_pool=[Path(k).name for k in getattr(registry, "loras", lambda: [])()]
            if hasattr(registry, "loras") else [],
        )
    else:
        matrix = {"models": [Path(k).name for k in registry.eligible()]}
        question = f"what does each of {len(matrix['models'])} model(s) do with this prompt?"

    # Each candidate is a full model load. Enough of them in one round and the
    # backend runs out of memory, which on this machine kills the process
    # outright rather than failing the render. Say the number before spending
    # twenty minutes finding out.
    span = len(matrix.get("models") or []) * len(matrix.get("seeds") or [7777])
    if span > _RENDERS_BEFORE_A_WARNING:
        print(f"note: {span} renders across {len(matrix['models'])} model(s). "
              f"Large mixed-family rounds have OOM'd the backend here - if it "
              f"dies, split the picks across two rounds.")

    print(f"round {len(session.rounds) + 1}: {question}")
    print("brief:", brief)
    print("matrix:", json.dumps(matrix))

    rnd = session.start_round({**matrix, "question": question, "brief": brief})
    started = time.time()

    inputs = {
        "project_dir": str(project_dir),
        "character": args.character,
        "brief": brief,
        "matrix": matrix,
        "preset": "quick" if len(matrix.get("seeds") or [7777]) < 2 else "shortlist",
        "use_embedded_recipe": "auto",
    }
    if args.budget:
        inputs["budget_minutes"] = args.budget

    result = ScreenTest().execute(inputs)
    rnd.seconds = round(time.time() - started, 1)
    if not result.success:
        # A round that rendered nothing usually means the server went away
        # mid-round, and "no candidate produced an image" says nothing about
        # that. Check before reporting, because the two have completely
        # different answers: one is a bad matrix, the other is a dead backend.
        if not VRGDGClient().is_available():
            print("FAIL: ComfyUI stopped responding during the round.")
            print("      Its most common cause here is running out of memory - "
                  "the OOM handler itself can abort the process while unloading.")
            print("      Restart ComfyUI Desktop, then re-run this exact command; "
                  "the reaction is already recorded and the round will simply "
                  "run again.")
        else:
            print("FAIL:", result.error)
        # An empty round is not a round. Leaving it in the history would claim
        # a round happened and push the next one to the wrong number.
        session.rounds = [r for r in session.rounds if r.candidates]
        session.save()
        return 1

    report = _report(project_dir)
    rnd.candidates = report.get("candidates") or []
    picks = _picks_from_report(report)
    sheet = phone_sheet(picks, project_dir / "casting" / f"round_{rnd.number}_sheet.jpg",
                        title=f"{args.character} - round {rnd.number}")
    rnd.contact_sheet = str(sheet) if sheet else None
    session.save()

    print(f"\n{len(picks)} candidates in {rnd.seconds:.0f}s")
    for i, (_, label, detail) in enumerate(picks, 1):
        print(f"  {i:>2}. {label:<34} {detail}")
    print("\nsheet:", sheet)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
