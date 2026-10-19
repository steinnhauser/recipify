"""Processing categories, ordered by how hard it is to extract content."""

from enum import StrEnum


class Category(StrEnum):
    READABLE_PDFS = "readable_pdfs"  # PDFs with an embedded text layer: local extraction
    IMAGE_BASED_PDFS = "image_based_pdfs"  # scanned PDFs: need OCR via API
    DOCX_FILES = "docx_files"  # Word .docx: local extraction
    IMAGE_FILES = "image_files"  # jpg/png photos of recipes: need OCR via API
    SPREADSHEETS = "spreadsheets"  # xls/xlsx: local conversion to tables
    LEGACY_OFFICE = "legacy_office"  # doc/odt/pptx/...: converted locally via LibreOffice
    EPUB_BOOKS = "epub_books"  # EPUB e-books (some are misnamed .pdf): local extraction
    EMPTY_OR_CORRUPTED = "empty_or_corrupted"  # zero bytes, unreadable, no content
    IGNORED = "ignored"  # lock files, .DS_Store, shortcuts, archives
    OTHER_FORMATS = "other_formats"  # anything unrecognised


# Categories the pipeline can currently convert to markdown.
PROCESSABLE = {
    Category.READABLE_PDFS,
    Category.IMAGE_BASED_PDFS,
    Category.DOCX_FILES,
    Category.IMAGE_FILES,
    Category.SPREADSHEETS,
    Category.LEGACY_OFFICE,
    Category.EPUB_BOOKS,
}

# Categories that require an OCR API call.
NEEDS_OCR = {Category.IMAGE_BASED_PDFS, Category.IMAGE_FILES}
