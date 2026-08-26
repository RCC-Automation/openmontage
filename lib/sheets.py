"""Contact sheets for anything with a path and a caption.

`screen_test.contact_sheet` builds the casting sheet, but it takes
`CandidateResult` objects and picks one representative render per candidate -
the right shape for comparing models, the wrong one for looking at forty renders
of the same model grouped by cluster, or at a dataset family with its scores.

Same visual language, generic inputs. Returns None when Pillow cannot build the
sheet, which is never fatal: the report still carries every path.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Sequence

__all__ = ["SheetItem", "labelled_sheet"]


@dataclass
class SheetItem:
    path: Path
    caption: str = ""
    subcaption: str = ""
    #: Drawn as a border. Used to make cluster membership visible at a glance,
    #: which is the whole reason to look at the sheet rather than the JSON.
    accent: tuple[int, int, int] | None = None


#: Distinguishable at a glance on the dark ground, and stable across runs so a
#: cluster keeps its colour between the "all renders" sheet and its own.
ACCENTS: tuple[tuple[int, int, int], ...] = (
    (232, 106, 122),
    (106, 176, 232),
    (140, 214, 132),
    (232, 186, 96),
    (178, 138, 232),
    (96, 216, 208),
    (232, 148, 200),
    (168, 168, 178),
)


def labelled_sheet(
    items: Sequence[SheetItem],
    destination: Path,
    *,
    columns: int = 6,
    cell: int = 288,
    title: str = "",
) -> Path | None:
    """A grid of thumbnails, each captioned, optionally border-coded."""
    try:
        from PIL import Image, ImageDraw
    except Exception:
        return None

    usable = [item for item in items if Path(item.path).is_file()]
    if not usable:
        return None

    label_h, pad = 32, 8
    title_h = 30 if title else 0
    columns = max(1, columns)
    rows = (len(usable) + columns - 1) // columns
    sheet = Image.new(
        "RGB",
        (
            columns * (cell + pad) + pad,
            rows * (cell + label_h + pad) + pad + title_h,
        ),
        (18, 18, 22),
    )
    draw = ImageDraw.Draw(sheet)
    if title:
        draw.text((pad + 2, 8), title[:150], fill=(235, 235, 242))

    for index, item in enumerate(usable):
        col, row = index % columns, index // columns
        x = pad + col * (cell + pad)
        y = pad + title_h + row * (cell + label_h + pad)
        try:
            with Image.open(item.path) as img:
                img = img.convert("RGB")
                img.thumbnail((cell, cell))
                offset_x = x + (cell - img.width) // 2
                sheet.paste(img, (offset_x, y))
                if item.accent:
                    draw.rectangle(
                        [offset_x - 2, y - 2, offset_x + img.width + 1, y + img.height + 1],
                        outline=item.accent,
                        width=3,
                    )
        except Exception:
            draw.rectangle([x, y, x + cell, y + cell], fill=(40, 40, 46))
        if item.caption:
            draw.text((x + 2, y + cell + 3), item.caption[:44], fill=(228, 228, 235))
        if item.subcaption:
            draw.text((x + 2, y + cell + 17), item.subcaption[:44], fill=(150, 150, 162))

    destination.parent.mkdir(parents=True, exist_ok=True)
    sheet.save(destination)
    return destination
