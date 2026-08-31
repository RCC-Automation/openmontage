"""Read a film's shot list out of its markdown table.

The shot list is written and edited as prose in `plan/02-shot-list.md`, because
that is the form a human argues with. Everything downstream - the status page,
the retime, the export - needs it as data. Keeping a second JSON copy alongside
the markdown would mean two files that disagree by the end of the week, so there
is one source and this parses it.

    from lib.shot_list import parse_shots, group_by_section
    shots = parse_shots(project)

The table's shape is the contract::

    | # | Time | Dur | Loc | Motion | Density | Tier | Action |
    | 01 | 0:00 | 7s | L1 | Still | empty | CORE | Nothing. A straight horizon |

A row whose first cell is a two-digit number (optionally with a letter suffix,
`08a`) is a shot. A row whose first cell is bold with every other cell empty is
a section banner - `**VERSE 1** - *they came before the light*` - and every shot
after it belongs to that section until the next banner.
"""

from __future__ import annotations

import re
from pathlib import Path

SHOT_ID = re.compile(r"\*{0,2}(\d{2}[a-z]?)\*{0,2}")
BOLD = re.compile(r"\*\*(.+?)\*\*")
#: A bold run at the very end of the action cell.
TRAILING_NOTE = re.compile(r"\s*\*\*([^*]+)\*\*\s*$")


def _clean(cell: str) -> str:
    return BOLD.sub(r"\1", cell).strip()


def parse_shots(project: Path, relative: str = "plan/02-shot-list.md") -> list[dict]:
    """Every shot in the list, in order, each tagged with its section."""
    try:
        text = (project / relative).read_text(encoding="utf-8")
    except OSError:
        return []

    shots: list[dict] = []
    section: str | None = None
    for line in text.splitlines():
        if not line.startswith("|"):
            continue
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if len(cells) < 8:
            continue

        head = cells[0]
        match = SHOT_ID.fullmatch(head)
        if not match:
            # A banner is a bold first cell with every other cell empty. The
            # banner text carries a lyric after an em dash; keep only the name,
            # which is what maps onto a song section.
            if head.startswith("**") and not any(cells[1:]):
                section = _clean(head).split("—")[0].split(" - ")[0].strip()
            continue

        shots.append({
            "id": match.group(1),
            "section": section,
            "time": cells[1],
            "duration": _seconds(cells[2]),
            "duration_raw": cells[2],
            "loc": cells[3],
            "motion": cells[4],
            "density": cells[5],
            "tier": cells[6],
            # A trailing bold run is a note to the reader, not part of the
            # image: **Bookend A**, **Attention 3**, **He loses her**. It has to
            # be separated HERE, while the markers still exist - once _clean has
            # removed them nothing downstream can tell the two apart, and the
            # note goes into the render prompt. On the bridge whiteouts that is
            # what kept putting a person in a frame that must be empty.
            "action": _clean(TRAILING_NOTE.sub("", cells[7]).strip()),
            "note": _clean(m.group(1)) if (m := TRAILING_NOTE.search(cells[7])) else "",
        })
    return shots


def _seconds(cell: str) -> float | None:
    m = re.search(r"([\d.]+)\s*s", cell)
    return float(m.group(1)) if m else None


def group_by_section(shots: list[dict]) -> list[tuple[str, list[dict]]]:
    """Shots grouped under their banner, banners in the order they appear.

    Returns a list rather than a dict: a film can repeat a section name
    (two choruses), and the order is the film.
    """
    groups: list[tuple[str, list[dict]]] = []
    for shot in shots:
        name = shot["section"] or "UNSECTIONED"
        if not groups or groups[-1][0] != name:
            groups.append((name, []))
        groups[-1][1].append(shot)
    return groups
