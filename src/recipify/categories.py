"""File categories, ordered roughly by how hard it is to get faithful text out of them."""

from enum import StrEnum


class Category(StrEnum):
    READABLE_PDFS = "readable_pdfs"  # PDFs with a text layer: exact text, local
    DOCX_FILES = "docx_files"  # Word .docx: exact text, local
    LEGACY_OFFICE = "legacy_office"  # .doc/.odt/.rtf/.pptx: exact text via LibreOffice
    SPREADSHEETS = "spreadsheets"  # .xls/.xlsx/.csv: tables, local
    IMAGE_BASED_PDFS = "image_based_pdfs"  # scans without a text layer: need a transcription
    IMAGE_FILES = "image_files"  # photos: of recipes (transcribe) or of dishes
    EPUB_BOOKS = "epub_books"  # e-books (some misnamed .pdf)
    EMPTY_OR_CORRUPTED = "empty_or_corrupted"  # zero bytes, unreadable, no content
    IGNORED = "ignored"  # lock files, .DS_Store, shortcuts, archives
    OTHER_FORMATS = "other_formats"  # anything unrecognised


# Text comes straight from the file, so a transcription can be checked word for word.
TEXT_LAYER = {
    Category.READABLE_PDFS,
    Category.DOCX_FILES,
    Category.LEGACY_OFFICE,
    Category.SPREADSHEETS,
}
# Text has to be read from pixels: a transcription cannot be checked against a text layer.
NO_TEXT_LAYER = {Category.IMAGE_BASED_PDFS, Category.IMAGE_FILES}
