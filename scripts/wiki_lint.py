"""Check the wiki for the ways a wiki quietly rots.

    python scripts/wiki_lint.py            # report
    python scripts/wiki_lint.py --fix      # create missing stubs, add index rows
    python scripts/wiki_lint.py --stale 60 # also flag pages untouched for N days

The failure mode of a knowledge base is never a dramatic one. It is a page that
was true in April, contradicted in June by a page nobody linked it to, sitting
in a folder nobody opens. Frontmatter, the index and the link graph are what
make that findable, so this checks all three.

Exits non-zero when something needs a human.
"""

from __future__ import annotations

import argparse
import re
import sys
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WIKI = ROOT / "wiki"
INDEX = WIKI / "index.md"
LOG = WIKI / "log.md"

STATUSES = ("measured", "researched", "assumed", "stub")

#: Pages that are structure, not knowledge. They are exempt from needing
#: frontmatter and from appearing in the index as content.
META_PAGES = {"index.md", "log.md", "CONVENTIONS.md"}

_FRONTMATTER = re.compile(r"\A---\n(.*?)\n---\n", re.S)
_LINK = re.compile(r"\[[^\]]*\]\(([^)#]+?)(?:#[^)]*)?\)")


@dataclass
class Report:
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    fixed: list[str] = field(default_factory=list)

    def ok(self) -> bool:
        return not self.errors


def _pages() -> list[Path]:
    return sorted(p for p in WIKI.rglob("*.md") if "raw" not in p.relative_to(WIKI).parts)


def _frontmatter(text: str) -> dict[str, str]:
    m = _FRONTMATTER.match(text)
    if not m:
        return {}
    out: dict[str, str] = {}
    for line in m.group(1).splitlines():
        if ":" in line and not line.startswith(" "):
            key, _, value = line.partition(":")
            out[key.strip()] = value.strip()
    return out


def _stub(path: Path, linked_from: Path) -> str:
    title = path.stem.replace("-", " ").replace("_", " ")
    return (
        f"---\ntitle: {title[:1].upper() + title[1:]}\nstatus: stub\n"
        f"updated: {date.today().isoformat()}\nsources: []\n---\n\n"
        f"Stub. Linked from `{linked_from.relative_to(WIKI).as_posix()}` before it was written.\n\n"
        f"A stub is a request, not a placeholder: something needed this page to exist.\n"
        f"Whoever fills it in should say what that was.\n"
    )


def lint(fix: bool = False, stale_days: int | None = None) -> Report:
    r = Report()
    if not WIKI.is_dir():
        r.errors.append(f"no wiki at {WIKI}")
        return r

    pages = _pages()
    index_text = INDEX.read_text(encoding="utf-8") if INDEX.is_file() else ""
    today = date.today()

    for page in pages:
        rel = page.relative_to(WIKI).as_posix()
        text = page.read_text(encoding="utf-8")

        # -- frontmatter -------------------------------------------------
        if page.name not in META_PAGES:
            fm = _frontmatter(text)
            if not fm:
                r.errors.append(f"{rel}: no frontmatter block")
            else:
                status = fm.get("status", "")
                if status not in STATUSES:
                    r.errors.append(
                        f"{rel}: status {status!r} is not one of {', '.join(STATUSES)}"
                    )
                if not fm.get("title"):
                    r.errors.append(f"{rel}: no title")
                updated = fm.get("updated", "")
                try:
                    when = datetime.strptime(updated, "%Y-%m-%d").date()
                except ValueError:
                    r.errors.append(f"{rel}: updated {updated!r} is not YYYY-MM-DD")
                    when = None
                if when and when > today:
                    r.errors.append(f"{rel}: updated {updated} is in the future")
                if when and stale_days and (today - when).days > stale_days:
                    r.warnings.append(
                        f"{rel}: untouched for {(today - when).days} days "
                        f"(status: {status})"
                    )
                # A page claiming measurement should carry a number. Not proof,
                # but it catches the page that says "works well" and calls that
                # measured - which is the claim this wiki is least able to
                # afford being wrong about.
                if status == "measured" and not re.search(r"\d", text[len(updated) :]):
                    r.warnings.append(f"{rel}: status is measured but carries no numbers")

        # -- links -------------------------------------------------------
        for target in _LINK.findall(text):
            if target.startswith(("http://", "https://", "mailto:")):
                continue
            resolved = (page.parent / target).resolve()
            if resolved.exists():
                continue
            try:
                shown = resolved.relative_to(ROOT).as_posix()
            except ValueError:
                shown = target
            if fix and resolved.suffix == ".md" and WIKI in resolved.parents:
                resolved.parent.mkdir(parents=True, exist_ok=True)
                resolved.write_text(_stub(resolved, page), encoding="utf-8")
                r.fixed.append(f"created stub {shown} (linked from {rel})")
            else:
                r.errors.append(f"{rel}: broken link -> {shown}")

        # -- index membership --------------------------------------------
        if page.name not in META_PAGES and rel not in index_text:
            if fix:
                r.warnings.append(
                    f"{rel}: missing from the index - add it by hand, the index "
                    f"groups pages by meaning and a script cannot guess the row"
                )
            else:
                r.errors.append(f"{rel}: not listed in index.md")

    # -- the index must not point at pages that do not exist -------------
    for target in _LINK.findall(index_text):
        if target.startswith(("http", "mailto:")):
            continue
        if not (INDEX.parent / target).resolve().exists():
            r.errors.append(f"index.md: lists a page that does not exist -> {target}")

    if not LOG.is_file():
        r.errors.append("wiki/log.md is missing - the wiki has no history")

    return r


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--fix", action="store_true", help="create stubs for broken links")
    ap.add_argument("--stale", type=int, default=None, help="flag pages older than N days")
    args = ap.parse_args()

    r = lint(fix=args.fix, stale_days=args.stale)

    for line in r.fixed:
        print(f"  fixed   {line}")
    for line in r.warnings:
        print(f"  warn    {line}")
    for line in r.errors:
        print(f"  ERROR   {line}")

    total = len(_pages())
    if r.ok():
        print(f"\nwiki lint: {total} pages, clean"
              + (f", {len(r.warnings)} warning(s)" if r.warnings else ""))
        return 0
    print(f"\nwiki lint: {total} pages, {len(r.errors)} error(s), {len(r.warnings)} warning(s)")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
