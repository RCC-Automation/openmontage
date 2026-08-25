"""Turn a reaction into the next casting round.

The instrument was already built: `screen_test` renders a matrix, five
calibrated axes score it, and a contact sheet comes out. What was missing is
the conversation — the part where a person says "more like #3, warmer, keep the
collar" and that becomes a matrix.

This module is that translation and nothing else. It does not render, does not
rank, and does not decide. It reads a reaction and a round, and says what the
next matrix should be.

Two rules it does not break:

* **The machine narrows, the human picks** (DECISIONS #15). Nothing here
  chooses a winner. `interpret` can say "they picked #3" because they said so.
* **Keep one thing varying per round.** Changing the model set and the prompt
  together produces a different image, not a better one, and no way to tell
  which change did it. `next_matrix` widens exactly one axis at a time and says
  which, so a round is always an answer to one question.

The vocabulary is deliberately small and deliberately incomplete. A phrase it
does not know is asked back in plain words rather than guessed at — a wrong
guess costs a whole round, and rounds are the expensive thing here. Phrases
that recur get added.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Iterable, Mapping, Sequence

#: What a reaction can change, in the order a casting session normally widens
#: them: which model, then whether it holds across seeds, then the wording,
#: then the LoRA stack. Round one is always models-only.
AXES = ("models", "seeds", "prompt", "loras")


@dataclass
class Reading:
    """What was understood from a reaction, and what was not.

    ``unknown`` is the important field. It is what gets asked back, and it is
    also the record of where the vocabulary is too small - a phrase that shows
    up here twice belongs in the table.
    """

    picks: list[str] = field(default_factory=list)
    pins: list[str] = field(default_factory=list)
    drops: list[str] = field(default_factory=list)
    adjust: dict[str, str] = field(default_factory=dict)
    widen: str | None = None
    done: bool = False
    unknown: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        out: dict[str, Any] = {}
        if self.picks:
            out["picks"] = self.picks
        if self.pins:
            out["pinned"] = self.pins
        if self.drops:
            out["dropped"] = self.drops
        if self.adjust:
            out.update(self.adjust)
        if self.widen:
            out["widen"] = self.widen
        if self.done:
            out["done"] = True
        if self.unknown:
            out["not_understood"] = self.unknown
        return out

    @property
    def understood(self) -> bool:
        return bool(
            self.picks or self.pins or self.drops or self.adjust or self.widen or self.done
        )


#: Adjustments that map onto a prompt or a sampler setting. The value is the
#: (field, value) pair a round spec carries. These are the phrases a person
#: actually uses about a face on a screen - not a parameter list with synonyms.
_ADJUSTMENTS: dict[str, tuple[str, str]] = {
    "warmer": ("color_temperature", "warm"),
    "cooler": ("color_temperature", "cool"),
    "colder": ("color_temperature", "cool"),
    "darker": ("lighting_key", "low_key"),
    "brighter": ("lighting_key", "high_key"),
    "moodier": ("lighting_key", "low_key"),
    "softer": ("detail", "soft"),
    "sharper": ("detail", "sharp"),
    "closer": ("shot_size", "close_up"),
    "wider": ("shot_size", "wide"),
    "younger": ("age", "younger"),
    "older": ("age", "older"),
}

#: Phrases that say "open the next axis". Ordered longest-first at match time so
#: "different face" is not eaten by "different".
_WIDEN: dict[str, str] = {
    "try the loras": "loras",
    "try loras": "loras",
    "with loras": "loras",
    "different face": "seeds",
    "other faces": "seeds",
    "another seed": "seeds",
    "different seeds": "seeds",
    "does it hold": "seeds",
    "reword": "prompt",
    "different prompt": "prompt",
    "say it differently": "prompt",
    "more models": "models",
    "other models": "models",
}

#: Phrases that end the loop. Kept separate from picks because "that's her" is
#: a decision and "I like #3" is not.
_DONE = (
    "that's her",
    "thats her",
    "that's the one",
    "thats the one",
    "that's him",
    "thats him",
    "cast her",
    "cast him",
    "cast that",
    "lock it",
    "we're done",
    "were done",
)

#: A pick with or without the hash. People type "#3" and they also type
#: "4, 6, 7 and 8", and a parser that only understands the first form selects
#: nothing from the second - which reads as being ignored, not as an error.
#: Bounded to two digits so a year or a percentage is not read as a pick.
_PICK = re.compile(r"#\s*(\d{1,2})\b|(?<![\w#.])(\d{1,2})(?![\w.])")
_KEEP = re.compile(r"\bkeep (?:the |her |his )?([a-z][a-z \-]{2,30}?)(?:[,.]|$| and | but )")
_LOSE = re.compile(r"\b(?:lose|drop|without|no more) (?:the |her |his )?([a-z][a-z \-]{2,30}?)(?:[,.]|$| and | but )")


def interpret(reaction: str) -> Reading:
    """Read a reaction. Understand what you can; report what you cannot.

    Case and punctuation are ignored. Several instructions in one sentence are
    normal - "more like #3, warmer, keep the collar" is three - so every rule
    runs against the whole reaction rather than stopping at the first match.
    """
    text = f" {str(reaction or '').lower().strip()} "
    reading = Reading()

    for phrase in _DONE:
        if phrase in text:
            reading.done = True
            break

    picks: list[str] = []
    for hashed, bare in _PICK.findall(text):
        n = hashed or bare
        if n and f"#{int(n)}" not in picks:
            picks.append(f"#{int(n)}")
    reading.picks = picks

    for phrase, axis in sorted(_WIDEN.items(), key=lambda kv: -len(kv[0])):
        if phrase in text:
            reading.widen = axis
            break

    for word, (field_name, value) in _ADJUSTMENTS.items():
        if re.search(rf"\b{re.escape(word)}\b", text):
            reading.adjust[field_name] = value

    reading.pins = [m.strip() for m in _KEEP.findall(text) if m.strip()]
    reading.drops = [m.strip() for m in _LOSE.findall(text) if m.strip()]

    if not reading.understood and text.strip():
        reading.unknown = [str(reaction).strip()]
    else:
        reading.unknown = _leftovers(text, reading)
    return reading


#: Words that carry no instruction and are not worth asking about. Everything
#: else that survives parsing is.
_FILLER = frozenset(
    """a an and or the this that these those i we you it is are was be to of for
    with on in at as but so then just really quite very bit more less like likes
    liked prefer please thanks thank ok okay yes no not do does did can could
    would should me my mine them they he she her his one ones them all also too
    them there here what which how why when where""".split()
)


def _leftovers(text: str, reading: Reading) -> list[str]:
    """Fragments a partly-understood reaction left behind.

    The point of the unknown list is that nothing said gets silently dropped.
    Reporting it only when *nothing* parsed misses the more dangerous case: a
    reaction that was mostly understood, so it runs, with one instruction
    quietly discarded. A typo'd pick - "4, u, 7" - is exactly that, and it seeds
    a whole round on the wrong models.

    A bare letter or a stray token next to real picks is worth one question. A
    round is not.
    """
    consumed: set[str] = set()
    for phrase in list(_WIDEN) + list(_DONE):
        if phrase in text:
            consumed.update(re.findall(r"[a-z]+", phrase))
    for word in _ADJUSTMENTS:
        if re.search(rf"\b{re.escape(word)}\b", text):
            consumed.add(word)
    for pinned in reading.pins + reading.drops:
        consumed.update(pinned.split())
    consumed.update({"keep", "lose", "drop", "without"})

    # Contractions are stripped before tokenising rather than filtered after.
    # Dropping every one-character token would also drop a typo'd pick - the
    # "u" in "4, u, 7" - which is exactly the fragment worth asking about.
    cleaned = re.sub(r"'(?:s|t|re|ve|ll|d|m)\b", "", text)

    out: list[str] = []
    for token in re.findall(r"[a-z0-9#]+", cleaned):
        bare = token.lstrip("#")
        if not bare or bare.isdigit() or bare in consumed or bare in _FILLER:
            continue
        if bare not in out:
            out.append(bare)
    return out


def next_matrix(
    previous: Mapping[str, Any],
    reading: Reading,
    *,
    candidates: Sequence[Mapping[str, Any]] = (),
    lora_pool: Iterable[str] = (),
) -> tuple[dict[str, Any], str]:
    """The next round's matrix, and one sentence saying what it is asking.

    Returns (matrix, question). The question is not decoration: a round whose
    purpose cannot be said in a sentence is a round that varies too much to
    learn from.
    """
    picked = _models_for(reading.picks, candidates) or list(previous.get("models") or [])
    matrix: dict[str, Any] = {"models": picked}

    axis = reading.widen or _default_widen(previous)
    if axis == "seeds":
        # The question round one cannot answer. One seed shows what a model
        # does with a prompt; three show whether it does the same thing twice.
        matrix["seeds"] = [7777, 1234, 9090]
        question = f"does the identity hold across seeds for {len(picked)} model(s)?"
    elif axis == "loras":
        pool = [str(l) for l in lora_pool]
        matrix["lora_sets"] = [[]] + [[[l, 0.8]] for l in pool]
        matrix["seeds"] = list(previous.get("seeds") or [7777])
        question = f"do any of {len(pool)} LoRA(s) improve the chosen stack?"
    elif axis == "prompt":
        matrix["seeds"] = list(previous.get("seeds") or [7777])
        question = "does rewording the description change who she is?"
    else:
        matrix["seeds"] = list(previous.get("seeds") or [7777])
        question = f"what does each of {len(picked)} model(s) do with this prompt?"

    return matrix, question


def next_brief(brief: str, reading: Reading) -> str:
    """The description for the next round, with pins kept and drops removed.

    Pinned phrases are appended verbatim rather than blended in. The
    description carries the identity, not the seed (DECISIONS #29), so a
    phrase the human asked to keep must survive every later reword intact -
    paraphrasing "the brass collar" into "ornate neckwear" is how a character
    stops being herself.
    """
    text = str(brief or "").strip()
    for drop in reading.drops:
        text = re.sub(rf",?\s*[^,]*\b{re.escape(drop)}\b[^,]*", "", text, flags=re.I).strip(" ,")
    for pin in reading.pins:
        if pin.lower() not in text.lower():
            text = f"{text}, {pin}" if text else pin
    for field_name, value in reading.adjust.items():
        phrase = _ADJUSTMENT_PHRASES.get((field_name, value))
        if phrase and phrase.lower() not in text.lower():
            text = f"{text}, {phrase}"
    return text


#: How an adjustment reads in a prompt. Kept apart from the parsing table so
#: the words a person says and the words a model reads can differ - "darker"
#: is what they say, "dramatic low-key lighting with deep shadows" is what
#: renders.
_ADJUSTMENT_PHRASES: dict[tuple[str, str], str] = {
    ("color_temperature", "warm"): "warm amber tones",
    ("color_temperature", "cool"): "cool blue tones",
    ("lighting_key", "low_key"): "dramatic low-key lighting with deep shadows",
    ("lighting_key", "high_key"): "bright high-key lighting, soft and even",
    ("detail", "soft"): "soft focus, gentle detail",
    ("detail", "sharp"): "razor-sharp detail, crisp micro-texture",
    ("shot_size", "close_up"): "tight close-up on her face",
    ("shot_size", "wide"): "wide shot, full figure in the frame",
    ("age", "younger"): "younger",
    ("age", "older"): "older",
}


def _models_for(
    picks: Sequence[str], candidates: Sequence[Mapping[str, Any]]
) -> list[str]:
    """Resolve "#3" against the sheet the human was looking at.

    Sheet position, not candidate id: the number they typed is the number under
    the picture. Any other mapping silently casts the wrong model.
    """
    out: list[str] = []
    for pick in picks:
        try:
            index = int(pick.lstrip("#")) - 1
        except ValueError:
            continue
        if 0 <= index < len(candidates):
            model = candidates[index].get("model")
            if model and model not in out:
                out.append(str(model))
    return out


def _default_widen(previous: Mapping[str, Any]) -> str:
    """Which axis opens next when the human did not say.

    Seeds before anything else. A model that makes one good portrait and a
    different face every time is useless for a film, and round one cannot tell
    the difference - so that is the question worth asking second.
    """
    seeds = list(previous.get("seeds") or [])
    if len(seeds) < 2:
        return "seeds"
    if not previous.get("lora_sets"):
        return "loras"
    return "prompt"


# ---------------------------------------------------------------------------
# the sheet the human actually judges from
# ---------------------------------------------------------------------------

#: Fonts to try, in order. Falls back to PIL's bitmap font, which is legible on
#: a desktop and far too small on a phone - so the fallback is a degraded sheet,
#: not an equivalent one.
_FONT_CANDIDATES = (
    "C:/Windows/Fonts/segoeuib.ttf",
    "C:/Windows/Fonts/arialbd.ttf",
    "/System/Library/Fonts/Supplemental/Arial Bold.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
)


def _font(size: int):
    from PIL import ImageFont

    for path in _FONT_CANDIDATES:
        try:
            return ImageFont.truetype(path, size)
        except Exception:
            continue
    return ImageFont.load_default()


def phone_sheet(
    picks: Sequence[tuple[str, str, str]],
    destination,
    *,
    title: str = "",
    columns: int = 2,
    cell: int = 620,
    start_index: int = 1,
) -> Any:
    """A contact sheet meant to be judged on a phone.

    ``picks`` is (image_path, label, detail) in the order they should be
    numbered. The number under the picture is what the human types back, so
    position is the identity here - see ``_models_for``.

    ``start_index`` continues the numbering across a split. Twelve candidates
    stacked two-wide is a 1:7 strip, and a phone that fits the whole thing to
    the screen renders every face too small to judge. Six per sheet is roughly
    a phone's own aspect - but the numbering has to run 1-6 then 7-12, or the
    pick resolves against the wrong model.

    The desktop sheet packs four 384px cells with an 11px caption, which is
    fine on a monitor and unreadable held in one hand. This one is two columns,
    large type, and puts the number *on* the image as a high-contrast badge so
    it survives being screenshotted, cropped, or scrolled past quickly.
    """
    from pathlib import Path as _Path

    try:
        from PIL import Image, ImageDraw
    except Exception:
        return None

    picks = [(p, l, d) for p, l, d in picks if _Path(p).is_file()]
    if not picks:
        return None

    pad, label_h = 16, 92
    title_h = 76 if title else 0
    columns = max(1, columns)
    rows = (len(picks) + columns - 1) // columns
    width = columns * (cell + pad) + pad
    height = title_h + rows * (cell + label_h + pad) + pad

    sheet = Image.new("RGB", (width, height), (16, 16, 20))
    draw = ImageDraw.Draw(sheet)
    f_title, f_badge, f_label, f_detail = _font(38), _font(46), _font(30), _font(24)

    if title:
        draw.text((pad + 4, pad + 8), title, fill=(240, 240, 248), font=f_title)

    for index, (path, label, detail) in enumerate(picks):
        col, row = index % columns, index // columns
        x = pad + col * (cell + pad)
        y = title_h + pad + row * (cell + label_h + pad)
        try:
            with Image.open(path) as img:
                img = img.convert("RGB")
                img.thumbnail((cell, cell))
                ox, oy = x + (cell - img.width) // 2, y + (cell - img.height) // 2
                sheet.paste(img, (ox, oy))
        except Exception:
            draw.rectangle([x, y, x + cell, y + cell], fill=(38, 38, 46))
            ox, oy = x, y

        # The number rides on the image, not beside it: a caption scrolls out of
        # frame, a badge does not.
        n = str(index + start_index)
        bw = 62
        draw.rectangle([ox + 10, oy + 10, ox + 10 + bw, oy + 10 + bw], fill=(0, 0, 0))
        draw.rectangle([ox + 10, oy + 10, ox + 10 + bw, oy + 10 + bw], outline=(255, 214, 92), width=3)
        tw = draw.textlength(n, font=f_badge)
        draw.text((ox + 10 + (bw - tw) / 2, oy + 16), n, fill=(255, 214, 92), font=f_badge)

        draw.text((x + 4, y + cell + 8), label[:34], fill=(236, 236, 244), font=f_label)
        draw.text((x + 4, y + cell + 48), detail[:52], fill=(158, 158, 172), font=f_detail)

    destination = _Path(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    sheet.save(destination, quality=92)
    return destination
