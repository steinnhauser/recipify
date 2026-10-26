"""Run the stages. Each reads the previous stage's artifacts and writes its own.

Work is cached by content hash and engine version: a stage skips every document that
already has a current artifact, so re-running is cheap and an interrupted run resumes where
it stopped. Transcriptions of scans are costly to make and are never overwritten.
"""

import time
from collections import Counter
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

from recipify import inventory
from recipify.assess import assess
from recipify.categories import Category
from recipify.curation import Curation
from recipify.extract import LOCAL
from recipify.labels import detect_labels, refine_title
from recipify.models import (
    Assessment,
    Catalog,
    Entry,
    Extraction,
    Inventory,
    Kind,
    Recipe,
    SourceFile,
    Structured,
    Tier,
    now_iso,
)
from recipify.report import render_report
from recipify.store import Workspace, write_json
from recipify.structure import rules
from recipify.text import fold, tokens

OnResult = Callable[[str, str], None]  # (source path, "ok" or the error)
TIER_RANK = {Tier.READY: 0, Tier.REVIEW: 1, Tier.EXCLUDED: 2}
TWIN_SIMILARITY = 0.9


@dataclass
class StageResult:
    done: int = 0
    skipped: int = 0
    failed: int = 0
    errors: list[tuple[str, str]] = field(default_factory=list)

    def as_dict(self) -> dict[str, object]:
        return {"done": self.done, "skipped": self.skipped, "failed": self.failed}


def _log(ws: Workspace, stage: str, started: float, **details: object) -> None:
    ws.log_run(
        {"stage": stage, "at": now_iso(), "seconds": round(time.time() - started, 1), **details}
    )


def recipe_files(inv: Inventory) -> list[SourceFile]:
    """The documents worth converting: unique files that are recipes."""
    return [f for f in inv.canonical() if f.kind == Kind.RECIPE]


# --- stage 1 ----------------------------------------------------------------------------


def run_inventory(
    ws: Workspace, curation: Curation, on_file: Callable[[str], None] | None = None
) -> Inventory:
    if not ws.sources.is_dir():
        raise FileNotFoundError(f"{ws.sources} is not a directory")
    started = time.time()
    inv = inventory.scan(ws.sources, ws.load_inventory(), curation, on_file)
    write_json(ws.inventory_path, inv)
    _log(ws, "inventory", started, files=len(inv.files), unique=len(inv.canonical()))
    return inv


# --- stage 2 ----------------------------------------------------------------------------


def run_extract(
    ws: Workspace,
    inv: Inventory,
    limit: int | None = None,
    force: bool = False,
    on_result: OnResult | None = None,
) -> StageResult:
    started, result = time.time(), StageResult()
    for f in recipe_files(inv):
        engine = LOCAL.get(f.category)
        if engine is None:  # scans and photos: see `register`
            continue
        target = ws.extraction_path(f.sha256, engine.name, engine.version)
        if target.exists() and not force:
            result.skipped += 1
            continue
        if limit is not None and result.done + result.failed >= limit:
            break
        try:
            text, checks = engine.run(ws.sources / f.path)
            if not text.strip():
                raise ValueError("no text found")
            extraction = Extraction(
                sha256=f.sha256,
                engine=engine.name,
                version=engine.version,
                text=text,
                checks=checks,
            )
            write_json(target, extraction)
            result.done += 1
            status = "ok"
        except Exception as exc:  # one bad file must not stop a long run
            result.failed += 1
            status = f"{type(exc).__name__}: {exc}"
            result.errors.append((f.path, status))
        if on_result:
            on_result(f.path, status)
    _log(ws, "extract", started, **result.as_dict())
    return result


def best_extraction(ws: Workspace, f: SourceFile) -> Extraction | None:
    """The current local engine's text if there is one, else the newest transcription."""
    found = list(ws.extractions(f.sha256))
    local = LOCAL.get(f.category)
    for e in found:
        if local and (e.engine, e.version) == (local.name, local.version):
            return e
    return found[0] if found else None


def register(
    ws: Workspace,
    f: SourceFile,
    text: str,
    engine: str,
    accuracy: float | None = None,
    notes: str = "",
) -> Path:
    """Store a transcription made outside the pipeline (by hand or by a vision model).

    Transcriptions are costly, so an existing one is never overwritten: a second
    transcription by the same engine is stored as the next version.
    """
    version = 1
    while ws.extraction_path(f.sha256, engine, version).exists():
        version += 1
    target = ws.extraction_path(f.sha256, engine, version)
    extraction = Extraction(
        sha256=f.sha256,
        engine=engine,
        version=version,
        text=text,
        costly=True,
        accuracy=accuracy,
        notes=notes,
    )
    write_json(target, extraction)
    return target


# --- stage 3 ----------------------------------------------------------------------------


def _label(e: Extraction) -> str:
    return f"{e.engine}@v{e.version}"


def run_structure(
    ws: Workspace,
    inv: Inventory,
    limit: int | None = None,
    force: bool = False,
    on_result: OnResult | None = None,
) -> StageResult:
    started, result = time.time(), StageResult()
    for f in recipe_files(inv):
        extraction = best_extraction(ws, f)
        if extraction is None:
            continue
        target = ws.structured_path(f.sha256, rules.ENGINE, rules.VERSION)
        if target.exists() and not force:
            previous = Structured.model_validate_json(target.read_text(encoding="utf-8"))
            if previous.extraction == _label(extraction):
                result.skipped += 1
                continue
        if limit is not None and result.done + result.failed >= limit:
            break
        try:
            structured = Structured(
                sha256=f.sha256,
                engine=rules.ENGINE,
                version=rules.VERSION,
                extraction=_label(extraction),
                recipe=rules.structure(extraction.text, Path(f.path).stem),
            )
            write_json(target, structured)
            result.done += 1
            status = "ok"
        except Exception as exc:  # one bad file must not stop a long run
            result.failed += 1
            status = f"{type(exc).__name__}: {exc}"
            result.errors.append((f.path, status))
        if on_result:
            on_result(f.path, status)
    _log(ws, "structure", started, engine=f"{rules.ENGINE}@v{rules.VERSION}", **result.as_dict())
    return result


# --- stage 4 ----------------------------------------------------------------------------


def _choose(
    ws: Workspace, f: SourceFile, extraction: Extraction | None
) -> tuple[Structured | None, Assessment]:
    """Assess every structuring of the current text (one per structurer version) and keep
    the most trustworthy one."""
    if extraction is None:
        return None, assess(f, None, None)
    candidates = [
        (s, assess(f, extraction, s))
        for s in ws.structured(f.sha256)
        if s.extraction == _label(extraction)
    ]
    if not candidates:
        return None, assess(f, extraction, None)
    return min(candidates, key=lambda c: (TIER_RANK[c[1].tier], len(c[1].reasons), -c[0].version))


def _words(entry: Entry) -> Counter[str]:
    return Counter(tokens("\n".join(entry.recipe.lines()))) if entry.recipe else Counter()


def _merge_twins(entries: list[Entry]) -> None:
    """The same recipe saved twice (a .docx and the PDF exported from it): keep one.

    Twins share a display title and at least 90% of their words. The Word file wins, as
    the editable original; otherwise the shorter path.
    """
    groups: dict[str, list[Entry]] = {}
    for e in entries:
        if e.assessment.tier == Tier.READY:
            groups.setdefault(fold(e.title), []).append(e)
    for group in groups.values():
        group.sort(key=lambda e: (e.category != Category.DOCX_FILES, len(e.source), e.source))
        kept: list[tuple[Entry, Counter[str]]] = []
        for e in group:
            words = _words(e)
            twin = next((k for k, w in kept if _similarity(w, words) >= TWIN_SIMILARITY), None)
            if twin is None:
                kept.append((e, words))
                continue
            e.assessment.tier = Tier.EXCLUDED
            e.assessment.reasons = [f"same recipe as {twin.source}"]
            twin.duplicates.append(e.source)


def _similarity(a: Counter[str], b: Counter[str]) -> float:
    return sum((a & b).values()) / max(sum((a | b).values()), 1)


def _distinct_titles(entries: list[Entry], curation: Curation) -> None:
    """Different recipes with one title ('Þorskur') get their file or folder name added."""
    groups: dict[str, list[Entry]] = {}
    for e in entries:
        if e.assessment.tier == Tier.READY and e.recipe:
            groups.setdefault(fold(e.title), []).append(e)
    for group in groups.values():
        if len(group) < 2:
            continue
        for hint in (_file_hint, _folder_hint):
            clashing = [e for e in group if sum(fold(o.title) == fold(e.title) for o in group) > 1]
            for e in clashing:
                h = hint(e)
                if Path(e.source).stem in curation.titles or fold(h) in fold(e.title):
                    continue
                # 'Aðalbláber & rjómi (tasting).pdf' is just a more specific title
                e.title = h if fold(h).startswith(fold(e.title)) else f"{e.title} ({h})"


def _file_hint(e: Entry) -> str:
    return refine_title(Path(e.source).stem, e.recipe or Recipe(title=""), "", {})


def _folder_hint(e: Entry) -> str:
    return Path(e.source).parent.name or "top folder"


def build_catalog(ws: Workspace, inv: Inventory, curation: Curation) -> Catalog:
    started = time.time()
    copies: dict[str, list[str]] = {}
    for f in inv.files.values():
        if f.duplicate_of:
            copies.setdefault(f.duplicate_of, []).append(f.path)
    entries = []
    for f in inv.canonical():
        stem = Path(f.path).stem
        extraction = best_extraction(ws, f) if f.kind == Kind.RECIPE else None
        structured, assessment = _choose(ws, f, extraction)
        if stem in curation.tier and assessment.tier != Tier.EXCLUDED:
            assessment.tier = curation.tier[stem]
            assessment.reasons.append("tier set by hand in curation.json")
        entry = Entry(
            id=f.sha256[:12],
            source=f.path,
            category=f.category,
            kind=f.kind,
            pages=f.pages,
            duplicates=sorted(copies.get(f.path, [])),
            assessment=assessment,
            title=stem,
        )
        if structured and extraction:
            recipe = structured.recipe
            entry.extraction = _label(extraction)
            entry.structure = f"{structured.engine}@v{structured.version}"
            entry.title = refine_title(recipe.title, recipe, stem, curation.titles)
            paths = "\n".join([f.path, *entry.duplicates])  # copies in other folders add hints
            entry.labels = detect_labels(entry.title, paths, recipe) | curation.labels.get(stem, {})
            entry.recipe = recipe
        entries.append(entry)
    _merge_twins(entries)
    _distinct_titles(entries, curation)
    entries.sort(key=lambda e: (TIER_RANK[e.assessment.tier], e.title.casefold()))
    catalog = Catalog(entries=entries)
    tiers = {e.source: e.assessment.tier.value for e in entries}
    previous = ws.latest_snapshot()
    changes = sorted(
        (source, previous.get(source, "new"), tier)
        for source, tier in tiers.items()
        if previous and previous.get(source) != tier
    )
    write_json(ws.catalog_path, catalog)
    ws.report_path.write_text(render_report(catalog, inv, changes), encoding="utf-8")
    ws.save_snapshot(catalog.created_at, tiers)
    counts = {t.value: len(catalog.by_tier(t)) for t in Tier}
    _log(ws, "catalog", started, changes=len(changes), **counts)
    return catalog
