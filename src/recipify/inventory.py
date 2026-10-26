"""Stage 1: hash, classify and triage every source file.

Classification reads file content (a PDF called .pdf may really be an EPUB). Triage then
decides what kind of document it is: a recipe, a book to handle later, or reference material
such as a mise en place list. Byte-identical copies point to one canonical file.
"""

import hashlib
import re
from collections.abc import Callable
from pathlib import Path

from recipify.categories import Category
from recipify.classify import classify
from recipify.curation import Curation
from recipify.models import Inventory, Kind, SourceFile
from recipify.text import fold

MAX_RECIPE_PAGES = 8  # longer documents are books, binders or course folders

# Kitchen paperwork that is not a recipe (folded: no accents, þ->th, ð->d).
REFERENCE_NAME = re.compile(
    r"\b(?:missi|magnutreikn|simaskra|thrif|hladbord|utreikn|starfsm|verdutreikn|pantanir"
    r"|\w*sedill|menu|eldunartim|reglur|rules|rutina|vaktstjor|innihaldslys|leidarbok)"
)
# Folders of dish photos ("Myndir" is Icelandic for pictures): images there are not recipes.
PHOTO_FOLDERS = {"myndir", "photos", "pictures", "images", "img"}
COPY_MARKER = re.compile(r"\(\d+\)|\bcopy\b|afrit", re.I)


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def triage(path: str, category: Category, pages: int | None, curation: Curation) -> Kind:
    stem = Path(path).stem
    if stem in curation.kind:
        return curation.kind[stem]
    folders = {fold(part) for part in Path(path).parts[:-1]}
    if category == Category.IMAGE_FILES and folders & PHOTO_FOLDERS:
        return Kind.PHOTO
    if category == Category.EPUB_BOOKS or (pages or 0) > MAX_RECIPE_PAGES:
        return Kind.BOOK
    if REFERENCE_NAME.search(fold(stem)):
        return Kind.REFERENCE
    return Kind.RECIPE


def _canonical_order(path: str) -> tuple[int, int, str]:
    """Prefer the copy without '(2)' or 'copy' in its path, then the shortest path."""
    return (len(COPY_MARKER.findall(path)), len(path), path)


def scan(
    sources: Path,
    previous: Inventory | None = None,
    curation: Curation | None = None,
    on_file: Callable[[str], None] | None = None,
) -> Inventory:
    """Build the inventory; unchanged files (same size and mtime) are not read again."""
    curation = curation or Curation()
    old = previous.files if previous else {}
    files: dict[str, SourceFile] = {}
    for path in sorted(p for p in sources.rglob("*") if p.is_file()):
        key = path.relative_to(sources).as_posix()
        if on_file:
            on_file(key)
        stat = path.stat()
        known = old.get(key)
        if known and known.size == stat.st_size and known.mtime == stat.st_mtime:
            entry = known.model_copy()
        else:
            result = classify(path)
            entry = SourceFile(
                path=key,
                sha256=sha256(path),
                size=stat.st_size,
                mtime=stat.st_mtime,
                category=result.category,
                reason=result.reason,
                pages=result.pages,
            )
        entry.kind = triage(key, entry.category, entry.pages, curation)
        entry.duplicate_of = None
        files[key] = entry

    by_hash: dict[str, list[str]] = {}
    for key, entry in files.items():
        by_hash.setdefault(entry.sha256, []).append(key)
    for keys in by_hash.values():
        first, *copies = sorted(keys, key=_canonical_order)
        for key in copies:
            files[key].duplicate_of = first
    return Inventory(files=files)
