"""Text-level helpers: labels, titles, quality, tidy, spelling, locking, metadata."""

import json
import re
from pathlib import Path

import pytest

from recipify.extractors.office import _cell
from recipify.labels import describe, detect_labels, fix_mojibake, load_curation, refine_title
from recipify.lock import encrypt_page
from recipify.metadata import new_run_id
from recipify.quality import detect_language
from recipify.spelling import load_spelling
from recipify.tidy import tidy


def test_fix_mojibake_leaves_unconvertible_text():
    assert fix_mojibake("S¢sa €5") == "S¢sa €5"  # € is not latin-1, so this was never cp850


def test_untitled_without_a_usable_line_keeps_its_name():
    assert refine_title("Untitled", "# Untitled\n\n12\n\nab\n", "u", {}) == "Untitled"


def test_seafood_gluten_free_and_cuisine_labels():
    text = "Lax 400 g, rækjur, laxinn steiktur, tortilla, salsa, guacamole, glutenlaus. " * 4
    labels = detect_labels("Fish tacos", "x.docx", text)
    assert "fish" in labels["ingredients"]
    assert labels["diet"][:2] == ["seafood", "gluten-free"]
    assert labels["cuisine"] == ["Mexican & Latin"]


def test_dairy_only_recipe_is_labelled_dairy():
    labels = detect_labels("Rjómi", "x.docx", "Þeytið rjóma. " * 20)
    assert labels["ingredients"] == ["dairy"] and labels["diet"] == ["vegetarian"]


def test_curation_overrides(tmp_path: Path):
    assert load_curation(tmp_path / "missing.json") == {"titles": {}, "labels": {}, "kind": {}}
    path = tmp_path / "curation.json"
    path.write_text(
        json.dumps({"titles": {"a": "Soup"}, "labels": {"a": {"course": ["starter"]}}}),
        encoding="utf-8",
    )
    info = describe("dir/a.docx", "# a\n\ntext", load_curation(path))
    assert info["title"] == "Soup" and info["labels"]["course"] == ["starter"]


def test_mixed_language():
    assert detect_language("og the með and í of salt sugar smjör flour pottinn bake") == "mixed"


def test_tidy_drops_empty_and_repeated_headings():
    assert tidy("# Soup\n\n# **\n\n## Stock\n\n## Stock\n\nBoil.\n", "Soup") == (
        "# Soup\n\n## Stock\n\nBoil.\n"
    )


def test_load_spelling(tmp_path: Path):
    assert load_spelling(tmp_path / "missing.json") == {}
    (tmp_path / "s.json").write_text('{"smjór": "smjör"}', encoding="utf-8")
    assert load_spelling(tmp_path / "s.json") == {"smjór": "smjör"}


def test_lock_needs_a_passphrase():
    with pytest.raises(ValueError, match="empty passphrase"):
        encrypt_page("<p>x</p>", "")


def test_run_ids_sort_by_time():
    assert re.fullmatch(r"\d{8}T\d{6}Z", new_run_id())


def test_spreadsheet_cell_values():
    assert [_cell(v) for v in (None, 2.0, 0.123456, "a|b")] == ["", "2", "0.1235", "a\\|b"]
