"""Standardised filenames and rename suggestions."""

import re
import unicodedata
from pathlib import Path

# Letters NFKD does not decompose to ASCII.
# "¢" is an "ó" mis-decoded from a cp437 zip.
TRANSLITERATION = str.maketrans(
    {
        "ð": "d",
        "Ð": "d",
        "þ": "th",
        "Þ": "th",
        "æ": "ae",
        "Æ": "ae",
        "ø": "o",
        "ß": "ss",
        "¢": "o",
    }
)
COPY_SUFFIX = re.compile(r"\s*\((\d{1,2})\)$")


def slugify(stem: str) -> str:
    """'Þorskur & hörpuskel (tasting)' -> 'thorskur-horpuskel-tasting'."""
    text = unicodedata.normalize("NFKD", stem.translate(TRANSLITERATION))
    text = text.encode("ascii", "ignore").decode().lower()
    text = re.sub(r"[^a-z0-9]+", "-", text).strip("-")
    return text or "untitled"


def standard_name(path: Path) -> str:
    """Standardised filename: ascii slug, '(1)' copies become '-copy1', lowercase suffix."""
    stem = path.stem
    copy = COPY_SUFFIX.search(stem)
    if copy:
        stem = stem[: copy.start()]
    slug = slugify(stem) + (f"-copy{copy.group(1)}" if copy else "")
    suffix = path.suffix.lower().replace(".jpeg", ".jpg")
    return slug + suffix


def rename_plan(paths: list[Path]) -> list[tuple[Path, str]]:
    """Return (path, new_name) for files whose name differs; resolve collisions with -N."""
    taken: set[tuple[Path, str]] = set()
    plan: list[tuple[Path, str]] = []
    for path in sorted(paths):
        new = standard_name(path)
        base, n = Path(new), 2
        while (path.parent, new) in taken:
            new = f"{base.stem}-{n}{base.suffix}"
            n += 1
        taken.add((path.parent, new))
        if new != path.name:
            plan.append((path, new))
    return plan
