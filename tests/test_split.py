import pytest

from recipify.split import check, pages, plan, split

CAKE = """Gulrótarkaka
300 g hveiti
250 g sykur
3 egg
Aðferð:
Allt hrært saman og bakað við 175°C í 40 mín. Kælt áður en kremið fer á."""
PIE = """Hjónabandssæla
200 g hafrar
200 g hveiti
150 g púðursykur
Aðferð:
Allt hnoðað saman, sultan smurð yfir og bakað við 180°C í 30 mín. Borið fram volgt."""


def doc(*page_texts: str) -> str:
    return "\n\f\n".join(page_texts)


def test_pages():
    assert pages("a\n\f\nb\n \f\nc") == ["a", "b", "c"]
    assert pages("only") == ["only"]


def test_collection_is_split_by_page():
    decision, reasons, units = plan(doc(CAKE, PIE), "Kökur - uppskriftir")
    assert decision == "split"
    assert reasons == ["2 recipes, each starting on a new page with its own title"]
    assert [(u.index, u.title, u.pages) for u in units] == [
        (1, "Gulrótarkaka", [1]),
        (2, "Hjónabandssæla", [2]),
    ]
    assert units[0].text == CAKE and units[1].text == PIE


def test_untitled_pages_continue_the_recipe_before():
    more = "og síðan smurt með kremi.\n200 g rjómaostur"
    decision, _, units = plan(doc(CAKE, more, PIE), "uppskriftir")
    assert decision == "split"
    assert [u.pages for u in units] == [[1, 2], [3]]
    assert units[0].text == doc(CAKE, more)


@pytest.mark.parametrize(
    ("text", "name", "reason"),
    [
        (CAKE, "Kökur", "one page"),
        (doc(CAKE, PIE), "Lamb with goat cheese", "not named as a collection of recipes"),
        (doc("200 g hveiti\n100 g sykur", PIE), "uppskriftir", "the first page has no title"),
        (doc(CAKE, "og bakað lengur.\nKælt."), "uppskriftir", "the pages continue one recipe"),
        (doc(CAKE, "Krem\n200 g rjómi\nÞeytt."), "uppskriftir", "not every part is a complete"),
        (doc(CAKE, CAKE.replace("Gulrótarkaka", "Carrot cake")), "uppskriftir", "two parts"),
        (doc("Sósur\n" + CAKE, "Sósur\n" + PIE), "uppskriftir", "every page repeats a header"),
    ],
)
def test_kept_whole(text: str, name: str, reason: str):
    decision, reasons, units = plan(text, name)
    assert decision == "whole" and reasons[0].startswith(reason)
    assert len(units) == 1 and units[0].text == text
    assert units[0].pages == list(range(1, len(pages(text)) + 1))


def test_running_header_that_names_the_recipes():
    text = doc("Gulrótarkaka & Hjónabandssæla\n" + CAKE, "Gulrótarkaka & Hjónabandssæla\n" + PIE)
    decision, reasons, units = plan(text, "uppskriftir")
    assert decision == "split" and "shared header" in reasons[0]
    assert units[0].dropped == units[1].dropped == ["Gulrótarkaka & Hjónabandssæla"]
    assert units[0].title == "Gulrótarkaka"


def test_collection_heading_above_the_first_recipe():
    by_name = plan(doc("Jólauppskriftir hússins\n" + CAKE, PIE), "x")
    assert by_name[0] == "split" and by_name[2][0].dropped == ["Jólauppskriftir hússins"]
    assert by_name[2][0].title == "Gulrótarkaka"
    assert "names the collection" in by_name[1][0]
    third = PIE.replace("Hjónabandssæla", "Kryddkaka").replace("200 g", "250 g")
    by_layout = plan(doc("Brauð\n" + CAKE, PIE, third), "Brauð - uppskriftir")
    assert by_layout[2][0].dropped == ["Brauð"] and by_layout[2][0].title == "Gulrótarkaka"


def test_split_records_the_decision_and_checks_coverage():
    result = split("ab" * 32, "poppler@v2", doc(CAKE, PIE), "uppskriftir")
    assert (result.decision, result.label, result.extraction) == ("split", "pages@v1", "poppler@v2")
    kept = split("ab" * 32, "poppler@v2", doc(CAKE, PIE), "uppskriftir", keep_whole=True)
    assert kept.decision == "whole" and kept.by_hand
    assert kept.reasons == ["kept whole by hand in curation.json"]
    result.units[0].text = "Gulrótarkaka"  # a unit that lost words
    with pytest.raises(ValueError, match="lost or repeated"):
        check(doc(CAKE, PIE), result)
