"""Small text helpers shared by the stages (Icelandic-aware)."""

import re
import unicodedata

# Letters NFKD does not decompose to ASCII. "¢" is an "ó" mis-decoded from a cp437 zip.
TRANSLITERATION = str.maketrans(
    {"ð": "d", "Ð": "d", "þ": "th", "Þ": "th", "æ": "ae", "Æ": "ae", "ø": "o", "ß": "ss", "¢": "o"}
)
TOKEN = re.compile(r"\w+")


def fold(text: str) -> str:
    """Lowercase, strip accents and map Icelandic letters, so one pattern covers spellings."""
    text = text.lower().translate(TRANSLITERATION).replace("ö", "o")
    return "".join(c for c in unicodedata.normalize("NFD", text) if not unicodedata.combining(c))


def slugify(text: str) -> str:
    """'Þorskur & hörpuskel (tasting)' -> 'thorskur-horpuskel-tasting'."""
    ascii_text = unicodedata.normalize("NFKD", text.translate(TRANSLITERATION))
    ascii_text = ascii_text.encode("ascii", "ignore").decode().lower()
    return re.sub(r"[^a-z0-9]+", "-", ascii_text).strip("-") or "untitled"


def tokens(text: str) -> list[str]:
    """Words and numbers, case-folded: the unit the fidelity check counts."""
    return TOKEN.findall(unicodedata.normalize("NFC", text).casefold())


def fix_mojibake(text: str) -> str:
    """Repair names that were cp850 bytes shown as latin-1 (e.g. 'S¢sa' -> 'Sósa')."""
    if not re.search(r"[¢£\x80-\x9f]", text):
        return text
    try:
        return text.encode("latin-1").decode("cp850")
    except UnicodeError:
        return text
