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
        ("Chia seeds 250 g", (250, None, "250", "g", "Chia seeds")),
        ("Almond milk 1L", (1, None, "1", "L", "Almond milk")),
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
    text = """Ostakaka, hafrar og bláber
Ostakrem
500 g rjómaostur
80 g sykur
Aðferð:
Súkkulaðið er brætt. Rjómi, sykur
og garðablóðberg sett saman í
pott.
Geymsluþol:
4 dagar.
Hafracrumble
140 g hafrar
140 g smjör
Aðferð: Allt nema smjörið sett saman.
Bakað við 160°c í 15 mín."""
    r = structure(text, "fallback")
    _check(r, text)
    assert r.title == "Ostakaka, hafrar og bláber"
    first, second = r.sections
    assert first.name == "Ostakrem" and first.method_label == "Aðferð:"
    assert [i.amount for i in first.ingredients] == [500, 80]
    assert first.steps == ["Súkkulaðið er brætt. Rjómi, sykur og garðablóðberg sett saman í pott."]
    assert first.notes == ["Geymsluþol: 4 dagar."]
    assert second.name == "Hafracrumble"
    assert second.steps == ["Allt nema smjörið sett saman.", "Bakað við 160°c í 15 mín."]


def test_bare_ingredients_before_a_method_label():
    text = """Leturhumar og rósakál

Epli og rósakál

Epli

Rósakál

Salt

Aðferð:

Allt blandað saman.

Rósakál

Rósakál

Vatn

Aðferð:

Rósakál er pillað."""
    r = structure(text, "x")
    _check(r, text)
    assert [s.name for s in r.sections] == ["Epli og rósakál", "Rósakál"]
    assert [i.text for i in r.sections[1].ingredients] == ["Rósakál", "Vatn"]


def test_numbered_steps_bullets_and_echoed_title():
    text = """# Crisp

# Crisp

## Kartöflucrisp:

- Skræla kartöflur.
- Baka:
\f
Crisp
- 140°C, vifta 2, í 7 mín
1. Taka út.
2. Strá salti yfir.

Crisp"""
    r = structure(text, "crisp")
    _check(r, text)
    assert r.dropped == ["Crisp", "Crisp", "1", "2"]  # echoes at the top and after a page break
    assert r.sections[0].name == "Kartöflucrisp"
    assert r.sections[0].steps[-3:] == ["Taka út.", "Strá salti yfir.", "Crisp"]
    assert len(r.sections[0].steps) == 6


def test_document_without_a_title_line():
    text = "Muffins:\n\n3 egg.\n\n200 gr sykur.\n\nAðferð :\n\nAllt hrært saman ."
    r = structure(text, "bakstur")
    _check(r, text)
    assert (r.title, r.title_in_text) == ("bakstur", False)
    assert r.sections[0].name == "Muffins"
    assert structure("", "empty") == Recipe(title="empty", title_in_text=False)
    form = structure("Námstaður : Hótel- og veitingaskóli\n2 egg\n1 l mjólk", "Bisque")
    assert (form.title, form.title_in_text) == ("Bisque", False)


def test_intro_method_only_components_and_tables():
    text = """Scallop tartare

Serves 4.

Horseradish snow

| 700 g | celeriac juice |

| 350 g | skyr |

Method

Gelatin is soaked in ice water. Vacuum pack 200g ea bag.

Scallop tartare

Each scallop is cut into 9 dices, seasoned with salt.

Ingredients

2 dl af soðinu"""
    r = structure(text, "x")
    _check(r, text)
    assert r.intro == ["Serves 4."]
    snow, scallop, last = r.sections
    assert snow.ingredients[0].text == "700 g · celeriac juice"
    assert snow.ingredients[0].amount == 700
    assert scallop.name == "Scallop tartare" and scallop.steps
    assert last.ingredients_label == "Ingredients"


def test_numbers_inside_a_method():
    text = """Karamella
200 g sykur
Aðferð:
Sykur og 55 g vatn sett í pott. Hitað þar til
100 ml af vatni bætt við ásamt vanillunni og saltinu og síðan sigtað.
2000 g salt, 2000 g sugar and the zest of 15 lemons is mixed together.
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
    text = """Rauðrófur
Rauðrófuskífur
Rauðrófunum er pakkað inní álpapír
og bakaðar á 180°C.
Vinagrette
100 ml safi
Skerið af botninum á lauknum
og gufusjóðið laukinn.
Salt
Lokið."""
    r = structure(text, "x")
    _check(r, text)
    assert r.sections[0].name == "Rauðrófuskífur"
    assert r.sections[0].steps == ["Rauðrófunum er pakkað inní álpapír og bakaðar á 180°C."]
    vinagrette = r.sections[1]
    assert vinagrette.steps[0] == "Skerið af botninum á lauknum og gufusjóðið laukinn."


def test_short_lines_at_the_end_and_numbers_after_a_label():
    text = (
        "Sósa\nGrunnur\n2 egg\nAðferð:\n"
        "2000 g salt, 2000 g sugar and the zest of 15 lemons mixed.\nHrært\nSalt\nPipar"
    )
    r = structure(text, "x")
    _check(r, text)
    assert r.sections[0].steps[0].startswith("2000 g salt")
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
