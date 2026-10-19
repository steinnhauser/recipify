"""Build the single-file HTML recipe viewer from the newest output version."""

import html
import json
import re
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path

from markdown_it import MarkdownIt

from recipify.labels import detect_labels
from recipify.metadata import Metadata
from recipify.quality import REVIEW_THRESHOLD

TEMPLATE = Path(__file__).with_name("viewer_template.html")
SKIP_CATEGORIES = {"epub_books"}  # whole books are not single recipes
_md = MarkdownIt("commonmark", {"html": False}).enable(["table", "strikethrough"])


@dataclass
class Sample:
    key: str
    entry: dict
    score: float | None
    text: str


def pick_sample(
    meta: Metadata,
    outputs_dir: Path,
    per_group: int = 1000,
    max_chars: int = 10_000,
    min_chars: int = 300,
    min_score: float = REVIEW_THRESHOLD,
) -> list[Sample]:
    """Deterministic, lightweight subset: evenly spaced recipes per course, no duplicates."""
    groups: dict[str, list[Sample]] = defaultdict(list)
    seen: set[str] = set()
    for key, entry in sorted(meta.recipes.items(), key=lambda kv: kv[1].get("slug", "")):
        info = entry.get("recipe") or {}
        version = next((v for v in reversed(entry["versions"]) if v["status"] == "ok"), None)
        title = (info.get("title") or "").lower()
        if (
            version is None
            or entry["category"] in SKIP_CATEGORIES
            or info.get("kind") == "reference"
            or entry["sha256"] in seen
            or (title and title in seen)
        ):
            continue
        path = outputs_dir / version["output"]
        if not path.is_file():
            continue
        text = path.read_text(encoding="utf-8")
        score = (version.get("quality") or {}).get("score")
        if not min_chars <= len(text) <= max_chars or (score is not None and score < min_score):
            continue
        seen |= {entry["sha256"], title}
        course = (info.get("labels", {}).get("course") or ["other"])[0]
        groups[course].append(Sample(key, entry, score, text))
    picked: list[Sample] = []
    for items in groups.values():
        step = max(len(items) / per_group, 1)
        picked += [items[int(i * step)] for i in range(min(per_group, len(items)))]
    return picked


def build_html(samples: list[Sample], version: str, source_run: str) -> str:
    recipes = []
    for i, s in enumerate(samples):
        info = s.entry.get("recipe") or {}
        title = info.get("title") or Path(s.key).stem
        body = re.sub(r"\A#\s+.*\n+", "", s.text)  # the title is shown separately
        labels = info.get("labels", {})
        recipes.append(
            {
                "id": i,
                "title": title,
                "labels": labels,
                "score": s.score,
                "original": info.get("original_filename") or Path(s.key).name,
                "html": _md.render(body),
            }
        )
    return render_page(recipes, version)


def build_demo(source_dir: Path) -> str:
    """Viewer for a folder of markdown recipes (course hinted by subfolder), e.g. examples/."""
    recipes = []
    for i, path in enumerate(sorted(source_dir.rglob("*.md"))):
        text = path.read_text(encoding="utf-8")
        heading = re.match(r"#\s+(.+)\n+", text)
        title = heading.group(1).strip() if heading else path.stem
        body = text[heading.end() :] if heading else text
        source = path.relative_to(source_dir).as_posix()
        recipes.append(
            {
                "id": i,
                "title": title,
                "labels": detect_labels(title, source, body),
                "score": None,
                "original": path.name,
                "html": _md.render(body),
            }
        )
    return render_page(recipes, "demo")


def _static_section(recipes: list[dict]) -> str:
    """All recipes as plain HTML: readable where scripts never run (iOS/macOS Quick Look)."""
    esc = html.escape
    by_title = sorted(recipes, key=lambda r: r["title"].lower())
    groups: dict[str, list[dict]] = defaultdict(list)
    for r in by_title:
        for course in r["labels"].get("course") or ["other"]:
            groups[course].append(r)

    def toc(name: str, items: list[dict]) -> str:
        links = "".join(f'<li><a href="#r{r["id"]}">{esc(r["title"])}</a></li>' for r in items)
        return f"<details><summary>{esc(name)} ({len(items)})</summary><ul>{links}</ul></details>"

    out = [
        '<div id="static">',
        '<h1 id="top">recipify</h1>',
        '<p class="note"><b>Simple view.</b> This preview does not run the page\'s scripts, so '
        "search, filters, favourites and notes are switched off. All "
        f"{len(recipes)} recipes are below: open a group and tap a title. "
        '<a href="#open">How to open the full version</a>.</p>',
        '<nav id="toc">',
        toc("All recipes A-Z", by_title),
        *(toc(c[:1].upper() + c[1:], groups[c]) for c in sorted(groups)),
        "</nav>",
    ]
    for r in by_title:
        labels = [
            v
            for f in ("course", "dish", "diet", "cuisine", "ingredients")
            for v in r["labels"].get(f) or []
        ]
        score = "" if r["score"] is None else str(r["score"])
        warn = (
            '<p class="warn">This text may contain reading errors: '
            "please double-check the amounts.</p>"
            if r["score"] is not None and r["score"] < REVIEW_THRESHOLD
            else ""
        )
        data = esc(json.dumps(r["labels"], ensure_ascii=False))
        out.append(
            f'<article id="r{r["id"]}" data-labels="{data}"'
            f' data-score="{score}" data-original="{esc(r["original"])}">'
            f'<h2 class="rt">{esc(r["title"])}</h2>'
            f'<p class="lab">{esc(" · ".join(labels))}</p>{warn}'
            f'<div class="body">{r["html"]}</div>'
            f'<p class="src">Original file: {esc(r["original"])} · '
            f'<a class="up" href="#top">Back to the list</a></p></article>'
        )
    out += [
        '<section id="open"><h2>Opening the full version</h2>',
        "<p>The full version (search, filters, favourites, notes) needs a web browser that runs "
        "the page's scripts. Previews do not: on iPhone and iPad, tapping the file in Files, "
        "Mail, Messages or WhatsApp shows this simple view, and so does the space-bar preview "
        "on a Mac.</p>",
        "<ul><li><b>Computer (Windows, Mac, Linux):</b> double-click the file to open it in "
        "Chrome, Edge, Firefox or Safari.</li>",
        "<li><b>iPhone / iPad:</b> Safari cannot open files saved on the device. Open the page "
        "from a web address instead, if one was shared with you, or use a file app with its own "
        "browser (for example Documents by Readdle).</li>",
        "<li><b>Android:</b> open the file with Chrome or Firefox.</li></ul>",
        '<p><a class="up" href="#top">Back to the list</a></p></section>',
        "</div>",
    ]
    return "\n".join(out)


def render_page(recipes: list[dict], version: str) -> str:
    page = TEMPLATE.read_text(encoding="utf-8")
    return (
        page.replace("__TITLE__", html.escape(f"recipify {version}"))
        .replace("__VERSION__", html.escape(version))
        .replace("__THRESHOLD__", str(REVIEW_THRESHOLD))
        .replace("__STATIC__", _static_section(recipes))
    )


def build(
    outputs_dir: Path,
    viewer_dir: Path,
    per_group: int = 4,
    note: str = "",
) -> Path:
    """Write viewer/<vNNN>/recipes.html and NOTES.md; never overwrites an earlier prototype."""
    meta = Metadata.load_latest(outputs_dir)
    source_run = max((r for r in meta.data["runs"]), default="none")
    viewer_dir.mkdir(parents=True, exist_ok=True)
    n = 1 + max(
        (int(p.name[1:]) for p in viewer_dir.glob("v[0-9]*") if p.name[1:].isdigit()), default=0
    )
    version = f"v{n:03d}"
    samples = pick_sample(meta, outputs_dir, per_group)
    out_dir = viewer_dir / version
    out_dir.mkdir()
    (out_dir / "recipes.html").write_text(
        build_html(samples, version, source_run), encoding="utf-8"
    )
    lines = [f"# Viewer prototype {version}", "", f"Built from output version `{source_run}`.", ""]
    if note:
        lines += [note, ""]
    lines += [f"{len(samples)} sample recipes (up to {per_group} per course):", ""]
    for s in samples:
        info = s.entry.get("recipe") or {}
        lines.append(
            f"- {info.get('title') or s.key} (original: `{info.get('original_filename') or s.key}`)"
        )
    (out_dir / "NOTES.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    return out_dir / "recipes.html"
