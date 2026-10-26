"""Stage 2: turn each source document into plain text.

One local engine per category with a text layer: free, exact and repeatable. Scans and
photos have no text layer; their transcriptions are made outside the pipeline (by hand or
by a vision model, from the page images `recipify pages` writes) and stored with
`recipify register`.
"""

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from recipify.categories import Category
from recipify.extract import docx, office, pdf

Result = tuple[str, dict[str, float]]


@dataclass(frozen=True)
class Engine:
    name: str
    version: int
    run: Callable[[Path], Result]

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
