from collections.abc import Callable
from pathlib import Path

import pytest
from docx import Document

from recipify import pipeline
from recipify.metadata import Metadata


def _make_docx(path: Path, text: str) -> Path:
    doc = Document()
    if text:
        doc.add_paragraph(text)
    doc.save(str(path))
    return path


def _make_pdf(path: Path, pages: list[str]) -> Path:
    """A minimal PDF with one line of Helvetica text per page (no PDF library needed)."""
    n = len(pages)
    kids = " ".join(f"{4 + 2 * i} 0 R" for i in range(n))
    objects = [
        "<< /Type /Catalog /Pages 2 0 R >>",
        f"<< /Type /Pages /Kids [{kids}] /Count {n} >>",
        "<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    ]
    for i, text in enumerate(pages):
        stream = f"BT /F1 12 Tf 72 720 Td ({text}) Tj ET"
        objects.append(
            "<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
            f"/Resources << /Font << /F1 3 0 R >> >> /Contents {5 + 2 * i} 0 R >>"
        )
        objects.append(f"<< /Length {len(stream)} >>\nstream\n{stream}\nendstream")
    out, offsets = b"%PDF-1.4\n", []
    for i, body in enumerate(objects, 1):
        offsets.append(len(out))
        out += f"{i} 0 obj\n{body}\nendobj\n".encode("latin-1")
    xref = len(out)
    out += f"xref\n0 {len(objects) + 1}\n0000000000 65535 f \n".encode()
    out += "".join(f"{o:010d} 00000 n \n" for o in offsets).encode()
    out += (
        f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode()
    )
    path.write_bytes(out)
    return path


@pytest.fixture
def make_docx() -> Callable[[Path, str], Path]:
    return _make_docx


@pytest.fixture
def make_pdf() -> Callable[[Path, list[str]], Path]:
    return _make_pdf


@pytest.fixture
def project(tmp_path: Path) -> tuple[Path, Path]:
    """Empty recipes/ and outputs/ directories."""
    recipes, outputs = tmp_path / "recipes", tmp_path / "outputs"
    recipes.mkdir()
    return recipes, outputs


def _processed(recipes: Path, outputs: Path, run_id: str = "run1") -> Metadata:
    meta = Metadata.load_latest(outputs)
    pipeline.classify_all(meta, recipes)
    pipeline.process(meta, recipes, outputs, run_id=run_id)
    return meta


@pytest.fixture
def processed() -> Callable[..., Metadata]:
    """Classify and convert everything in recipes/, returning the working metadata."""
    return _processed
