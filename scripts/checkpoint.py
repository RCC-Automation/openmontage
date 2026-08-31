"""Write and read a project's stage checkpoints - the record that makes a film resumable.

    python scripts/checkpoint.py --project the-man-watches --list
    python scripts/checkpoint.py --project the-man-watches --stage scene_plan \
        --status awaiting_human --note "retimed to the delivered track"
    python scripts/checkpoint.py --project the-man-watches --stage scene_plan \
        --status completed --approved --approved-on "2026-08-30 in chat"

**Run this with the repo venv** - `.venv/Scripts/python.exe` - because checkpoint
writing validates every artifact against its schema, and that needs `jsonschema`.

What a checkpoint is for
------------------------

Artifacts on disk prove work happened. They cannot prove it was *approved*, and
they cannot tell a cold session which stage comes next. A checkpoint records
both, and that is what buys three things nothing else does:

**Resume.** `get_next_stage()` reads the checkpoints and answers. Without them a
fresh session always answers `brief`, no matter how much of the film is made.

**Gate.** `write_checkpoint` refuses `completed` on a stage the manifest gates
without `human_approved=True`, and refuses to advance any stage whose
predecessors are not completed and approved. Exporting a half-picked film to the
Builder stops being something we remember not to do and becomes an error.

**Send back.** A superseded checkpoint is copied into `history/` before it is
overwritten, so dailies can reopen a shot and the earlier verdict survives.

The gate protocol
-----------------

For a gated stage the order is: write `awaiting_human`, show the human what the
stage produced, **stop**, and only after they approve write `completed` with
`--approved`. Skipping straight to `completed` is a hard error, by design.

Where an approval happened before this record existed, pass `--approved-on` so
the audit trail says when and how the human actually decided rather than
implying this script witnessed it.

Every write regenerates the project's status page, because a status page that
has to be remembered is a status page that goes stale.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from lib.checkpoint import (  # noqa: E402
    CheckpointValidationError, get_next_stage, get_pipeline_stages,
    read_checkpoint, write_checkpoint,
)
from lib.machine_paths import project_dir, repo_root  # noqa: E402

#: Where a stage's artifacts live when they are files. A stage whose artifact is
#: not a file yet (a look record, an export report) simply contributes nothing
#: and the checkpoint carries a path reference instead.
ARTIFACT_FILE = "artifacts/{name}.json"


def manifest_produces(repo: Path, pipeline_type: str) -> dict[str, list[str]]:
    """`produces:` per stage, read from the pipeline manifest.

    A targeted reader rather than a YAML parse: the manifest's stage block is a
    flat list of `- name:` entries, and this keeps the tool usable in a bare
    environment where only jsonschema is installed.
    """
    try:
        text = (repo / "pipeline_defs" / f"{pipeline_type}.yaml").read_text(
            encoding="utf-8")
    except OSError:
        return {}
    out: dict[str, list[str]] = {}
    stage = None
    in_produces = False
    for line in text.split("\nstages:", 1)[-1].splitlines():
        m = re.match(r"^\s*-\s+name:\s*(\w+)\s*$", line)
        if m:
            stage, in_produces = m.group(1), False
            out[stage] = []
            continue
        if stage is None:
            continue
        if re.match(r"^\s*produces:\s*$", line):
            in_produces = True
            continue
        if in_produces:
            item = re.match(r"^\s*-\s+(\w+)\s*$", line)
            if item:
                out[stage].append(item.group(1))
            else:
                in_produces = False
    return out


def collect_artifacts(project: Path, names: list[str]) -> tuple[dict, list[str]]:
    """Load each named artifact from disk. Embed the object when the file is
    there - the checkpoint is meant to be a snapshot, not a set of pointers that
    can rot - and note what is missing."""
    found, missing = {}, []
    for name in names:
        path = project / ARTIFACT_FILE.format(name=name)
        try:
            found[name] = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            missing.append(name)
    return found, missing


def show(project: Path, pipeline_dir: Path, pipeline_type: str) -> int:
    stages = get_pipeline_stages(pipeline_type)
    width = max(len(s) for s in stages)
    print(f"{project.name}  ({pipeline_type})\n")
    for stage in stages:
        try:
            cp = read_checkpoint(pipeline_dir, project.name, stage)
        except CheckpointValidationError as exc:
            print(f"  {stage:{width}}  INVALID  {str(exc)[:80]}")
            continue
        if not cp:
            print(f"  {stage:{width}}  -")
            continue
        mark = "approved" if cp.get("human_approved") else (
            "NEEDS APPROVAL" if cp.get("human_approval_required") else "")
        print(f"  {stage:{width}}  {cp['status']:14} {cp['timestamp'][:19]}  {mark}")
    nxt = get_next_stage(pipeline_dir, project.name, pipeline_type)
    print(f"\nnext stage: {nxt or 'none - the film is finished'}")
    return 0


def regenerate_page(project: Path) -> None:
    try:
        sys.path.insert(0, str(repo_root() / "scripts"))
        import project_page
        out = project / "page"
        out.mkdir(parents=True, exist_ok=True)
        dest = out / f"{project.name}.html"
        dest.write_text(project_page.build(project, repo_root()), encoding="utf-8")
        print(f"page: {dest}")
    except Exception as exc:  # never let a page failure lose a checkpoint
        print(f"page NOT regenerated: {exc}")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--project", default=None)
    ap.add_argument("--list", action="store_true", help="show every stage and stop")
    ap.add_argument("--stage")
    ap.add_argument("--status", choices=("in_progress", "awaiting_human",
                                         "completed", "failed"))
    ap.add_argument("--approved", action="store_true",
                    help="the human approved this stage; required for a gated "
                         "stage to be completed")
    ap.add_argument("--approved-on",
                    help="when and how the human approved, for an approval that "
                         "happened before this record existed")
    ap.add_argument("--note", help="one line for the review record")
    ap.add_argument("--open", action="append", default=[], dest="open_items",
                    help="something this stage leaves unresolved; repeatable")
    ap.add_argument("--error", help="what failed, for --status failed")
    ap.add_argument("--no-page", action="store_true")
    args = ap.parse_args()

    project = project_dir(args.project)
    pipeline_dir = project.parent
    meta = json.loads((project / "project.json").read_text(encoding="utf-8"))
    pipeline_type = meta.get("pipeline_type", "unknown")

    if args.list or not args.stage:
        return show(project, pipeline_dir, pipeline_type)
    if not args.status:
        print("--status is required with --stage")
        return 2

    produces = manifest_produces(repo_root(), pipeline_type).get(args.stage, [])
    artifacts, missing = collect_artifacts(project, produces)
    if missing:
        print(f"note: {args.stage} declares {missing} which are not on disk yet")

    review = None
    if args.note or args.open_items:
        review = {"summary": args.note or "",
                  "open_items": args.open_items,
                  "reviewed_by": "agent"}

    metadata = {"written_by": "scripts/checkpoint.py"}
    if args.approved_on:
        metadata["approval_recorded_from"] = args.approved_on
    if missing:
        metadata["declared_but_absent"] = missing

    try:
        path = write_checkpoint(
            pipeline_dir, project.name, args.stage, args.status, artifacts,
            pipeline_type=pipeline_type,
            human_approved=args.approved,
            review=review, error=args.error, metadata=metadata)
    except CheckpointValidationError as exc:
        print(f"REFUSED\n\n{exc}")
        return 1

    carried = ", ".join(artifacts) or "no artifact files"
    print(f"{args.stage}: {args.status}"
          f"{' (approved)' if args.approved else ''} -> {path}")
    print(f"  carries: {carried}")
    nxt = get_next_stage(pipeline_dir, project.name, pipeline_type)
    print(f"  next stage: {nxt or 'none'}")

    if not args.no_page:
        regenerate_page(project)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
