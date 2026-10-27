"""Stage 5: one self-contained HTML file with every ready recipe.

Recipes are written into the page as plain HTML, so the file is readable where scripts do
not run (iOS Quick Look, mail previews). Where they do, the script builds the app on top of
that markup: search, filters, scaling, favourites and notes, all offline.
"""

import html
import json
import re
from collections import defaultdict
from pathlib import Path

from recipify.categories import Category
from recipify.models import Catalog, Entry, Ingredient, Section, Tier

TEMPLATE = Path(__file__).parent / "templates" / "viewer.html"
SOURCE_KIND = {
    Category.READABLE_PDFS: "PDF",
    Category.DOCX_FILES: "Word document",
    Category.LEGACY_OFFICE: "office document",
    Category.SPREADSHEETS: "spreadsheet",
}
esc = html.escape


def _number(value: float) -> str:
    return f"{value:g}"


def ingredient_html(i: Ingredient) -> str:
    if i.amount is None:
        return f'<li class="bare"><span class="q"></span><span class="n">{esc(i.text)}</span></li>'
    digits = re.search(r"[\d½¼¾⅓⅔⅛]", i.quantity)
    prefix = i.quantity[: digits.start()] if digits else ""
    attrs = f' data-a="{_number(i.amount)}"'
    if i.amount_max is not None:
        attrs += f' data-b="{_number(i.amount_max)}"'
    if "," in i.quantity:
        attrs += ' data-comma=""'
    if prefix:
        attrs += f' data-p="{esc(prefix)}"'
    if i.unit == "%":  # baker's percentages do not scale
        attrs = ""
    unit = f" {esc(i.unit)}" if i.unit else ""
    return (
        f'<li><span class="q"><span class="v"{attrs}>{esc(i.quantity)}</span>{unit}</span>'
        f'<span class="n">{esc(i.name)}</span></li>'
    )


def _label(text: str) -> str:
    return esc(text.rstrip(":. ").strip())


def section_html(s: Section) -> str:
    out = ['<section class="part">' if s.name else '<section class="part cont">']
    if s.name:
        out.append(f"<h3>{esc(s.name)}</h3>")
    out.append('<div class="cols">')
    if s.ingredients:
        head = f"<h4>{_label(s.ingredients_label)}</h4>" if s.ingredients_label else ""
        items = "".join(map(ingredient_html, s.ingredients))
        out.append(f'<div class="ing">{head}<ul>{items}</ul></div>')
    if s.steps or s.method_label:
        head = f"<h4>{_label(s.method_label)}</h4>" if s.method_label else ""
        if len(s.steps) == 1:
            body = f'<p class="step">{esc(s.steps[0])}</p>'
        else:
            body = "<ol>" + "".join(f"<li>{esc(x)}</li>" for x in s.steps) + "</ol>"
        out.append(f'<div class="met">{head}{body}</div>')
    out.append("</div>")
    out += [f'<p class="note">{esc(x)}</p>' for x in s.notes]
    out.append("</section>")
    return "".join(out)


def recipe_html(e: Entry) -> str:
    assert e.recipe is not None
    intro = "".join(f"<p>{esc(x)}</p>" for x in e.recipe.intro)
    parts = "".join(section_html(s) for s in e.recipe.sections)
    return (f'<div class="intro">{intro}</div>' if intro else "") + parts


def source_line(e: Entry) -> str:
    kind = SOURCE_KIND.get(e.category, "document")
    pages = f", {e.pages} page{'s' * (e.pages != 1)}" if e.pages else ""
    if e.unit is not None:
        where = ", ".join(map(str, e.unit_pages))
        pages = f", page{'s' * (len(e.unit_pages) > 1)} {where}; recipe {e.unit} of {e.units}"
    return (
        f"From {esc(Path(e.source).name)} ({kind}{pages}). Every word and number was checked "
        "against the original."
    )


def _labels(e: Entry) -> list[str]:
    return [
        v for f in ("course", "dish", "diet", "cuisine", "ingredients") for v in e.labels.get(f, [])
    ]


def static_section(entries: list[Entry], title: str) -> str:
    """All recipes as plain HTML with a course index: the page without JavaScript."""
    groups: dict[str, list[Entry]] = defaultdict(list)
    for e in entries:
        for course in e.labels.get("course") or ["other"]:
            groups[course].append(e)

    def toc(name: str, items: list[Entry]) -> str:
        links = "".join(f'<li><a href="#r{e.id}">{esc(e.title)}</a></li>' for e in items)
        return f"<details><summary>{esc(name)} ({len(items)})</summary><ul>{links}</ul></details>"

    out = [
        '<div id="static">',
        f'<h1 id="top">{esc(title)}</h1>',
        '<p class="notice"><b>Simple view.</b> This preview does not run the page\'s scripts, so '
        "search, filters, scaling, favourites and notes are off. All "
        f"{len(entries)} recipes are below: open a group and tap a title. "
        '<a href="#open">How to open the full version</a>.</p>',
        '<nav id="toc">',
        toc("All recipes A-Z", entries),
        *(toc(c[:1].upper() + c[1:], groups[c]) for c in sorted(groups)),
        "</nav>",
    ]
    for e in entries:
        labels = esc(json.dumps(e.labels, ensure_ascii=False))
        out.append(
            f'<article id="r{e.id}" data-labels="{labels}">'
            f'<h2 class="rt">{esc(e.title)}</h2>'
            f'<p class="lab">{esc(" · ".join(_labels(e)))}</p>'
            f'<div class="body">{recipe_html(e)}</div>'
            f'<p class="src">{source_line(e)} <a class="up" href="#top">Back to the list</a></p>'
            "</article>"
        )
    out += [
        '<section id="open"><h2>Opening the full version</h2>',
        "<p>The full version needs a browser that runs the page's scripts. Previews do not: "
        "on iPhone and iPad, tapping the file in Files, Mail or Messages shows this simple "
        "view, and so does the space-bar preview on a Mac.</p>",
        "<ul><li><b>Computer:</b> double-click the file to open it in Chrome, Edge, Firefox or "
        "Safari.</li>",
        "<li><b>iPhone / iPad:</b> open the page from a web address, if one was shared with "
        "you, or use a file app with its own browser.</li>",
        "<li><b>Android:</b> open the file with Chrome or Firefox.</li></ul>",
        '<p><a class="up" href="#top">Back to the list</a></p></section>',
        "</div>",
    ]
    return "\n".join(out)


def render(catalog: Catalog, title: str) -> str:
    entries = sorted(catalog.by_tier(Tier.READY), key=lambda e: e.title.casefold())
    stats = {
        "recipes": len(entries),
        "documents": len(catalog.entries),
        "built": catalog.created_at[:10],
    }
    page = TEMPLATE.read_text(encoding="utf-8")
    return (
        page.replace("__TITLE__", esc(title))
        .replace("__STATS__", esc(json.dumps(stats)))
        .replace("__STATIC__", static_section(entries, title))
    )
