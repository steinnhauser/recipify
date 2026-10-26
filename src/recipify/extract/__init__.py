"""Stage 2: turn each source document into plain text.

One engine per category. Local engines read the text layer and are free and exact; the OCR
engine reads pixels, costs API credits and only runs when asked for.
"""

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from recipify.categories import NEEDS_OCR, Category
from recipify.extract import docx, ocr, office, pdf

Result = tuple[str, dict[str, float]]


@dataclass(frozen=True)
class Engine:
    name: str
    version: int
    run: Callable[[Path], Result]
    costly: bool = False  # paid API: runs only when asked for, never twice

    @property
    def label(self) -> str:
        return f"{self.name}@v{self.version}"


def _no_checks(fn: Callable[[Path], str]) -> Callable[[Path], Result]:
    return lambda path: (fn(path), {})


LOCAL = {
    Category.READABLE_PDFS: Engine(pdf.ENGINE, pdf.VERSION, pdf.extract_pdf),
    Category.DOCX_FILES: Engine(docx.ENGINE, docx.VERSION, _no_checks(docx.extract_docx)),
    Category.LEGACY_OFFICE: Engine(
        office.LEGACY_ENGINE, office.LEGACY_VERSION, _no_checks(office.extract_legacy)
    ),
    Category.SPREADSHEETS: Engine(
        office.SPREADSHEET_ENGINE,
        office.SPREADSHEET_VERSION,
        _no_checks(office.extract_spreadsheet),
    ),
}
OCR = Engine(ocr.ENGINE, ocr.VERSION, _no_checks(ocr.extract_ocr), costly=True)


def engine_for(category: Category, use_ocr: bool = False) -> Engine | None:
    if category in LOCAL:
        return LOCAL[category]
    if use_ocr and category in NEEDS_OCR:
        return OCR
    return None
