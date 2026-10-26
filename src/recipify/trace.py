"""Follow a published recipe back to its source file, checking every link on the way.

recipe (catalog entry) <- structured artifact (keyed by its input's sha256) <- unit of the
split decision (page numbers, exact text) <- extraction artifact <- source file (sha256).
"""

import hashlib
from dataclasses import dataclass
from pathlib import Path

from recipify.inventory import sha256
from recipify.models import Entry, Extraction, Inventory
from recipify.split import pages
from recipify.store import Workspace


@dataclass
class Link:
    stage: str
    detail: str
    path: Path | None = None
    ok: bool | None = None  # None: nothing to verify at this link


def _parse(label: str) -> tuple[str, int]:
    engine, version = label.rsplit("@v", 1)
    return engine, int(version)


def trace(ws: Workspace, inv: Inventory, entry: Entry) -> list[Link]:
    f = inv.files[entry.source]
    tier = entry.assessment.tier.value
    links = [Link("recipe", f"{entry.title!r}  id {entry.id}  tier {tier}")]
    if not entry.extraction:
        links.append(Link("source", f"{f.path}  ({'; '.join(entry.assessment.reasons)})"))
        return links + [_source(ws, f.path, f.sha256)]

    ex_engine, ex_version = _parse(entry.extraction)
    extraction_path = ws.extraction_path(f.sha256, ex_engine, ex_version)
    sp_engine, sp_version = _parse(entry.split)
    decision = ws.load_split(ws.split_path(f.sha256, entry.extraction, sp_engine, sp_version))
    assert decision is not None
    unit = decision.units[(entry.unit or 1) - 1]
    if entry.structure:
        st_engine, st_version = _parse(entry.structure)
        st_path = ws.structured_path(unit.sha256, st_engine, st_version)
        structured = ws.load_structured(st_path)
        same = bool(structured and structured.input_sha256 == unit.sha256)
        same = same and structured is not None and structured.recipe == entry.recipe
        links.append(Link("structured", f"{entry.structure} from unit {unit.index}", st_path, same))

    text_hash = hashlib.sha256(unit.text.encode("utf-8")).hexdigest()
    extraction = Extraction.model_validate_json(extraction_path.read_text(encoding="utf-8"))
    source_pages = pages(extraction.text)
    in_source = all(
        any(part.strip() in source_pages[n - 1] for n in unit.pages)
        for part in pages(unit.text)
        if part.strip()
    )
    of = f" of {len(decision.units)}" if len(decision.units) > 1 else ""
    links.append(
        Link(
            "unit",
            f"recipe {unit.index}{of}, page(s) {', '.join(map(str, unit.pages))}"
            + (f", set aside: {unit.dropped!r}" if unit.dropped else ""),
            None,
            text_hash == unit.sha256 and in_source,
        )
    )
    split_path = ws.split_path(f.sha256, entry.extraction, sp_engine, sp_version)
    links.append(
        Link(
            "split",
            f"{decision.label}: {decision.decision}: {'; '.join(decision.reasons)}",
            split_path,
        )
    )
    links.append(
        Link("extraction", f"{entry.extraction}", extraction_path, extraction.sha256 == f.sha256)
    )
    return links + [_source(ws, f.path, f.sha256, entry.duplicates)]


def _source(ws: Workspace, path: str, digest: str, copies: list[str] | None = None) -> Link:
    file = ws.sources / path
    ok = file.is_file() and sha256(file) == digest
    also = f"  (identical copies: {', '.join(copies)})" if copies else ""
    return Link("source", f"{path}  sha256 {digest[:16]}…{also}", file, ok)
