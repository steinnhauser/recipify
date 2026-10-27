import pytest

from recipify import viewer
from recipify.categories import Category
from recipify.lock import decrypt_page, encrypt_page
from recipify.models import Assessment, Catalog, Entry, Ingredient, Kind, Recipe, Section, Tier


def _entry(**kw) -> Entry:
    recipe = Recipe(
        title="Ostakaka",
        intro=["Fyrir 10."],
        sections=[
            Section(
                name="Ostakrem",
                ingredients_label="Hráefni:",
                ingredients=[
                    Ingredient(
                        text="1,5 kg ostur", amount=1.5, quantity="1,5", unit="kg", name="ostur"
                    ),
                    Ingredient(
                        text="ca. 2-3 stk egg",
                        amount=2,
                        amount_max=3,
                        quantity="ca. 2-3",
                        unit="stk",
                        name="egg",
                    ),
                    Ingredient(
                        text="100% - 1000 g epli",
                        amount=100,
                        quantity="100",
                        unit="%",
                        name="- 1000 g epli",
                    ),
                    Ingredient(text="Salt <b>", name="Salt <b>"),
                ],
                method_label="Aðferð:",
                steps=["Hrært.", "Kælt."],
                notes=["Geymsluþol: 4 dagar."],
            ),
            Section(method_label="Aðferð", steps=["Borið fram."]),
        ],
    )
    defaults = dict(
        id="0123456789ab",
        source="Eftirréttir/Ostakaka.pdf",
        category=Category.READABLE_PDFS,
        kind=Kind.RECIPE,
        pages=1,
        title="Ostakaka",
        labels={"course": ["dessert"], "diet": ["sweet"]},
        assessment=Assessment(tier=Tier.READY),
        recipe=recipe,
    )
    return Entry(**(defaults | kw))


def test_ingredient_and_section_markup():
    html = viewer.recipe_html(_entry())
    assert '<span class="v" data-a="1.5" data-comma="">1,5</span> kg' in html
    assert 'data-a="2" data-b="3" data-p="ca. "' in html
    assert '<span class="v">100</span> %' in html  # percentages do not scale
    assert 'class="bare"' in html and "Salt &lt;b&gt;" in html
    assert "<h4>Hráefni</h4>" in html and "<h4>Aðferð</h4>" in html
    assert "<ol><li>Hrært.</li><li>Kælt.</li></ol>" in html
    assert '<p class="step">Borið fram.</p>' in html
    assert '<p class="note">Geymsluþol: 4 dagar.</p>' in html
    assert '<div class="intro"><p>Fyrir 10.</p></div>' in html


def test_render_page():
    other = _entry(
        id="ffffffffffff", title="Annað", category=Category.DOCX_FILES, pages=None, labels={}
    )
    hidden = _entry(id="eeeeeeeeeeee", title="Falið", assessment=Assessment(tier=Tier.REVIEW))
    page = viewer.render(Catalog(entries=[_entry(), other, hidden]), "Uppskriftir")
    assert "<title>Uppskriftir</title>" in page
    assert page.split("<script>\ntry")[0].count('<article id="r') == 2 and "Falið" not in page
    assert "From Eftirréttir/Ostakaka.pdf (PDF, 1 page). Trace id 0123456789ab." in page
    assert "From Eftirréttir/Ostakaka.pdf (Word document). Trace id ffffffffffff." in page
    assert "Other (1)" in page and "Dessert (1)" in page
    assert "&quot;recipes&quot;: 2" in page


def test_source_line_names_the_original():
    split = _entry(
        id="0123456789ab-2",
        unit=2,
        units=3,
        unit_pages=[3, 4],
        duplicates=["Afrit/Ostakaka.pdf", "Gamalt/Ostakaka.pdf"],
    )
    assert viewer.source_line(split) == (
        "From Eftirréttir/Ostakaka.pdf (PDF, pages 3, 4; recipe 2 of 3). Identical copies: "
        "Afrit/Ostakaka.pdf; Gamalt/Ostakaka.pdf. Trace id 0123456789ab-2. Every word and "
        "number was checked against the original."
    )
    copy = viewer.source_line(_entry(duplicates=["Afrit/<Ostakaka>.pdf"]))
    assert "Identical copy: Afrit/&lt;Ostakaka&gt;.pdf." in copy
    photo = _entry(source="Myndir/kaka.jpeg", category=Category.IMAGE_FILES, pages=None)
    assert viewer.source_line(photo) == (
        "From Myndir/kaka.jpeg (photo). Trace id 0123456789ab. Transcribed by reading the "
        "image, then reviewed by hand."
    )
    scan = _entry(category=Category.IMAGE_BASED_PDFS, pages=2)
    assert "(scan, 2 pages)" in viewer.source_line(scan)


def test_lock_roundtrip():
    locked = encrypt_page("<p>secret</p>", "key", title="Locked")
    assert "secret" not in locked and "<title>Locked</title>" in locked
    assert decrypt_page(locked, "key") == "<p>secret</p>"
    with pytest.raises(ValueError):
        encrypt_page("x", "")


def test_editable_page():
    import json
    from html import unescape

    plain = viewer.render(Catalog(entries=[_entry()]), "Uppskriftir")
    assert 'data-editable=""' in plain and "data-recipe=" not in plain.split("<script>\ntry")[0]
    page = viewer.render(Catalog(entries=[_entry()]), "Uppskriftir", editable=True)
    assert 'data-editable="1"' in page and 'data-units="kg|' in page
    data = json.loads(unescape(page.split('data-recipe="')[1].split('"')[0]))
    assert data["title"] == "Ostakaka"
    assert data["sections"][0]["ingredients"][0] == "1,5 kg ostur"
    assert data["sections"][0]["method_label"] == "Aðferð:"
    # the collection id is stable, so favourites and notes survive rebuilds and exports
    collection = page.split('data-collection="')[1][:12]
    assert collection == viewer.render(Catalog(), "Uppskriftir").split('data-collection="')[1][:12]
