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
from recipify import split as split_stage
from recipify.assess import assess
from recipify.categories import Category
from recipify.curation import Curation
from recipify.extract import LOCAL
from recipify.labels import detect_labels, refine_title
from recipify.models import (
    Catalog,
    Entry,
    Extraction,
    Inventory,
    Kind,
    Recipe,
    SourceFile,
    Split,
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


def transcriptions(ws: Workspace, inv: Inventory) -> list[tuple[SourceFile, Extraction]]:
    """The transcription each document uses (scans and photos), least certain first."""
    found = [(f, best_extraction(ws, f)) for f in inv.canonical()]
    rows = [(f, e) for f, e in found if e is not None and e.costly]
    return sorted(rows, key=lambda r: (-1 if r[1].accuracy is None else r[1].accuracy, r[0].path))


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


def current_split(ws: Workspace, f: SourceFile, extraction: Extraction) -> Split | None:
    path = ws.split_path(f.sha256, _label(extraction), split_stage.ENGINE, split_stage.VERSION)
    return ws.load_split(path)


def run_split(
    ws: Workspace,
    inv: Inventory,
    curation: Curation,
    force: bool = False,
    on_result: OnResult | None = None,
) -> StageResult:
    """Stage 2b: decide, for every document, whether it holds one recipe or several."""
    started, result = time.time(), StageResult()
    for f in recipe_files(inv):
        extraction = best_extraction(ws, f)
        if extraction is None:
            continue
        stem = Path(f.path).stem
        keep_whole = stem in curation.keep_whole
        previous = current_split(ws, f, extraction)
        if previous and previous.by_hand == keep_whole and not force:
            result.skipped += 1
            continue
        decision = split_stage.split(
            f.sha256, _label(extraction), extraction.text, stem, keep_whole, curation.vocabulary
        )
        path = ws.split_path(f.sha256, _label(extraction), decision.engine, decision.version)
        write_json(path, decision)
        result.done += 1
        if on_result:
            on_result(f.path, f"{decision.decision}: {len(decision.units)} recipe(s)")
    _log(
        ws,
        "split",
        started,
        engine=f"{split_stage.ENGINE}@v{split_stage.VERSION}",
        **result.as_dict(),
    )
    return result


def run_structure(
    ws: Workspace,
    inv: Inventory,
    limit: int | None = None,
    force: bool = False,
    on_result: OnResult | None = None,
) -> StageResult:
    """Stage 3: one structured recipe per unit, keyed by the hash of the unit's text."""
    started, result = time.time(), StageResult()
    for f in recipe_files(inv):
        extraction = best_extraction(ws, f)
        decision = current_split(ws, f, extraction) if extraction else None
        if extraction is None or decision is None:
            continue
        for unit in decision.units:
            target = ws.structured_path(unit.sha256, rules.ENGINE, rules.VERSION)
            if target.exists() and not force:
                result.skipped += 1
                continue
            if limit is not None and result.done + result.failed >= limit:
                break
            name = f"{f.path}#{unit.index}" if len(decision.units) > 1 else f.path
            try:
                structured = Structured(
                    sha256=f.sha256,
                    engine=rules.ENGINE,
                    version=rules.VERSION,
                    extraction=_label(extraction),
                    split=decision.label,
                    unit=unit.index,
                    input_sha256=unit.sha256,
                    recipe=rules.structure(unit.text, Path(f.path).stem),
                )
                write_json(target, structured)
                result.done += 1
                status = "ok"
            except Exception as exc:  # one bad file must not stop a long run
                result.failed += 1
                status = f"{type(exc).__name__}: {exc}"
                result.errors.append((name, status))
            if on_result:
                on_result(name, status)
    _log(ws, "structure", started, engine=f"{rules.ENGINE}@v{rules.VERSION}", **result.as_dict())
    return result


# --- stage 4 ----------------------------------------------------------------------------


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
        hints: dict[str, list[str]] = {e.ref: [] for e in group}
        base = {e.ref: e.title for e in group}

        def title(e: Entry) -> str:
            return f"{base[e.ref]} ({', '.join(hints[e.ref])})" if hints[e.ref] else base[e.ref]

        for hint in (_file_hint, _folder_hint):
            clashing = [e for e in group if sum(title(o) == title(e) for o in group) > 1]
            for e in clashing:
                h = hint(e)
                if Path(e.source).stem in curation.titles or fold(h) in fold(title(e)):
                    continue
                if not hints[e.ref] and fold(h).startswith(fold(base[e.ref])):
                    base[e.ref] = h  # 'Aðalbláber & rjómi (tasting).pdf': a more specific title
                else:
                    hints[e.ref].append(h)
        for e in group:
            e.title = title(e)


def _file_hint(e: Entry) -> str:
    return refine_title(Path(e.source).stem, e.recipe or Recipe(title=""), "", {})


def _folder_hint(e: Entry) -> str:
    return Path(e.source).parent.name or "top folder"


def _entries(ws: Workspace, f: SourceFile, copies: list[str], curation: Curation) -> list[Entry]:
    """One catalog entry per recipe in the document (one, unless it was split)."""
    stem = Path(f.path).stem
    extraction = best_extraction(ws, f) if f.kind == Kind.RECIPE else None
    decision = current_split(ws, f, extraction) if extraction else None
    base = Entry(
        id=f.sha256[:12],
        source=f.path,
        category=f.category,
        kind=f.kind,
        pages=f.pages,
        duplicates=copies,
        assessment=assess(f, extraction, None),
        title=stem,
    )
    if extraction is None or decision is None:
        return [_curated(base, stem, curation)]
    entries = []
    several = len(decision.units) > 1
    for unit in decision.units:
        path = ws.structured_path(unit.sha256, rules.ENGINE, rules.VERSION)
        structured = ws.load_structured(path)
        entry = base.model_copy(deep=True)
        entry.extraction, entry.split = _label(extraction), decision.label
        entry.transcribed, entry.accuracy = extraction.costly, extraction.accuracy
        entry.unit_pages = unit.pages
        if several:
            entry.id, entry.unit, entry.units = (
                f"{base.id}-{unit.index}",
                unit.index,
                len(decision.units),
            )
        entry.assessment = assess(f, extraction, structured, unit.text, curation.vocabulary)
        if structured:
            recipe = structured.recipe
            entry.structure = f"{structured.engine}@v{structured.version}"
            entry.title = refine_title(
                recipe.title, recipe, "" if several else stem, curation.titles
            )
            hints = "\n".join([f.path, *copies])  # copies in other folders add hints
            entry.labels = detect_labels(entry.title, hints, recipe) | curation.labels.get(stem, {})
            entry.recipe = recipe
        entries.append(_curated(entry, stem, curation))
    return entries


def _curated(entry: Entry, stem: str, curation: Curation) -> Entry:
    if stem in curation.tier and entry.assessment.tier != Tier.EXCLUDED:
        entry.assessment.tier = curation.tier[stem]
        entry.assessment.reasons.append("tier set by hand in curation.json")
    return entry


def build_catalog(ws: Workspace, inv: Inventory, curation: Curation) -> Catalog:
    started = time.time()
    copies: dict[str, list[str]] = {}
    for f in inv.files.values():
        if f.duplicate_of:
            copies.setdefault(f.duplicate_of, []).append(f.path)
    entries = []
    for f in inv.canonical():
        entries += _entries(ws, f, sorted(copies.get(f.path, [])), curation)
    _merge_twins(entries)
    _distinct_titles(entries, curation)
    entries.sort(key=lambda e: (TIER_RANK[e.assessment.tier], e.title.casefold()))
    catalog = Catalog(entries=entries)
    tiers = {e.ref: e.assessment.tier.value for e in entries}
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
