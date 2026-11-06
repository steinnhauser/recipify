"""Recipes written in markdown: read as written, straight into the catalog."""

import json
from pathlib import Path

from recipify import markdown, pipeline, viewer
from recipify.categories import Category
from recipify.classify import classify
from recipify.curation import Curation
from recipify.models import Tier
from recipify.store import Workspace
from recipify.trace import trace

SOUP = """---
course: main            # comments after a value are ignored
dish: soup
diet:
cuisine: Nordic, French
status: draft
---
<!-- a reminder to myself -->
# Root vegetable soup

Serves 4.
A weeknight soup.

## Ingredients
- 500 g celeriac
* 2 onions
- salt

## Method
1. Sweat the onions.
2) Add the celeriac and cover with water.
Blend until smooth.
3.

> Freezes well.
"""

PIE = """# Mushroom pie

## Filling
### Hráefni
- 400 g mushrooms
### Aðferð:
1. Fry the mushrooms.
Not a numbered line, still a step.

## Pastry
- 250 g flour
A loose line after the ingredients.

### Method
Rub in the butter.
"""


def test_front_matter_labels_and_draft():
    w = markdown.parse(SOUP, "root-soup")
    assert w.labels == {"course": ["main"], "dish": ["soup"], "cuisine": ["Nordic", "French"]}
    assert w.draft
    r = w.recipe
    assert (r.title, r.title_in_text) == ("Root vegetable soup", True)
    assert r.intro == ["Serves 4.", "A weeknight soup."]
    [part] = r.sections
    assert (part.name, part.ingredients_label, part.method_label) == ("", "", "")
    assert [i.text for i in part.ingredients] == ["500 g celeriac", "2 onions", "salt"]
    assert part.ingredients[0].amount == 500 and part.ingredients[0].unit == "g"
    assert part.ingredients[2].name == "salt"  # no quantity: kept whole
    assert part.steps == [
        "Sweat the onions.",
        "Add the celeriac and cover with water.",
        "Blend until smooth.",
    ]  # numbers are drawn by the viewer; an empty "3." is a placeholder
    assert part.notes == ["Freezes well."]


def test_components_own_labels_and_no_front_matter():
    w = markdown.parse(PIE, "pie")
    assert (w.labels, w.draft) == ({}, False)
    filling, pastry = w.recipe.sections
    assert (filling.name, filling.ingredients_label, filling.method_label) == (
        "Filling",
        "Hráefni",
        "Aðferð:",
    )
    assert filling.steps == ["Fry the mushrooms.", "Not a numbered line, still a step."]
    assert pastry.notes == ["A loose line after the ingredients."]
    assert (pastry.method_label, pastry.steps) == ("Method", ["Rub in the butter."])


def test_untitled_and_unclosed_front_matter():
    w = markdown.parse("---\ncourse: main\n\n- 1 egg\n", "boiled-egg")
    assert (w.recipe.title, w.recipe.title_in_text, w.labels) == ("boiled-egg", False, {})
    assert w.recipe.intro == ["---", "course: main"]  # not front matter without a closing ---
    assert markdown.parse("", "empty").recipe.sections == []


def test_classified_by_extension(tmp_path: Path):
    (tmp_path / "soup.md").write_text(SOUP, encoding="utf-8")
    (tmp_path / "README.md").write_text("About these recipes", encoding="utf-8")
    assert classify(tmp_path / "soup.md").category == Category.MARKDOWN
    assert classify(tmp_path / "README.md").category == Category.IGNORED


def test_markdown_goes_straight_to_the_catalog(tmp_path: Path):
    sources = tmp_path / "sources"
    (sources / "Soups").mkdir(parents=True)
    (sources / "Soups" / "root-soup.md").write_text(SOUP, encoding="utf-8")
    (sources / "pie.md").write_text(PIE, encoding="utf-8")
    ws = Workspace(sources, tmp_path / "data")
    ws.data.mkdir()
    (ws.data / "curation.json").write_text(
        json.dumps({"titles": {"pie": "Wild mushroom pie"}, "labels": {"pie": {"diet": ["vegan"]}}})
    )
    curation = Curation.model_validate_json((ws.data / "curation.json").read_text())
    inv = pipeline.run_inventory(ws, curation)
    assert pipeline.run_extract(ws, inv).done == 0  # nothing to extract: the file is the text
    catalog = pipeline.build_catalog(ws, inv, curation)
    soup, pie = sorted(catalog.entries, key=lambda e: e.source)
    assert soup.source == "Soups/root-soup.md" and pie.title == "Wild mushroom pie"
    assert {soup.assessment.tier, pie.assessment.tier} == {Tier.READY}
    assert soup.structure == "markdown@v1" and soup.draft and not pie.draft
    assert soup.labels["cuisine"] == ["Nordic", "French"]  # stated labels win
    assert soup.labels["dish"] == ["soup"] and pie.labels["diet"] == ["vegan"]
    assert soup.assessment.reasons == ["written in markdown: the file is the recipe", "draft"]

    line = viewer.source_line(soup)
    assert "From Soups/root-soup.md (markdown)" in line
    assert line.endswith("Written in markdown: the file is the recipe. Draft: still being written.")
    assert viewer.certainty(pie) == "Written in markdown: the file is the recipe."
    assert not viewer.uncertain(soup)
    page = viewer.render(catalog, "Home")
    assert "Root vegetable soup" in page and "Freezes well." in page

    links = trace(ws, inv, pie)
    assert links[-1].ok and "written in markdown" in links[1].detail
