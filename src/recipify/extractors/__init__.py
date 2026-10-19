"""Markdown extractors, one per processable category."""

from collections.abc import Callable
from pathlib import Path

from recipify.categories import Category
from recipify.extractors.docx import docx_to_markdown
from recipify.extractors.epub import epub_to_markdown
from recipify.extractors.ocr import ocr_to_markdown
from recipify.extractors.office import legacy_office_to_markdown, spreadsheet_to_markdown
from recipify.extractors.pdf import pdf_to_markdown

Extractor = Callable[[Path], str]

EXTRACTORS: dict[Category, tuple[str, Extractor]] = {
    Category.READABLE_PDFS: ("pypdf", pdf_to_markdown),
    Category.DOCX_FILES: ("python-docx", docx_to_markdown),
    Category.SPREADSHEETS: ("openpyxl", spreadsheet_to_markdown),
    Category.LEGACY_OFFICE: ("libreoffice", legacy_office_to_markdown),
    Category.EPUB_BOOKS: ("epub-stdlib", epub_to_markdown),
    Category.IMAGE_BASED_PDFS: ("mistral-ocr", ocr_to_markdown),
    Category.IMAGE_FILES: ("mistral-ocr", ocr_to_markdown),
}
