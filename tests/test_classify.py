import zipfile
from pathlib import Path

import pytest
from pypdf import PdfWriter

from recipify.categories import Category
from recipify.classify import classify

TEXT = "Whisk the eggs with sugar until pale, then fold in the flour. " * 3


def test_pdfs_by_text_layer(tmp_path: Path, make_pdf):
    assert classify(make_pdf(tmp_path / "text.pdf", [TEXT])).category == Category.READABLE_PDFS
    scan = make_pdf(tmp_path / "scan.pdf", ["p. 1"])
    assert classify(scan).category == Category.IMAGE_BASED_PDFS


def test_pdfs_that_cannot_be_read(tmp_path: Path, make_pdf):
    source = make_pdf(tmp_path / "a.pdf", [TEXT])
    locked = PdfWriter(clone_from=source)
    locked.encrypt("secret")
    locked.write(tmp_path / "locked.pdf")
    opens = PdfWriter(clone_from=source)
    opens.encrypt("", owner_password="owner")  # encrypted, but no password needed to read
    opens.write(tmp_path / "opens.pdf")
    PdfWriter().write(tmp_path / "nopages.pdf")
    (tmp_path / "junk.pdf").write_bytes(b"%PDF-1.4 garbage")
    with zipfile.ZipFile(tmp_path / "zip.pdf", "w") as zf:
        zf.writestr("readme.txt", "not a document")

    reasons = {n: classify(tmp_path / f"{n}.pdf") for n in ("locked", "nopages", "junk", "zip")}
    assert reasons["locked"].reason == "encrypted PDF"
    assert reasons["nopages"].reason == "PDF has no pages"
    assert reasons["junk"].reason.startswith("unreadable PDF")
    assert reasons["zip"].reason == "missing %PDF header"
    assert all(r.category == Category.EMPTY_OR_CORRUPTED for r in reasons.values())
    assert classify(tmp_path / "opens.pdf").category == Category.READABLE_PDFS


def test_broken_docx(tmp_path: Path):
    (tmp_path / "plain.docx").write_text("not a zip")
    with zipfile.ZipFile(tmp_path / "bad.docx", "w") as zf:
        zf.writestr("word/document.xml", "<not xml")
    assert classify(tmp_path / "plain.docx").reason == "not a valid docx (zip) container"
    assert classify(tmp_path / "bad.docx").reason.startswith("unreadable docx")


@pytest.mark.parametrize(
    ("name", "content", "category"),
    [
        ("Thumbs.db", b"x", Category.IGNORED),
        ("link.url", b"x", Category.IGNORED),
        ("zero.docx", b"", Category.EMPTY_OR_CORRUPTED),
        ("photo.png", b"\x89PNG\r\n\x1a\nrest", Category.IMAGE_FILES),
        ("fake.jpg", b"GIF89a", Category.EMPTY_OR_CORRUPTED),
        ("book.epub", b"PK", Category.EPUB_BOOKS),
        ("costs.xls", b"x", Category.SPREADSHEETS),
        ("menu.csv", b"a,b", Category.SPREADSHEETS),
        ("old.doc", b"x", Category.LEGACY_OFFICE),
        ("notes.txt", b"x", Category.OTHER_FORMATS),
        ("README", b"x", Category.OTHER_FORMATS),
    ],
)
def test_category_by_name_and_header(tmp_path: Path, name: str, content: bytes, category):
    (tmp_path / name).write_bytes(content)
    assert classify(tmp_path / name).category == category
