"""The viewer in a real browser: editing, export and the parser shared with the pipeline.

Run with ``uv run pytest -m browser`` (add ``--browser-channel chrome`` to use an installed
Chrome instead of Playwright's Chromium).
"""

from pathlib import Path

import pytest
from playwright.sync_api import Page, expect

from recipify import viewer
from recipify.models import Catalog, Tier
from recipify.structure.quantities import parse_ingredient
from tests.test_viewer import _entry

pytestmark = pytest.mark.browser


@pytest.fixture
def starter(tmp_path: Path) -> Path:
    other = _entry(id="ffffffffffff", title="Annað")
    page = viewer.render(Catalog(entries=[_entry(), other]), "Mínar uppskriftir", editable=True)
    path = tmp_path / "starter.html"
    path.write_text(page, encoding="utf-8")
    return path


def _static(html: str) -> str:
    return html[html.index('<div id="static">') : html.index("<script>\ntry")]


def test_add_edit_remove_and_export(page: Page, starter: Path, tmp_path: Path):
    page.on("dialog", lambda d: d.accept())  # confirm() before removing
    page.goto(starter.as_uri())
    expect(page.locator("#count")).to_have_text("2 recipes")

    page.click("#new")
    page.fill("#e-title", "Rúgbrauð")
    page.fill("#e-course", "bread & pastry")
    page.fill(".p-ing", "500 g rúgmjöl\n1,5 tsk salt\nSmá síróp")
    page.fill(".p-steps", "Allt hrært saman.\nBakað við 100°C í 8 klst.")
    page.click("#edit-save")
    expect(page.locator("h2.title")).to_have_text("Rúgbrauð")
    page.click(".scale button[data-f='2']")
    expect(page.locator(".ing .q")).to_have_text(["1000 g", "3 tsk", ""])

    page.click("#items .item >> text=Ostakaka")
    page.click("#edit")
    page.fill("#e-title", "Ostakaka hússins")
    page.click("#edit-save")
    expect(page.locator(".src")).to_contain_text("Edited by hand")
    expect(page.locator(".src")).not_to_contain_text("Every word and number was checked")

    page.click("#items .item >> text=Annað")
    page.click("#del")
    expect(page.locator("#count")).to_have_text("2 recipes")

    page.reload()  # unsaved changes live in this browser until they are exported
    expect(page.locator("#count")).to_have_text("2 recipes")
    page.click("#export")
    expect(page.locator("#changelist li")).to_have_count(3)
    page.fill("#x-name", "Mínar uppskriftir.HTML")
    expect(page.locator("#x-saves")).to_have_text("Saves as: Mínar uppskriftir.html")
    with page.expect_download() as download:
        page.click("#x-download")
    assert download.value.suggested_filename == "Mínar uppskriftir.html"
    exported = tmp_path / "exported.html"
    download.value.save_as(exported)
    expect(page.locator("#x-after")).to_be_visible()

    fresh = page.context.browser.new_context().new_page()  # no storage: only the file counts
    fresh.goto(exported.as_uri())
    expect(fresh.locator("#items .item b")).to_have_text(["Ostakaka hússins ✎", "Rúgbrauð ✎"])
    html = exported.read_text(encoding="utf-8")
    assert "Annað" not in _static(html) and "Rúgbrauð" in _static(html)
    assert 'class="nojs"' in html.split("\n", 2)[1]  # readable without JavaScript again

    page.click("#x-clear")  # back to the original file's content
    expect(page.locator("#count")).to_have_text("2 recipes")
    expect(page.locator("#items .item b").first).to_have_text("Annað")


def test_an_unchanged_export_is_the_page_itself(page: Page, starter: Path):
    page.goto(starter.as_uri())
    exported = page.evaluate("window.recipify.exportPage()")
    assert _static(exported) == _static(starter.read_text(encoding="utf-8"))


def test_file_names(page: Page, starter: Path):
    page.goto(starter.as_uri())
    names = {
        "": "recipify.html",
        "  Menu.HTML ": "Menu.html",
        "a/b:c": "a-b-c.html",
        "Kökur.html.html": "Kökur.html.html",  # only one extension is removed, then added back
    }
    for typed, expected in names.items():
        assert page.evaluate("n => window.recipify.fileName(n)", typed) == expected


LINES = [
    "125gr smjör", "1,5 l mysa", "1 ½ tsk timían", "2-3 msk Dijon", "ca. 4stk sítróna",
    "Rolled oats 250 g", "Oat milk 1L", "100% - 1000 g epli", "2 egg", "Salt",
    "140°C, vifta 2", "1. Sjóðið", "4 x 2,5",
]  # fmt: skip


def test_the_page_parses_ingredients_like_the_pipeline(page: Page, starter: Path):
    page.goto(starter.as_uri())
    for line in LINES:
        py = parse_ingredient(line)
        js = page.evaluate("l => window.recipify.parseIngredient(l)", line)
        if py is None:
            assert js is None, line
            continue
        expected = (py.amount, py.amount_max, py.quantity, py.unit, py.name)
        assert (js["a"], js["b"], js["quantity"], js["unit"], js["name"]) == expected, line


def test_the_private_build_cannot_edit(page: Page, tmp_path: Path):
    path = tmp_path / "private.html"
    path.write_text(viewer.render(Catalog(entries=[_entry()]), "x"), encoding="utf-8")
    page.goto(path.as_uri())
    expect(page.locator("#new")).to_be_hidden()
    expect(page.locator("#export")).to_be_hidden()
    assert page.evaluate("typeof window.recipify") == "undefined"
    assert Tier.READY  # the entry fixture is ready
