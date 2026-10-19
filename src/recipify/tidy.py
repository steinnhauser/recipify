"""Deterministic clean-up of raw extracted markdown into the text shown to readers.

The raw output (a faithful copy of the source) stays in the earlier version; tidy only
removes noise that is certainly not part of the recipe.
"""

import re

from recipify.labels import fold

HEADING = re.compile(r"^#{1,6}\s+(.*)$")


def _norm(block: str) -> str:
    return re.sub(r"\s+", " ", fold(re.sub(r"[#*_]+", " ", block))).strip()


def _blocks(text: str) -> list[str]:
    return [b.strip() for b in re.split(r"\n\s*\n", text) if b.strip()]


def _collapse_repeats(blocks: list[str]) -> list[str]:
    """If the whole document is one sequence of blocks repeated (page printed N times), keep one."""
    keys = [_norm(b) for b in blocks]
    n = len(keys)
    for p in range(3, n // 2 + 1):
        if keys[:p] * (n // p) == keys[: p * (n // p)] and sum(map(len, keys[:p])) > 40:
            rest = keys[p * (n // p) :]
            if keys[: len(rest)] == rest:
                return blocks[:p]
    return blocks


PHRASE_REPEAT = re.compile(r"(\S.{5,}?)(?:\s+\1){2,}(?!\w)")
TOKEN_REPEAT = re.compile(r"(\S+)(?:\s+\1){2,}(?!\S)")


def _squash_line(line: str) -> str:
    """Merged table cells in docx/pdf come out as the same phrase 3-4 times in a row."""
    line = PHRASE_REPEAT.sub(r"\1", line)
    return TOKEN_REPEAT.sub(r"\1", line).rstrip()


def tidy(text: str, title: str) -> str:
    blocks = _blocks(text)
    keys = [_norm(b) for b in blocks]
    name = _norm(title)
    out: list[str] = []
    seen_head = 0
    for block, key in zip(blocks, keys, strict=True):
        first = block.splitlines()[0]
        is_head = bool(HEADING.match(first)) and "\n" not in block
        is_bold_title = key == name and len(block) < 160
        if is_head and not key:
            continue
        # the title is shown separately; drop its echoes among the first headings/lines
        if (is_head or is_bold_title) and key == name and seen_head < 8:
            seen_head += 1
            continue
        if out and is_head and key == _norm(out[-1]):
            continue
        out.append(block)
        seen_head += 1
    out = _collapse_repeats(out)
    out = ["\n".join(_squash_line(ln) for ln in b.splitlines()) for b in out]
    return f"# {title}\n\n" + "\n\n".join(out) + "\n"
