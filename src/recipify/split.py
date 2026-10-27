"""Stage 2b: split documents that hold several recipes into one unit per recipe.

Only clear, page-aligned splits are made; when in doubt a document stays whole, and the
reason is recorded. A document is split at its page breaks (PDF pages, or explicit page
breaks in Word) when all of these hold:

- its file name or title says it is a collection ("Kökur - uppskriftir", "Breakfast recipes");
  a dish's own pages are often its components (a sauce,
  a garnish) laid out exactly like separate recipes, so the name is the deciding signal;
- every page with its own title starts a recipe (a title over named components, or a
  title directly over an ingredient list); untitled pages continue the recipe before them;
- most resulting parts (75%, and at least two) are recipes on their own, not fragments
  (measured ingredients, 25+ words); the thin ones are still separate units, and the
  assessment decides whether they are ready;
- no two parts carry exactly the same numbers (a translation of the same recipe);
- a header repeated on every page names the recipes ("Gulrótarkaka & Hjónabandssæla" over
  "Gulrótarkaka" and "Hjónabandssæla"); otherwise it is a category ("Sósur") and the
  document stays whole.

"""

import hashlib
import re
from collections import Counter

from recipify.models import Recipe, Split, Unit
from recipify.structure import rules
from recipify.structure.quantities import parse_ingredient
from recipify.text import fold, tokens
from recipify.vocabulary import Vocabulary

ENGINE, VERSION = "pages", 2
MIN_MEASURED, MIN_WORDS = 2, 25
MIN_COMPLETE_SHARE = 0.75  # thin parts are kept (and assessed) if most parts are recipes
# A line of a table of contents: "Skyrkaka 3", "12 | Vanilla ice cream", "Brauð ....... 4".
CONTENTS_LINE = re.compile(r"^\d+\s*(?:\||$)|[\s.]\d+$")


def pages(text: str) -> list[str]:
    """The text of each page (pages are separated by a line holding only a form feed)."""
    out: list[str] = []
    current: list[str] = []
    for line in text.split("\n"):
        if line.strip(" \t\r") == "\f":
            out.append("\n".join(current))
            current = []
        else:
            current.append(line)
    out.append("\n".join(current))
    return out


def _first_line(page: str) -> str:
    return next((line.strip() for line in page.splitlines() if line.strip()), "")


def _without_first_line(page: str) -> str:
    lines = page.split("\n")
    first = next(i for i, line in enumerate(lines) if line.strip())
    return "\n".join(lines[first + 1 :])


def _shape(recipe: Recipe) -> str:
    """'named' (title over named components or an intro), 'direct' (title over an ingredient
    list) or 'untitled' (the page continues the one before)."""
    if not recipe.title_in_text or not recipe.sections or recipe.title[:1].islower():
        return "untitled"  # a page that opens mid-sentence continues the one before
    first = recipe.sections[0]
    return "direct" if first.ingredients and not (first.name or recipe.intro) else "named"


def _front_matter(page: str) -> bool:
    """A cover (a title and little else) or a table of contents, ahead of the recipes."""
    lines = [line.strip() for line in page.splitlines() if line.strip()]
    if len(lines) <= 3:
        return not any(parse_ingredient(line) for line in lines)
    contents = sum(bool(CONTENTS_LINE.search(line)) for line in lines)
    return contents / len(lines) >= 0.6


def _category(page: str) -> str:
    """'# Eftirréttir' over '## Skyrkaka': the first heading names a section of the book."""
    lines = [line.strip() for line in page.splitlines() if line.strip()]
    if len(lines) >= 2 and lines[0].startswith("#") and lines[1].startswith("#"):
        if len(lines[0]) - len(lines[0].lstrip("#")) <= len(lines[1]) - len(lines[1].lstrip("#")):
            return lines[0]
    return ""


def _complete(recipe: Recipe) -> bool:
    """A recipe rather than a fragment; whether its method is clear is assessed later."""
    measured = sum(i.amount is not None for s in recipe.sections for i in s.ingredients)
    return measured >= MIN_MEASURED and len(tokens("\n".join(recipe.lines()))) >= MIN_WORDS


def _numbers(text: str) -> Counter[str]:
    return Counter(t for t in tokens(text) if t.isdigit())


def _unit(index: int, page_numbers: list[int], texts: list[str], dropped: list[str]) -> Unit:
    text = "\n\f\n".join(texts)
    return Unit(
        index=index,
        pages=page_numbers,
        title=rules.structure(text, "").title,
        text=text,
        sha256=hashlib.sha256(text.encode("utf-8")).hexdigest(),
        dropped=dropped,
    )


def _whole(text: str, reason: str) -> tuple[str, list[str], list[Unit]]:
    return "whole", [reason], [_unit(1, list(range(1, len(pages(text)) + 1)), [text], [])]


def plan(
    text: str, name: str, words: Vocabulary | None = None
) -> tuple[str, list[str], list[Unit]]:
    """(decision, reasons, units) for one document's text; `name` is its file name."""
    collection = (words or Vocabulary()).collection
    numbered = [(n, p) for n, p in enumerate(pages(text), 1) if p.strip()]
    if len(numbered) < 2:
        return _whole(text, "one page")
    if not collection.search(fold(f"{name} {_first_line(numbered[0][1])}")):
        return _whole(text, "not named as a collection of recipes, so pages may be one dish")
    front: list[str] = []  # a cover and a table of contents are set aside, not recipes
    while len(numbered) > 2 and _front_matter(numbered[0][1]):
        front.append(numbered.pop(0)[1])

    firsts = [fold(_first_line(p)) for _, p in numbered]
    header = _first_line(numbered[0][1]) if len(set(firsts)) == 1 else ""
    if header:
        bodies = [(n, _without_first_line(p)) for n, p in numbered]
        names = [fold(_first_line(b)) for _, b in bodies]
        if not all(name and name in fold(header) for name in names):
            return _whole(text, "every page repeats a header that does not name the recipes")
    else:
        bodies = list(numbered)
    categories = [_category(body) for _, body in bodies]
    bodies = [
        (n, _without_first_line(b) if c else b)
        for (n, b), c in zip(bodies, categories, strict=True)
    ]

    shapes = [_shape(rules.structure(body, "")) for _, body in bodies]
    if shapes[0] == "untitled":
        return _whole(text, "the first page has no title")
    groups: list[list[int]] = []
    for i, shape in enumerate(shapes):
        if shape == "untitled":
            groups[-1].append(i)  # continues the recipe on the page before
        else:
            groups.append([i])
    if len(groups) < 2:
        return _whole(text, "the pages continue one recipe")

    # The first page may open with the collection's own heading ("Brauð", "Jólauppskriftir
    # hússins") above its first recipe: that line names the document, not
    # the recipe, so it is set aside like a running header.
    heading = ""
    others = [shapes[g[0]] for g in groups[1:]]
    first_line = _first_line(bodies[0][1])
    by_name = bool(collection.search(fold(first_line)))
    by_layout = shapes[0] == "named" and others.count("direct") > len(others) / 2
    if by_name or by_layout:
        heading = first_line
        bodies[0] = (bodies[0][0], _without_first_line(bodies[0][1]))

    units = [
        _unit(
            k,
            [bodies[i][0] for i in g],
            [bodies[i][1] for i in g],
            (front + [heading] if k == 1 and heading else front if k == 1 else [])
            + ([header] * len(g) if header else [])  # header lines removed from the pages
            + [categories[i] for i in g if categories[i]],
        )
        for k, g in enumerate(groups, 1)
    ]
    incomplete = [u.title for u in units if not _complete(rules.structure(u.text, ""))]
    complete = len(units) - len(incomplete)
    if complete < 2 or complete < MIN_COMPLETE_SHARE * len(units):
        return _whole(text, f"too few parts are complete recipes ({', '.join(incomplete)})")
    signatures = [_numbers(u.text) for u in units]
    if any(a == b for i, a in enumerate(signatures) for b in signatures[i + 1 :]):
        return _whole(text, "two parts have the same quantities (a translation?)")
    reason = f"{len(units)} recipes, each starting on a new page with its own title"
    if incomplete:
        reason += f" ({len(incomplete)} without a full ingredient list)"
    if header:
        reason += f" under the shared header {header!r}"
    if heading:
        reason += f"; the heading {heading!r} above the first recipe names the collection"
    if front:
        reason += f"; {len(front)} page(s) of front matter (cover, contents) set aside"
    if any(categories):
        reason += f"; {sum(map(bool, categories))} section heading(s) set aside"
    return "split", [reason], units


def split(
    sha256: str,
    extraction: str,
    text: str,
    name: str,
    keep_whole: bool = False,
    words: Vocabulary | None = None,
) -> Split:
    if keep_whole:
        decision, reasons, units = _whole(text, "kept whole by hand in curation.json")
    else:
        decision, reasons, units = plan(text, name, words)
    result = Split(
        sha256=sha256,
        engine=ENGINE,
        version=VERSION,
        extraction=extraction,
        decision=decision,
        by_hand=keep_whole,
        reasons=reasons,
        units=units,
    )
    check(text, result)
    return result


def check(text: str, result: Split) -> None:
    """Every word of the document is in exactly one unit, or in a dropped header line."""
    parts = [u.text for u in result.units] + [h for u in result.units for h in u.dropped]
    if Counter(tokens("\n".join(parts))) != Counter(tokens(text)):
        raise ValueError("the split lost or repeated words of the document")
