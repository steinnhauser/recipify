"""Stage 4a: decide how far each converted recipe can be trusted.

The central check is **fidelity**: the words and numbers of the extracted source text are
counted and compared with those the reader will see (plus the few lines the structurer
dropped on purpose). For text-layer documents the extracted text *is* the document, so
fidelity 1.0 with precision 1.0 means nothing was lost, changed or invented on the way.

A recipe is ``ready`` only when every check passes; otherwise it goes to ``review`` with
the reasons, and the report lists them.
"""

import re
from collections import Counter

from recipify.categories import NO_TEXT_LAYER, Category
from recipify.models import Assessment, Extraction, Kind, Recipe, SourceFile, Structured, Tier
from recipify.text import tokens

MIN_WORDS, MAX_WORDS = 25, 3000
# School assignments and exams: several dishes per document, with student and teacher names.
COURSEWORK = re.compile(
    r"\b(?:nemandi|nemendur|kennari|kennarar|námsta[ðd]ur|sveinspróf|i[ðd]an fræðslusetur)\b",
    re.I,
)
MIN_TEXT_QUALITY = 0.9
MAX_UNSTRUCTURED = 0.4  # share of words that sit in intro/notes rather than lists and steps

ICELANDIC_ONLY = set("þðÞÐ")
ICELANDIC_WORDS = set(
    "og með til að er í á af við sem það fyrir út svo eða þar um sett bætt soðið hráefni "
    "aðferð stk msk tsk gr ml mín smjör salt pipar hveiti sykur egg".split()
)
ENGLISH_WORDS = set(
    "the and of to in with for add until minutes cup cups teaspoon tablespoon mix bake salt "
    "pepper butter sugar flour ingredients serve heat stir oil water".split()
)
WORD = re.compile(r"[^\W\d_]+(?:['’-][^\W\d_]+)*")
VOWELS = "aeiouyáéíóúýöæåäøAEIOUYÁÉÍÓÚÝÖÆ"
CONSONANT_RUN = re.compile(f"[^{VOWELS}]+")
SINGLE_OK = set("aiáíoóöspgxlcdhmtf")  # one-letter words that are normal in recipes


def detect_language(text: str) -> str:
    """'is', 'en', 'mixed' or 'unknown'."""
    words = [w.lower() for w in WORD.findall(text)]
    if len(words) < 5:
        return "unknown"
    letters = [c for c in text if c.isalpha()]
    ice_chars = sum(c in ICELANDIC_ONLY for c in letters) / max(len(letters), 1)
    is_hits = sum(w in ICELANDIC_WORDS for w in words) / len(words) + 5 * ice_chars
    en_hits = sum(w in ENGLISH_WORDS for w in words) / len(words)
    if is_hits < 0.03 and en_hits < 0.03:
        return "unknown"
    if is_hits > 2 * en_hits:
        return "is"
    return "en" if en_hits > 2 * is_hits else "mixed"


def _plausible(word: str) -> bool:
    if len(word) <= 3:
        return True
    if not any(c in VOWELS for c in word):
        return word.isupper() and len(word) <= 5  # abbreviations
    return max(map(len, CONSONANT_RUN.findall(word)), default=0) <= 5


def text_quality(text: str) -> tuple[float, list[str]]:
    """0-1 readability score; flags garbled text (broken spacing, mojibake, non-words)."""
    words = WORD.findall(text)
    if len(words) < 5:
        return 0.1, ["almost_no_text"]
    flags: list[str] = []
    score = sum(map(_plausible, words)) / len(words)
    if score < 0.97:
        flags.append("non-words")
    single = sum(len(w) == 1 and w.lower() not in SINGLE_OK for w in words) / len(words)
    if single > 0.08:
        flags.append("broken spacing")
        score *= max(0.2, 1 - 3 * single)
    bad = text.count("�") + len(re.findall(r"Ã[\x80-\xbf]|â€", text))
    if bad:
        flags.append("mojibake")
        score *= max(0.1, 1 - 20 * bad / max(len(text), 1))
    return round(score, 3), flags


def fidelity(source: str, recipe: Recipe) -> tuple[float, float]:
    """(recall, precision) of the recipe's words against the source's words."""
    src = Counter(tokens(source))
    shown = Counter(tokens("\n".join(recipe.lines() + recipe.dropped)))
    common = sum((src & shown).values())
    recall = common / max(sum(src.values()), 1)
    precision = common / max(sum(shown.values()), 1)
    return round(recall, 4), round(precision, 4)


def _excluded(file: SourceFile) -> str | None:
    if file.duplicate_of:
        return f"duplicate of {file.duplicate_of}"
    if file.kind == Kind.BOOK:
        pages = f" ({file.pages} pages)" if file.pages else ""
        return f"book{pages}: not split into recipes yet"
    if file.kind == Kind.REFERENCE:
        return "reference material, not a recipe"
    if file.kind == Kind.PHOTO:
        return "photo of a dish, not a recipe"
    if file.category in (Category.EMPTY_OR_CORRUPTED, Category.IGNORED, Category.OTHER_FORMATS):
        return f"{file.category.value.replace('_', ' ')}: {file.reason}"
    return None


def assess(
    file: SourceFile, extraction: Extraction | None, structured: Structured | None
) -> Assessment:
    if reason := _excluded(file):
        return Assessment(tier=Tier.EXCLUDED, reasons=[reason])
    if extraction is None:
        missing = (
            "needs a transcription (no text layer)"
            if file.category in NO_TEXT_LAYER
            else "not extracted yet"
        )
        return Assessment(tier=Tier.EXCLUDED, reasons=[missing])
    if structured is None:
        return Assessment(tier=Tier.EXCLUDED, reasons=["not structured yet"])

    if COURSEWORK.search(extraction.text):
        return Assessment(tier=Tier.EXCLUDED, reasons=["course material: a school assignment"])

    recipe = structured.recipe
    shown = "\n".join(recipe.lines())
    recall, precision = fidelity(extraction.text, recipe)
    quality, flags = text_quality(shown)
    words = len(tokens(shown))
    agreement = extraction.checks.get("order_agreement")
    reasons: list[str] = []

    if file.category in NO_TEXT_LAYER:
        reasons.append("read from images: cannot be checked against a text layer")
    if file.category == Category.SPREADSHEETS:
        reasons.append("spreadsheet: tables are not structured into recipes yet")
    if recall < 1 or precision < 1:
        reasons.append(f"text differs from the source (recall {recall}, precision {precision})")
    if agreement is not None and agreement < 1:
        reasons.append(f"reading order uncertain ({agreement:.1%} of lines agree)")
    if quality < MIN_TEXT_QUALITY:
        reasons.append(f"text looks garbled ({', '.join(flags)})")
    measured = sum(i.amount is not None for s in recipe.sections for i in s.ingredients)
    if recipe.ingredient_count() < 2:
        reasons.append("no ingredient list found")
    elif measured < 2:
        reasons.append("fewer than 2 measured ingredients: a plating guide, not a recipe")
    if recipe.step_count() < 1:
        reasons.append("no method found")
    if words > MAX_WORDS:
        return Assessment(
            tier=Tier.EXCLUDED,
            reasons=[f"collection ({words} words): not split into recipes yet"],
            words=words,
        )
    if words < MIN_WORDS:
        reasons.append(f"very little text ({words} words)")
    loose = sum(len(tokens(x)) for s in recipe.sections for x in s.notes)
    loose += sum(len(tokens(x)) for x in recipe.intro)
    if words and loose / words > MAX_UNSTRUCTURED:
        reasons.append(f"mostly unstructured text ({loose / words:.0%} outside lists and steps)")

    return Assessment(
        tier=Tier.REVIEW if reasons else Tier.READY,
        reasons=reasons,
        fidelity=recall,
        precision=precision,
        order_agreement=agreement,
        text_quality=quality,
        language=detect_language(shown),
        words=words,
    )
