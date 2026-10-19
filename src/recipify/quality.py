"""Heuristic language detection and output-quality scoring for extracted markdown.

Scores are 0-1. They flag text that is garbled or hard to read (broken spacing,
mojibake, non-words); they cannot prove a transcription is faithful.
"""

import re
from dataclasses import asdict, dataclass, field

REVIEW_THRESHOLD = 0.8

ICELANDIC_CHARS = set("þðÞÐáéíóúýÁÉÍÓÚÝöÖæÆ")
ICELANDIC_ONLY = set("þðÞÐ")
ICELANDIC_WORDS = {
    "og",
    "með",
    "til",
    "að",
    "er",
    "í",
    "á",
    "af",
    "við",
    "sem",
    "það",
    "fyrir",
    "út",
    "svo",
    "í",
    "eða",
    "þar",
    "um",
    "sett",
    "bætt",
    "soðið",
    "hráefni",
    "aðferð",
    "stk",
    "msk",
    "tsk",
    "gr",
    "ml",
    "mín",
    "smjör",
    "salt",
    "pipar",
    "hveiti",
    "sykur",
    "egg",
}
ENGLISH_WORDS = {
    "the",
    "and",
    "of",
    "to",
    "in",
    "with",
    "for",
    "add",
    "until",
    "minutes",
    "cup",
    "cups",
    "teaspoon",
    "tablespoon",
    "mix",
    "bake",
    "salt",
    "pepper",
    "butter",
    "sugar",
    "flour",
    "ingredients",
    "serve",
    "heat",
    "stir",
    "oil",
    "water",
}
WORD_RE = re.compile(r"[^\W\d_]+(?:['’-][^\W\d_]+)*", re.UNICODE)
VOWELS = set("aeiouyáéíóúýöæåäøAEIOUYÁÉÍÓÚÝÖÆ")
# single letters that are legitimate in recipes (units, "s og p", conjunctions, "x" as times)
SINGLE_OK = set("aiáíoóöspgxlcdhmtf")
MARKUP_RE = re.compile(r"\*\(.*?\)\*|\[\?\]|[#>*_`|~\-]+|\(.*?\)")


@dataclass
class Quality:
    score: float
    method: str = "heuristic"
    flags: list[str] = field(default_factory=list)
    notes: str = ""

    def to_dict(self) -> dict:
        return asdict(self)


def _words(text: str) -> list[str]:
    return WORD_RE.findall(text)


def detect_language(text: str) -> str:
    """Return 'is', 'en', 'mixed' or 'unknown'."""
    words = [w.lower() for w in _words(text)]
    if len(words) < 5:
        return "unknown"
    letters = [c for c in text if c.isalpha()]
    ice_char_ratio = sum(c in ICELANDIC_ONLY for c in letters) / max(len(letters), 1)
    is_hits = sum(w in ICELANDIC_WORDS for w in words) / len(words) + ice_char_ratio * 5
    en_hits = sum(w in ENGLISH_WORDS for w in words) / len(words)
    if is_hits < 0.03 and en_hits < 0.03:
        return "unknown"
    if is_hits > 2 * en_hits:
        return "is"
    if en_hits > 2 * is_hits:
        return "en"
    return "mixed"


def _plausible(word: str) -> bool:
    if len(word) <= 3:
        return True
    if not any(c in VOWELS for c in word):
        return word.isupper() and len(word) <= 5  # abbreviations
    run = max((len(m) for m in re.findall(r"[^aeiouyáéíóúýöæåäøAEIOUYÁÉÍÓÚÝÖÆ]+", word)), default=0)
    return run <= 5


def score_text(text: str, language: str | None = None) -> Quality:
    """Heuristic readability score for generated markdown."""
    body = MARKUP_RE.sub(" ", text)
    words = _words(body)
    flags: list[str] = []
    if len(words) < 5:
        return Quality(0.1, flags=["almost_no_text"])

    score = 1.0
    plausible = sum(_plausible(w) for w in words) / len(words)
    if plausible < 0.97:
        flags.append("nonwords")
    score *= plausible

    single = sum(len(w) == 1 and w.lower() not in SINGLE_OK for w in words) / len(words)
    if single > 0.08:
        flags.append("broken_spacing")
        score *= max(0.2, 1 - 3 * single)

    bad_chars = body.count("\ufffd") + len(re.findall(r"Ã[\x80-\xbf]|â€", body))
    if bad_chars:
        flags.append("mojibake")
        score *= max(0.1, 1 - 20 * bad_chars / max(len(body), 1))

    lang = language or detect_language(body)
    if lang == "unknown":
        flags.append("language_unrecognised")
        score *= 0.8

    avg = sum(map(len, words)) / len(words)
    if avg > 9 or avg < 2.5:
        flags.append("odd_word_length")
        score *= 0.7
    if len(words) < 20:
        flags.append("very_short")
        score *= 0.85
    return Quality(round(max(0.0, min(1.0, score)), 2), flags=flags)
