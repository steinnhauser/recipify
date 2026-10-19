"""Scan, classify, sort and process recipe files."""

import hashlib
import shutil
from collections.abc import Callable, Collection, Iterable
from pathlib import Path

from recipify.categories import NEEDS_OCR, PROCESSABLE, Category
from recipify.classify import classify
from recipify.extractors import EXTRACTORS
from recipify.labels import describe
from recipify.metadata import Metadata, new_run_id, now_iso
from recipify.naming import slugify, standard_name
from recipify.quality import Quality, detect_language, score_text
from recipify.spelling import fix_spelling
from recipify.tidy import tidy

ORIGINAL_FORM = {
    Category.READABLE_PDFS: "pdf (text layer)",
    Category.IMAGE_BASED_PDFS: "pdf (scanned images)",
    Category.DOCX_FILES: "word document",
    Category.IMAGE_FILES: "photo/image",
    Category.SPREADSHEETS: "spreadsheet",
    Category.LEGACY_OFFICE: "legacy office document",
    Category.EPUB_BOOKS: "e-book (epub)",
}


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def scan(recipes_dir: Path) -> list[Path]:
    return sorted(p for p in recipes_dir.rglob("*") if p.is_file())


def _unique_slug(meta: Metadata, key: str, path: Path, digest: str) -> str:
    slug = Path(standard_name(path)).stem if path.suffix else slugify(path.name)
    used = {e.get("slug") for k, e in meta.recipes.items() if k != key}
    return f"{slug}-{digest[:8]}" if slug in used else slug


def classify_all(
    meta: Metadata,
    recipes_dir: Path,
    on_progress: Callable[[Path], None] | None = None,
    force: bool = False,
) -> None:
    """Classify every file and record it in metadata (unchanged files are not re-read)."""
    for path in scan(recipes_dir):
        key = path.relative_to(recipes_dir).as_posix()
        if on_progress:
            on_progress(path)
        entry = meta.entry(key)
        size = path.stat().st_size
        if not force and "original_format" in entry and entry.get("size") == size:
            continue
        digest = sha256(path)
        result = classify(path)
        entry.update(
            source=key,
            size=size,
            sha256=digest,
            category=result.category.value,
            classification_reason=result.reason,
            original_format=path.suffix.lower().lstrip(".") or "none",
            original_form=ORIGINAL_FORM.get(result.category, result.category.value),
            suggested_name=standard_name(path),
            slug=_unique_slug(meta, key, path, digest),
        )


def sort_files(meta: Metadata, recipes_dir: Path, sorted_dir: Path) -> int:
    """Copy (never move) sources into sorted_dir/<category>/. Returns files copied."""
    copied = 0
    for key, entry in meta.recipes.items():
        src = recipes_dir / key
        if not src.exists():
            continue
        dest = sorted_dir / entry["category"] / f"{entry['slug']}{src.suffix.lower()}"
        if dest.exists():
            continue
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dest)
        copied += 1
    return copied


def carry_forward(
    meta: Metadata, outputs_dir: Path, run_id: str, skip: Collection[str] = ()
) -> int:
    """Copy every current output into the new version so each version is a complete tree.

    The copy is recorded as a version with ``carried_from`` and is not reported as a change.
    """
    carried = 0
    for key, entry in meta.recipes.items():
        if key in skip or any(v["run_id"] == run_id for v in entry["versions"]):
            continue
        latest = next(
            (
                v
                for v in reversed(entry["versions"])
                if v["status"] == "ok" and (outputs_dir / v["output"]).is_file()
            ),
            None,
        )
        if latest is None:
            continue
        out = Path(run_id) / Path(latest["output"]).relative_to(Path(latest["output"]).parts[0])
        (outputs_dir / out).parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(outputs_dir / latest["output"], outputs_dir / out)
        entry["versions"].append(
            {
                **latest,
                "version": len(entry["versions"]) + 1,
                "run_id": run_id,
                "output": out.as_posix(),
                "carried_from": latest.get("carried_from") or latest["run_id"],
                "created_at": now_iso(),
            }
        )
        carried += 1
    return carried


def _already_done(entry: dict) -> bool:
    return any(v["status"] == "ok" and v["sha256"] == entry["sha256"] for v in entry["versions"])


def process(
    meta: Metadata,
    recipes_dir: Path,
    outputs_dir: Path,
    categories: Iterable[Category] | None = None,
    limit: int | None = None,
    force: bool = False,
    run_id: str | None = None,
    note: str = "",
    on_result: Callable[[str, str, str | None], None] | None = None,
) -> str:
    """Convert files to markdown into outputs_dir/<run_id>/<category>/<slug>.md."""
    run_id = run_id or new_run_id()
    meta.start_run(run_id, note)
    wanted = set(categories) if categories else PROCESSABLE - NEEDS_OCR  # OCR only on request
    done = 0
    todo = []
    for key, entry in sorted(meta.recipes.items()):
        category = Category(entry["category"])
        if category in wanted and category in EXTRACTORS and (force or not _already_done(entry)):
            todo.append(key)
    if not todo:
        meta.data["runs"].pop(run_id, None)
        return run_id
    carry_forward(meta, outputs_dir, run_id, skip=todo)
    for key in todo:
        entry = meta.recipes[key]
        category = Category(entry["category"])
        if limit is not None and done >= limit:
            break
        done += 1
        processor, extract = EXTRACTORS[category]
        version = {
            "version": len(entry["versions"]) + 1,
            "run_id": run_id,
            "processor": processor,
            "sha256": entry["sha256"],
            "created_at": now_iso(),
        }
        try:
            markdown = extract(recipes_dir / key)
            if not markdown.strip():
                raise ValueError("extractor returned no content")
            out = Path(run_id) / category.value / f"{entry['slug']}.md"
            (outputs_dir / out).parent.mkdir(parents=True, exist_ok=True)
            (outputs_dir / out).write_text(markdown, encoding="utf-8")
            language = detect_language(markdown)
            entry["language"] = language
            version.update(
                status="ok",
                output=out.as_posix(),
                error=None,
                language=language,
                quality=score_text(markdown, language).to_dict(),
            )
        except Exception as exc:
            version.update(status="failed", output=None, error=f"{type(exc).__name__}: {exc}")
        entry["versions"].append(version)
        if on_result:
            on_result(key, version["status"], version["error"])
    meta.write_run(outputs_dir, run_id)
    return run_id


def register_manual(
    meta: Metadata,
    outputs_dir: Path,
    key: str,
    markdown_file: Path,
    processor: str,
    run_id: str | None = None,
    language: str | None = None,
    quality: Quality | None = None,
    note: str = "",
) -> Path:
    """Store hand/LLM-produced markdown as a new version of an already classified source.

    Calling this repeatedly with the same run_id groups files into one output version.
    """
    entry = meta.recipes[key]
    run_id = run_id or new_run_id()
    meta.start_run(run_id, note)
    carry_forward(meta, outputs_dir, run_id)
    text = markdown_file.read_text(encoding="utf-8")
    language = language or detect_language(text)
    quality = quality or score_text(text, language)
    out: Path = Path(run_id) / entry["category"] / f"{entry['slug']}.md"
    (outputs_dir / out).parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(markdown_file, outputs_dir / out)
    entry["language"] = language
    entry["versions"].append(
        {
            "version": len(entry["versions"]) + 1,
            "run_id": run_id,
            "processor": processor,
            "sha256": entry["sha256"],
            "created_at": now_iso(),
            "status": "ok",
            "output": out.as_posix(),
            "error": None,
            "language": language,
            "quality": quality.to_dict(),
        }
    )
    meta.write_run(outputs_dir, run_id)
    return out


def _comparable(info: dict) -> dict:
    # label order carries no meaning, so reordering alone must not create a new version
    labels = {k: sorted(v) for k, v in info.get("labels", {}).items()}
    return {**info, "labels": labels}


def enrich(
    meta: Metadata,
    outputs_dir: Path,
    curation: dict,
    run_id: str | None = None,
    note: str = "",
) -> str | None:
    """Add refined titles and labels to every recipe's ``recipe{}`` as a new full-copy version.

    Files whose display title differs from their heading get that heading rewritten in the
    new version (earlier versions are untouched). Returns None when nothing changed.
    """
    run_id = run_id or new_run_id()
    plan: list[tuple[str, dict, dict, str]] = []
    for key, entry in meta.recipes.items():
        latest = next((v for v in reversed(entry["versions"]) if v["status"] == "ok"), None)
        if latest is None or not (outputs_dir / latest["output"]).is_file():
            continue
        text = (outputs_dir / latest["output"]).read_text(encoding="utf-8")
        previous = entry.get("recipe", {})
        info = describe(key, text, curation)
        if previous.get("original_title"):
            # the heading may already be retitled, so describe the text under its original title
            info = describe(
                key,
                text.replace(f"# {previous['title']}", f"# {previous['original_title']}", 1),
                curation,
            )
        merged = {**previous, **info}
        if _comparable(merged) != _comparable(previous):
            plan.append((key, merged, latest, text))
    if not plan:
        return None
    meta.start_run(run_id, note)
    carry_forward(meta, outputs_dir, run_id)
    for key, merged, _, text in plan:
        entry = meta.recipes[key]
        entry["recipe"] = merged
        new_version = entry["versions"][-1]
        if merged["title"] != merged["original_title"] and new_version["run_id"] == run_id:
            path = outputs_dir / new_version["output"]
            heading = f"# {merged['original_title']}"
            if text.startswith(heading):
                path.write_text(f"# {merged['title']}" + text[len(heading) :], encoding="utf-8")
            else:
                path.write_text(f"# {merged['title']}\n\n{text}", encoding="utf-8")
            new_version.pop("carried_from", None)
            new_version["processor"] = f"{new_version['processor']}+title-refine"
    meta.write_run(outputs_dir, run_id)
    return run_id


def tidy_run(
    meta: Metadata, outputs_dir: Path, run_id: str | None = None, note: str = ""
) -> str | None:
    """Write reader-ready text (no echoed titles, no repeated blocks) as a new full-copy version.

    The raw extraction stays untouched in the previous version; tidied files record
    ``tidied_from`` (the raw version's run) and how many characters were dropped.
    """
    run_id = run_id or new_run_id()
    plan: list[tuple[str, str, str, dict]] = []
    for key, entry in meta.recipes.items():
        latest = next((v for v in reversed(entry["versions"]) if v["status"] == "ok"), None)
        title = (entry.get("recipe") or {}).get("title")
        if latest is None or not title or "tidy" in latest["processor"]:
            continue
        path = outputs_dir / latest["output"]
        if not path.is_file():
            continue
        raw = path.read_text(encoding="utf-8")
        clean = tidy(raw, title)
        if clean.split() != raw.split():
            plan.append((key, clean, raw, latest))
    if not plan:
        return None
    meta.start_run(run_id, note)
    carry_forward(meta, outputs_dir, run_id)
    for key, clean, raw, latest in plan:
        version = meta.recipes[key]["versions"][-1]
        (outputs_dir / version["output"]).write_text(clean, encoding="utf-8")
        version.pop("carried_from", None)
        version["processor"] = f"{latest['processor']}+tidy"
        version["tidied_from"] = latest["run_id"]
        version["chars_removed"] = len(raw) - len(clean)
        version["quality"] = latest.get("quality", version.get("quality"))
    meta.write_run(outputs_dir, run_id)
    return run_id


def spelling_run(
    meta: Metadata,
    outputs_dir: Path,
    fixes: dict[str, str],
    run_id: str | None = None,
    note: str = "",
) -> str | None:
    """Apply reviewed spelling fixes as a new full-copy version (older versions keep raw text)."""
    run_id = run_id or new_run_id()
    plan: list[tuple[str, str, int, dict]] = []
    for key, entry in meta.recipes.items():
        latest = next((v for v in reversed(entry["versions"]) if v["status"] == "ok"), None)
        if latest is None:
            continue
        path = outputs_dir / latest["output"]
        if not path.is_file():
            continue
        fixed, n = fix_spelling(path.read_text(encoding="utf-8"), fixes)
        if n:
            plan.append((key, fixed, n, latest))
    if not plan:
        return None
    meta.start_run(run_id, note)
    carry_forward(meta, outputs_dir, run_id)
    for key, fixed, n, latest in plan:
        version = meta.recipes[key]["versions"][-1]
        (outputs_dir / version["output"]).write_text(fixed, encoding="utf-8")
        version.pop("carried_from", None)
        base = latest["processor"].removesuffix("+spelling")
        version["processor"] = f"{base}+spelling"
        version["spelling_fixes"] = n
    meta.write_run(outputs_dir, run_id)
    return run_id
