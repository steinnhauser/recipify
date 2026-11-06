"""End to end: the whole free pipeline on the sample documents in examples/sources."""

from pathlib import Path

from recipify import pipeline, viewer
from recipify.categories import Category
from recipify.curation import Curation
from recipify.models import Tier
from recipify.store import Workspace

EXAMPLES = Path(__file__).parent.parent / "examples" / "sources"


def test_examples_end_to_end(tmp_path: Path):
    ws = Workspace(EXAMPLES, tmp_path)
    inv = pipeline.run_inventory(ws, Curation())
    pipeline.run_extract(ws, inv)
    pipeline.run_split(ws, inv, Curation())
    pipeline.run_structure(ws, inv)
    catalog = pipeline.build_catalog(ws, inv, Curation())

    ready = catalog.by_tier(Tier.READY)
    assert len(ready) == 16
    checked = [e for e in ready if e.category != Category.MARKDOWN]
    assert all(e.assessment.fidelity == e.assessment.precision == 1.0 for e in checked)
    reasons = {
        e.source: e.assessment.reasons[0]
        for e in catalog.entries
        if e.assessment.tier != Tier.READY
    }
    assert reasons == {
        "Costing - lamb shank.xlsx": "reference material, not a recipe",
        "Kitchen handbook 2019.pdf": "book (14 pages): not split into recipes yet",
        "Missi listi.docx": "reference material, not a recipe",
        "Restaurant/Desserts/Chocolate mousse.pdf": (
            "same recipe as Restaurant/Desserts/Chocolate mousse.docx"
        ),
        "Scans/Beetroot salad.png": "needs a transcription (no text layer)",
    }
    plokkfiskur = next(e for e in ready if e.source == "Restaurant/Mains/Plokkfiskur.pdf")
    assert plokkfiskur.duplicates == ["Old/Plokkfiskur (1).pdf"]

    skyr = next(e for e in ready if e.title == "Skyr, bláber og hafrar")
    assert skyr.recipe is not None
    assert [s.name for s in skyr.recipe.sections] == ["Skyrkrem", "Hafracrumble", "Bláberjagel"]
    assert all(s.method_label == "Aðferð:" and s.notes for s in skyr.recipe.sections)
    assert skyr.labels["course"] == ["dessert"]

    cod = next(e for e in ready if e.title.startswith("Cod"))
    assert cod.recipe is not None and len(cod.recipe.sections) == 3
    assert cod.recipe.intro == ["Serves 4. Main course."]

    cakes = [e for e in ready if e.source == "Bakery/Kökur - uppskriftir.pdf"]
    assert [(e.unit, e.units, e.unit_pages, e.title) for e in cakes] == [
        (1, 2, [1], "Gulrótarkaka"),
        (2, 2, [2], "Hjónabandssæla"),
    ]
    assert [e.id[-2:] for e in cakes] == ["-1", "-2"]

    soup = next(e for e in ready if e.category == Category.MARKDOWN)
    assert (soup.source, soup.title) == ("Home/Barley and kale soup.md", "Barley and kale soup")
    assert soup.labels["cuisine"] == ["Nordic"] and soup.recipe is not None
    assert soup.recipe.sections[0].steps[0].startswith("Melt the butter")

    page = viewer.render(catalog, "demo")
    assert page.split("<script>\ntry")[0].count('<article id="r') == 16
    assert "page 2; recipe 2 of 2" in page
