import json
import os
from pathlib import Path

import pytest

from recipify import pipeline
from recipify.assess import assess, detect_language, text_quality
from recipify.categories import Category
from recipify.curation import Curation
from recipify.extract import Engine
from recipify.inventory import scan, triage
from recipify.labels import detect_labels, refine_title
from recipify.models import (
    Extraction,
    Ingredient,
    Kind,
    Recipe,
    Section,
    SourceFile,
    Structured,
    Tier,
)
from recipify.report import reason_group
from recipify.store import Workspace, write_json


def _source(**kw) -> SourceFile:
    defaults = dict(
        path="a.pdf",
        sha256="ab" * 32,
        size=1,
        mtime=0.0,
        category=Category.READABLE_PDFS,
        reason="",
    )
    return SourceFile(**(defaults | kw))


def test_inventory_triage_and_duplicates(ws: Workspace):
    inv = scan(ws.sources)
    files = inv.files
    assert files["copy/Tartdeig (1).pdf"].duplicate_of == "Bakarí/Tartdeig.pdf"
    assert files["Handbook.pdf"].kind == Kind.BOOK and files["Handbook.pdf"].pages == 10
    assert files["photo.jpg"].category == Category.IMAGE_FILES
    assert len(inv.canonical()) == 4

    seen: list[str] = []
    again = scan(ws.sources, inv, Curation(kind={"Skyrkaka": Kind.REFERENCE}), seen.append)
    assert again.files["Eftirréttir/Skyrkaka.docx"].kind == Kind.REFERENCE
    assert len(seen) == 5
    path = ws.sources / "photo.jpg"
    os.utime(path, (1, 1))  # changed files are read again
    assert scan(ws.sources, inv).files["photo.jpg"].mtime == 1


def test_triage():
    assert triage("Myndir/Lava/Ostakaka.jpg", Category.IMAGE_FILES, None, Curation()) == Kind.PHOTO
    assert triage("Advanced Pastry 3.jpeg", Category.IMAGE_FILES, None, Curation()) == Kind.RECIPE
    assert triage("Missi Lava.xlsx", Category.SPREADSHEETS, None, Curation()) == Kind.REFERENCE
    assert triage("Hópaseðill.pdf", Category.READABLE_PDFS, 1, Curation()) == Kind.REFERENCE
    assert triage("Bók.epub", Category.EPUB_BOOKS, None, Curation()) == Kind.BOOK
    assert triage("Kaka.pdf", Category.READABLE_PDFS, 2, Curation()) == Kind.RECIPE


def test_stages_cache_and_resume(ws: Workspace):
    inv = pipeline.run_inventory(ws, Curation())
    results: list[tuple[str, str]] = []
    first = pipeline.run_extract(ws, inv, on_result=lambda p, s: results.append((p, s)))
    assert (first.done, first.failed) == (2, 0)  # the PDF and the docx; copy, book, photo skipped
    assert sorted(results) == [("Bakarí/Tartdeig.pdf", "ok"), ("Eftirréttir/Skyrkaka.docx", "ok")]
    assert pipeline.run_extract(ws, inv).skipped == 2
    assert pipeline.run_extract(ws, inv, force=True, limit=1).done == 1

    st = pipeline.run_structure(ws, inv, on_result=lambda p, s: None)
    assert st.done == 2
    assert pipeline.run_structure(ws, inv).skipped == 2
    assert pipeline.run_structure(ws, inv, force=True, limit=1).done == 1

    catalog = pipeline.build_catalog(ws, inv, Curation(titles={"Skyrkaka": "Skyrkaka góða"}))
    by_source = {e.source: e for e in catalog.entries}
    tart = by_source["Bakarí/Tartdeig.pdf"]
    assert tart.assessment.tier == Tier.READY, tart.assessment.reasons
    assert tart.assessment.fidelity == tart.assessment.precision == 1.0
    assert tart.duplicates == ["copy/Tartdeig (1).pdf"]
    assert tart.labels["course"] == ["bread & pastry"]
    assert tart.extraction == "poppler@v2" and tart.structure == "rules@v1"
    assert by_source["Eftirréttir/Skyrkaka.docx"].title == "Skyrkaka góða"
    assert by_source["Handbook.pdf"].assessment.reasons == [
        "book (10 pages): not split into recipes yet"
    ]
    assert by_source["photo.jpg"].assessment.reasons == ["needs a transcription (no text layer)"]
    report = ws.report_path.read_text()
    assert "**1 recipes ready**" in report and "## Review list" in report
    assert "Changes since the last run" not in report  # the first run has nothing to compare
    pipeline.register(ws, inv.files["photo.jpg"], "Rauðrófur\n4 rauðrófur", "vision")
    pipeline.run_structure(ws, inv)
    pipeline.build_catalog(ws, inv, Curation())
    assert "- `photo.jpg`: excluded -> review" in ws.report_path.read_text()
    assert len(list((ws.data / "history").glob("*.json"))) >= 1
    log = [json.loads(line) for line in (ws.data / "runs.jsonl").read_text().splitlines()]
    assert [r["stage"] for r in log][:2] == ["inventory", "extract"]


def test_failures_are_reported_not_fatal(ws: Workspace, monkeypatch: pytest.MonkeyPatch):
    inv = pipeline.run_inventory(ws, Curation())

    def broken(path: Path):
        raise ValueError("cannot read")

    monkeypatch.setitem(pipeline.LOCAL, Category.DOCX_FILES, Engine("broken", 1, broken))
    monkeypatch.setitem(
        pipeline.LOCAL, Category.READABLE_PDFS, Engine("empty", 1, lambda p: (" ", {}))
    )
    result = pipeline.run_extract(ws, inv)
    assert result.failed == 2
    assert sorted(e[1] for e in result.errors) == [
        "ValueError: cannot read",
        "ValueError: no text found",
    ]


def test_transcriptions_are_never_overwritten(ws: Workspace):
    inv = pipeline.run_inventory(ws, Curation())
    photo = inv.files["photo.jpg"]
    text = "Rauðrófur\n4 rauðrófur\n200 g skyr\nAðferð:\nBakað."
    first = pipeline.register(ws, photo, text, "vision", 0.9, "by hand")
    second = pipeline.register(ws, photo, text + "\nSalt.", "vision")
    assert (first.name, second.name) == ("vision@v1.json", "vision@v2.json")
    assert pipeline.best_extraction(ws, photo).version == 2
    assert pipeline.run_extract(ws, inv, force=True).done == 2  # the photo has no local engine
    pipeline.run_structure(ws, inv)
    catalog = pipeline.build_catalog(ws, inv, Curation())
    photo_entry = next(e for e in catalog.entries if e.source == "photo.jpg")
    assert photo_entry.assessment.tier == Tier.REVIEW
    assert "read from images" in photo_entry.assessment.reasons[0]


def test_structure_failures(ws: Workspace, monkeypatch: pytest.MonkeyPatch):
    inv = pipeline.run_inventory(ws, Curation())
    pipeline.run_extract(ws, inv)

    def broken(text: str, title: str):
        raise RuntimeError("parser bug")

    monkeypatch.setattr(pipeline.rules, "structure", broken)
    result = pipeline.run_structure(ws, inv)
    assert result.failed == 2 and "parser bug" in result.errors[0][1]
    catalog = pipeline.build_catalog(ws, inv, Curation())
    tart = next(e for e in catalog.entries if e.source == "Bakarí/Tartdeig.pdf")
    assert tart.assessment.reasons == ["not structured yet"]


def test_twins_titles_and_curated_tiers(tmp_path: Path, make_pdf, make_docx):
    sources = tmp_path / "src"
    steps = (
        "Laxinn er snyrtur og beinhreinsaður.\nSaltinu og sykrinum blandað saman.\n"
        "Stráð yfir laxinn og hann grafinn\ní kæli í tvo sólarhringa áður en hann er skorinn."
    )
    body = ["Graflax", "2 kg lax\n100 g salt\nAðferð:\n" + steps]
    make_docx(sources / "Graflax.docx", *body)
    make_pdf(sources / "Graflax.pdf", ["\n".join(body)])
    make_pdf(
        sources / "Spa" / "Graflax.pdf",
        ["Graflax\n1 kg lax\n50 g sykur\nAðferð:\nGrafið.\n" + steps],
    )
    make_pdf(
        sources / "Lava" / "Graflax.pdf",
        ["Graflax\n3 kg lax\n50 g dill\nAðferð:\nGrafið vel.\n" + steps],
    )
    make_pdf(
        sources / "Graflax (hópar).pdf",
        ["Graflax\n9 kg lax\n9 g salt\nAðferð:\nFyrir hópa.\n" + steps],
    )
    make_pdf(sources / "Hidden.pdf", ["Hidden\n1 kg lax\n9 g salt\nAðferð:\nHidden.\n" + steps])
    ws = Workspace(sources, tmp_path / "data")
    inv = pipeline.run_inventory(ws, Curation())
    pipeline.run_extract(ws, inv)
    pipeline.run_structure(ws, inv)
    curation = Curation(tier={"Hidden": Tier.REVIEW}, titles={"Graflax (hópar)": "Graflax"})
    catalog = pipeline.build_catalog(ws, inv, curation)
    ready = {e.source: e.title for e in catalog.by_tier(Tier.READY)}
    assert ready == {
        "Graflax.docx": "Graflax (top folder)",  # the curated "Graflax" keeps its title
        "Spa/Graflax.pdf": "Graflax (Spa)",
        "Lava/Graflax.pdf": "Graflax (Lava)",
        "Graflax (hópar).pdf": "Graflax",
    }
    twin = next(e for e in catalog.entries if e.source == "Graflax.pdf")
    assert twin.assessment.reasons == ["same recipe as Graflax.docx"]
    hidden = next(e for e in catalog.entries if e.source == "Hidden.pdf")
    assert hidden.assessment.tier == Tier.REVIEW
    assert hidden.assessment.reasons == ["tier set by hand in curation.json"]


def test_assessment_reasons():
    ingredients = [Ingredient(text=f"{n} g salt", amount=n) for n in (1, 2)]
    recipe = Recipe(
        title="Sósa", sections=[Section(ingredients=ingredients, steps=["Hrært saman í potti."])]
    )
    text = "Sósa\n1 g salt\n2 g salt\nHrært saman í potti."
    structured = Structured(sha256="x", engine="rules", version=1, extraction="e", recipe=recipe)
    extraction = Extraction(
        sha256="x", engine="e", version=1, text=text, checks={"order_agreement": 0.5}
    )
    a = assess(_source(), extraction, structured)
    assert a.tier == Tier.REVIEW
    assert a.reasons == [
        "reading order uncertain (50.0% of lines agree)",
        "very little text (11 words)",
    ]

    extraction.text += " invented"
    extraction.checks = {}
    assert "text differs from the source" in assess(_source(), extraction, structured).reasons[0]

    unmeasured = recipe.model_copy(deep=True)
    unmeasured.sections[0].ingredients = [Ingredient(text="salt"), Ingredient(text="pipar")]
    unmeasured.intro = ["Long intro words " * 30]
    s2 = structured.model_copy(update={"recipe": unmeasured})
    reasons = assess(_source(category=Category.SPREADSHEETS), extraction, s2).reasons
    assert any("plating guide" in r for r in reasons)
    assert any("unstructured" in r for r in reasons)
    assert reasons[0].startswith("spreadsheet")

    empty = structured.model_copy(update={"recipe": Recipe(title="x")})
    reasons = assess(_source(category=Category.IMAGE_FILES), extraction, empty).reasons
    assert reasons[:1] == ["read from images: cannot be checked against a text layer"]
    assert "no ingredient list found" in reasons and "no method found" in reasons

    huge = Extraction(sha256="x", engine="e", version=1, text="orð " * 4000)
    big = structured.model_copy(update={"recipe": Recipe(title="x", intro=["orð " * 4000])})
    assert assess(_source(), huge, big).tier == Tier.EXCLUDED
    school = Extraction(sha256="x", engine="e", version=1, text="Nemandi: Jón\n2 egg")
    assert assess(_source(), school, structured).reasons == ["course material: a school assignment"]


@pytest.mark.parametrize(
    ("file", "reason"),
    [
        (dict(duplicate_of="b.pdf"), "duplicate of b.pdf"),
        (dict(kind=Kind.BOOK), "book: not split into recipes yet"),
        (dict(kind=Kind.REFERENCE), "reference material, not a recipe"),
        (dict(kind=Kind.PHOTO), "photo of a dish, not a recipe"),
        (dict(category=Category.IGNORED, reason="lock file"), "ignored: lock file"),
        (dict(category=Category.DOCX_FILES), "not extracted yet"),
    ],
)
def test_exclusions(file: dict, reason: str):
    assert assess(_source(**file), None, None).reasons == [reason]


def test_not_structured_yet():
    extraction = Extraction(sha256="x", engine="e", version=1, text="t")
    assert assess(_source(), extraction, None).reasons == ["not structured yet"]


def test_language_and_text_quality():
    assert detect_language("Smjör og sykur hrært saman með eggjum í skál") == "is"
    assert detect_language("Mix the butter and sugar with the eggs in a bowl") == "en"
    assert detect_language("butter og sykur and salt með the") == "mixed"
    assert detect_language("xyz qwe rty uio pas") == "unknown"
    assert detect_language("too short") == "unknown"
    assert text_quality("ok") == (0.1, ["almost_no_text"])
    assert text_quality("Smjör og sykur hrært saman með eggjum")[0] == 1.0
    score, flags = text_quality(
        "S m j ö r o g s y k u r h r æ r t " + "Ã© " * 3 + "xkcdwq rtyplkjh"
    )
    assert score < 0.9 and {"broken spacing", "mojibake", "non-words"} <= set(flags)
    assert text_quality("NATO RSVP HTML og smjör")[0] == 1.0


def test_labels_and_titles():
    recipe = Recipe(
        title="Lambaskankar",
        intro=["Ribeye steik 300 gr. Borið fram með sósu og mörgu fleira góðgæti " * 5],
        sections=[Section(name="Sósa", ingredients=[Ingredient(text="2 dl kjúklingabaunir")])],
    )
    labels = detect_labels("Lambaskankar", "Lava/Aðalréttir/x.pdf", recipe)
    assert labels["course"] == ["main"]
    assert "vegetarian" not in labels["diet"] and "meat" in labels["diet"]
    assert "chicken" not in labels["ingredients"] and "legumes" in labels["ingredients"]
    vegan = Recipe(title="Salat", intro=["Fallegt salat með gúrku og tómötum. " * 10])
    assert detect_labels("Glútenlaust salat", "x", vegan)["diet"] == [
        "vegetarian",
        "vegan",
        "gluten-free",
    ]
    cake = Recipe(
        title="Kaka",
        sections=[Section(ingredients=[Ingredient(text="200 g smjör")])],
        intro=["Kaka bökuð " * 30],
    )
    assert detect_labels("Súkkulaðikaka gluten free", "Eftirréttir/x", cake)["diet"] == [
        "vegetarian",
        "gluten-free",
        "sweet",
    ]
    italian = Recipe(title="x", intro=["risotto parmesan pesto"])
    assert detect_labels("Risotto", "", italian)["cuisine"] == ["Italian"]
    salmon = Recipe(title="x", intro=["lax " * 100])
    assert "seafood" in detect_labels("x", "", salmon)["diet"]

    assert refine_title("S¢sa_1_5 (2)", recipe, "x", {}) == "Sósa 1.5"
    assert refine_title("anything", recipe, "stem", {"stem": "Curated"}) == "Curated"
    assert refine_title("Untitled", recipe, "x", {}) == "Sósa"
    assert refine_title("PICKLED HERRING", recipe, "x", {}) == "Pickled herring"
    assert refine_title("‚bbq sósa", recipe, "x", {}) == "Bbq sósa"


def test_report_reason_groups():
    assert (
        reason_group("reading order uncertain (97.0% of lines agree)") == "reading order uncertain"
    )
    assert reason_group("duplicate of x.pdf") == "identical copy of another file"
    assert reason_group("book (10 pages): not split into recipes yet") == "book"


def test_store_helpers(tmp_path: Path):
    ws = Workspace(tmp_path / "s", tmp_path / "d")
    assert ws.load_inventory().files == {}
    with pytest.raises(FileNotFoundError, match="recipify catalog"):
        ws.load_catalog()
    write_json(tmp_path / "x.json", {"a": "þ"})
    assert json.loads((tmp_path / "x.json").read_text()) == {"a": "þ"}
    with pytest.raises(FileNotFoundError):
        pipeline.run_inventory(ws, Curation())
    assert Curation.load(tmp_path / "missing.json") == Curation()
    (tmp_path / "c.json").write_text('{"kind": {"Missi": "reference"}}', encoding="utf-8")
    assert Curation.load(tmp_path / "c.json").kind == {"Missi": Kind.REFERENCE}
