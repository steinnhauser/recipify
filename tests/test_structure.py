import pytest

from recipify.assess import fidelity
from recipify.models import Recipe
from recipify.structure.quantities import amount, parse_ingredient
from recipify.structure.rules import structure
from recipify.text import fix_mojibake, fold, slugify, tokens


def test_text_helpers():
    assert fold("Þorskur á Ðiski") == "thorskur a diski"
    assert slugify("Þorskur & hörpuskel (tasting)") == "thorskur-horpuskel-tasting"
    assert slugify("!!!") == "untitled"
    assert tokens("1,5 kg Smjör.") == ["1", "5", "kg", "smjör"]
    assert fix_mojibake("S¢sa") == "Sósa"
    assert fix_mojibake("Sósa") == "Sósa"
    assert fix_mojibake("¢Ā") == "¢Ā"  # not latin-1: left alone


@pytest.mark.parametrize(
    ("line", "expected"),
    [
        ("125gr smjör", (125, None, "125", "gr", "smjör")),
        ("1,5 l mysa", (1.5, None, "1,5", "l", "mysa")),
        ("1 ½ tsk timían", (1.5, None, "1 ½", "tsk", "timían")),
        ("¼ tsk salt", (0.25, None, "¼", "tsk", "salt")),
        ("3/4 cup milk", (0.75, None, "3/4", "cup", "milk")),
        ("2-3 msk Dijon", (2, 3, "2-3", "msk", "Dijon")),
        ("ca. 4stk Sítrónusafi", (4, None, "ca. 4", "stk", "Sítrónusafi")),
        ("2 egg", (2, None, "2", "", "egg")),
        ("Rolled oats 250 g", (250, None, "250", "g", "Rolled oats")),
        ("Oat milk 1L", (1, None, "1", "L", "Oat milk")),
        ("100% - 1000 g epli", (100, None, "100", "%", "- 1000 g epli")),
    ],
)
def test_parse_ingredient(line: str, expected: tuple):
    found = parse_ingredient(line)
    assert found is not None
    assert (found.amount, found.amount_max, found.quantity, found.unit, found.name) == expected
    assert found.text == line


@pytest.mark.parametrize(
    "line",
    ["1. Boil", "140°C, vifta 2", "4.-10. Júní", "4 x 2,5", "Salt", "Lamb with 2 sauces", "12"],
)
def test_not_an_ingredient(line: str):
    assert parse_ingredient(line) is None


def test_amount():
    assert amount("½") == 0.5
    assert amount("2") == 2


def _check(recipe: Recipe, text: str) -> None:
    assert fidelity(text, recipe) == (1.0, 1.0)


def test_components_labels_and_notes():
    text = """Skyrterta með rabarbara
Skyrkrem
400 g skyr
60 g sykur
Aðferð:
Rjóminn er þeyttur. Skyr, sykur
og vanilla hrært saman í
skál.
Geymsluþol:
3 dagar.
Hafrabotn
120 g hafrar
90 g smjör
Aðferð: Smjörið brætt og hafrar settir út í.
Ofnbakað í 12 mín."""
    r = structure(text, "fallback")
    _check(r, text)
    assert r.title == "Skyrterta með rabarbara"
    first, second = r.sections
    assert first.name == "Skyrkrem" and first.method_label == "Aðferð:"
    assert [i.amount for i in first.ingredients] == [400, 60]
    assert first.steps == ["Rjóminn er þeyttur. Skyr, sykur og vanilla hrært saman í skál."]
    assert first.notes == ["Geymsluþol: 3 dagar."]
    assert second.name == "Hafrabotn"
    assert second.steps == ["Smjörið brætt og hafrar settir út í.", "Ofnbakað í 12 mín."]


def test_bare_ingredients_before_a_method_label():
    text = """Bleikja og fennel

Fennelsalat

Fennel

Dill

Salt

Aðferð:

Allt skorið fínt.

Fennel

Fennel

Olía

Aðferð:

Fennel er grillað."""
    r = structure(text, "x")
    _check(r, text)
    assert [s.name for s in r.sections] == ["Fennelsalat", "Fennel"]
    assert [i.text for i in r.sections[1].ingredients] == ["Fennel", "Olía"]


def test_numbered_steps_bullets_and_echoed_title():
    text = """# Kex

# Kex

## Hafrakex:

- Hræra deigið.
- Baka:
\f
Kex
- 150°C, vifta 2, í 9 mín
1. Kæla.
2. Geyma í boxi.

Kex"""
    r = structure(text, "kex")
    _check(r, text)
    assert r.dropped == ["Kex", "Kex", "1", "2"]  # echoes at the top and after a page break
    assert r.sections[0].name == "Hafrakex"
    assert r.sections[0].steps[-3:] == ["Kæla.", "Geyma í boxi.", "Kex"]
    assert len(r.sections[0].steps) == 6


def test_document_without_a_title_line():
    text = "Skonsur:\n\n2 egg.\n\n300 gr hveiti.\n\nAðferð :\n\nAllt hrært saman ."
    r = structure(text, "morgunbakstur")
    _check(r, text)
    assert (r.title, r.title_in_text) == ("morgunbakstur", False)
    assert r.sections[0].name == "Skonsur"
    assert structure("", "empty") == Recipe(title="empty", title_in_text=False)
    form = structure("Staður : Eldhúsið\n2 egg\n1 l mjólk", "Súpa")
    assert (form.title, form.title_in_text) == ("Súpa", False)


def test_intro_method_only_components_and_tables():
    text = """Beetroot

Serves 4.

Horseradish cream

| 300 g | sour cream |

| 40 g | horseradish |

Method

Everything is mixed and chilled. Keeps 2 days.

Beetroot

The beetroots are baked whole at 180°C for an hour.

Ingredients

2 dl af soðinu"""
    r = structure(text, "x")
    _check(r, text)
    assert r.intro == ["Serves 4."]
    cream, beetroot, last = r.sections
    assert cream.ingredients[0].text == "300 g · sour cream"
    assert cream.ingredients[0].amount == 300
    assert beetroot.name == "Beetroot" and beetroot.steps  # named like the title, and kept
    assert last.ingredients_label == "Ingredients"


def test_numbers_inside_a_method():
    text = """Karamella
200 g sykur
Aðferð:
Sykurinn bræddur í potti. Hitað þar til
50 ml af rjóma er hellt út í og hrært þar til sósan er orðin slétt.
500 g flour, 250 g butter and a pinch of salt are rubbed together.
2 dl rjómi
1 l mjólk
Smá vatn
3 g agar"""
    r = structure(text, "x")
    _check(r, text)
    first, second = r.sections
    assert len(first.steps) == 2  # the wrapped line and the long sentence stay steps
    assert [i.text for i in second.ingredients] == [
        "2 dl rjómi",
        "1 l mjólk",
        "Smá vatn",
        "3 g agar",
    ]


def test_prose_in_lists_and_names_followed_by_prose():
    text = """Gulrætur
Gulrótarskífur
Gulræturnar eru skornar í skífur
og bakaðar á 180°C.
Vinagrette
100 ml safi
Skerið laukinn í tvennt
og steikið hann.
Salt
Lokið."""
    r = structure(text, "x")
    _check(r, text)
    assert r.sections[0].name == "Gulrótarskífur"
    assert r.sections[0].steps == ["Gulræturnar eru skornar í skífur og bakaðar á 180°C."]
    vinagrette = r.sections[1]
    assert vinagrette.steps[0] == "Skerið laukinn í tvennt og steikið hann."


def test_short_lines_at_the_end_and_numbers_after_a_label():
    text = (
        "Sósa\nGrunnur\n2 egg\nAðferð:\n"
        "500 g flour, 250 g butter and a pinch of salt rubbed together.\nHrært\nSalt\nPipar"
    )
    r = structure(text, "x")
    _check(r, text)
    assert r.sections[0].steps[0].startswith("500 g flour")
    assert r.sections[0].steps[-3:] == ["Hrært", "Salt", "Pipar"]


def test_repeated_labels_start_new_components():
    text = "Sósa\nHráefni\n2 egg\nHráefni\n1 l mjólk\nAðferð:\nAðferð:\nHrært."
    r = structure(text, "x")
    _check(r, text)
    assert len(r.sections) == 3
    assert r.sections[2].method_label == "Aðferð:" and r.sections[2].steps == ["Hrært."]


def test_title_too_long_or_a_quantity():
    long = "Þetta er mjög löng lína sem er greinilega ekki titill heldur texti " * 2
    assert structure(long, "fallback").title == "fallback"
    assert structure("2 egg\n1 l mjólk", "Pönnukökur").title == "Pönnukökur"


def test_intro_lines_and_two_names_in_a_row():
    text = "Réttur\nUndirtitill\nSósa\n2 egg\nAðferð:\nHrært."
    r = structure(text, "x")
    _check(r, text)
    assert r.intro == ["Undirtitill"]
    assert r.sections[0].name == "Sósa"
    text = "Réttur\n# Sósa\n# Grunnur\n2 egg"
    r = structure(text, "x")
    assert [s.name for s in r.sections] == ["Sósa", "Grunnur"]


def test_instructions_written_between_ingredients():
    text = """Eplakaka
Botn
150 g hafrar
300 ml mjólk
Látið standa í skál
500 g sykur
250 g smjör
Hrærið smjörið og sykurinn saman
900 g hveiti
10 g salt
Bakið við 170°C í 35 mín
Steikt smælki"""
    r = structure(text, "x")
    _check(r, text)
    groups = [([i.text for i in s.ingredients], s.steps) for s in r.sections]
    assert groups == [
        (["150 g hafrar", "300 ml mjólk"], ["Látið standa í skál"]),
        (["500 g sykur", "250 g smjör"], ["Hrærið smjörið og sykurinn saman"]),
        (["900 g hveiti", "10 g salt"], ["Bakið við 170°C í 35 mín", "Steikt smælki"]),
    ]
    assert r.sections[0].name == "Botn"


def test_costing_tables_are_set_aside():
    text = """Lambasteik
2 kg lambalæri
20 g salt
Aðferð:
Steikt við 180°C.
hráefni | Amount | Unit | Purchase Price
0.1 | kg | 2000
Total cost | 1500
\f
Annað blað
1 l soð"""
    r = structure(text, "x")
    _check(r, text)
    assert r.dropped == [
        "hráefni · Amount · Unit · Purchase Price",
        "0.1 · kg · 2000",
        "Total cost · 1500",
    ]
    assert r.sections[-1].ingredients[-1].text == "1 l soð"  # a new page ends the table


def test_scaling_tables_are_read_by_column():
    text = """Rabarbarasulta

| | X1 | X4 | x10 |
| --- | --- | --- | --- |
| | g | g | g |
| Rabarbari | 500 | 2000 | 5000 |
| Sykur | 250 | 1000 | 2500 |
| Pektín | 6 stk | 24 stk | 60 stk |
| | | 0 | 0 |
| Kælt yfir nótt | | 0 | 0 |
| Samtals | 756 | 3024 | 7560 |
| Hrært | | 3 | 4 |
Soðið í 10 mín.

| | | | ½ |
| Smjör | 100g | 15% | 50g |"""
    r = structure(text, "x")
    _check(r, text)
    first, last = r.sections
    assert [(i.quantity, i.unit, i.name) for i in first.ingredients] == [
        ("500", "g", "Rabarbari"),
        ("250", "g", "Sykur"),
        ("6", "stk", "Pektín"),
    ]
    assert first.ingredients[0].text == "Rabarbari · 500"
    assert first.notes == ["Kælt yfir nótt", "Samtals · 756"]
    assert "Hrært · 3 · 4" in r.lines()  # a row that does not fit is read as a plain line
    assert "X1 · X4 · x10" in r.dropped and "2000" in r.dropped and "g · g · g" in r.dropped
    # without an X1 column, the recipe's own amounts are the first unlabelled column
    assert [(i.text, i.name) for i in last.ingredients] == [("Smjör · 100g · 15%", "Smjör · 15%")]
    assert "50g" in r.dropped
