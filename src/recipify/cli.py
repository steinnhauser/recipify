"""Command-line interface: one command per pipeline stage, plus `run` for all of them."""

import os
import shlex
import tempfile
from collections import Counter
from pathlib import Path
from typing import Annotated
from urllib.parse import quote

import typer
from dotenv import load_dotenv
from rich.console import Console
from rich.table import Table

from recipify import lock as locking
from recipify import pipeline, viewer
from recipify import trace as tracing
from recipify.curation import Curation
from recipify.extract.pdf import render_pages
from recipify.models import Catalog, Entry, Inventory, Tier
from recipify.report import reason_group, tier_table
from recipify.store import Workspace

app = typer.Typer(
    help="Turn a folder of recipe documents into verified, structured recipes and a viewer.",
    no_args_is_help=True,
)
console = Console()


@app.callback()
def main(
    ctx: typer.Context,
    sources: Annotated[
        Path, typer.Option(envvar="RECIPIFY_SOURCES", help="Folder of source documents.")
    ] = Path("recipes"),
    data: Annotated[
        Path, typer.Option(envvar="RECIPIFY_DATA", help="Pipeline artifacts (cache, catalog).")
    ] = Path("data"),
) -> None:
    ctx.obj = Workspace(sources, data)


def _ws(ctx: typer.Context) -> Workspace:
    ws: Workspace = ctx.obj
    return ws


def _curation(ws: Workspace) -> Curation:
    return Curation.load(ws.data / "curation.json")


def _report(path: str, status: str) -> None:
    mark = "[green]ok[/green]" if status == "ok" else f"[red]failed[/red] {status}"
    console.print(f"{mark}  {path}", highlight=False)


def _inventory(ws: Workspace) -> Inventory:
    with console.status("Scanning sources...") as status:
        return pipeline.run_inventory(ws, _curation(ws), lambda p: status.update(f"Reading {p}"))


def _print_summary(catalog: Catalog, inv: Inventory) -> None:
    table = Table("Category", "Files", "Documents", "Ready", "Review", "Excluded")
    for row in tier_table(catalog, inv):
        table.add_row(*map(str, row))
    console.print(table)
    for tier in (Tier.REVIEW, Tier.EXCLUDED):
        reasons = Counter(
            reason_group(r) for e in catalog.by_tier(tier) for r in e.assessment.reasons
        )
        if reasons:
            console.print(
                f"[bold]{tier.value}[/bold]: "
                + ", ".join(f"{r} ({n})" for r, n in reasons.most_common())
            )


@app.command()
def inventory(ctx: typer.Context) -> None:
    """Stage 1: hash, classify and triage every source file."""
    inv = _inventory(_ws(ctx))
    counts = Counter((f.category.value, f.kind.value) for f in inv.canonical())
    table = Table("Category", "Kind", "Unique files")
    for (cat, kind), n in sorted(counts.items()):
        table.add_row(cat, kind, str(n))
    console.print(table)
    console.print(f"{len(inv.files)} files, {len(inv.canonical())} unique")


@app.command()
def extract(
    ctx: typer.Context,
    limit: Annotated[int | None, typer.Option(help="Convert at most this many files.")] = None,
    force: Annotated[bool, typer.Option(help="Redo extractions that exist.")] = False,
) -> None:
    """Stage 2: extract the text layer of every recipe document (local, free)."""
    ws = _ws(ctx)
    result = pipeline.run_extract(ws, _inventory(ws), limit, force, on_result=_report)
    console.print(f"{result.done} extracted, {result.skipped} cached, {result.failed} failed")


@app.command()
def split(
    ctx: typer.Context,
    force: Annotated[bool, typer.Option(help="Decide again for documents decided before.")] = False,
) -> None:
    """Stage 2b: split documents that hold several recipes (clear cases only)."""
    ws = _ws(ctx)
    result = pipeline.run_split(ws, ws.load_inventory(), _curation(ws), force, _report)
    console.print(f"{result.done} decided, {result.skipped} cached")


@app.command()
def structure(
    ctx: typer.Context,
    limit: Annotated[int | None, typer.Option(help="Structure at most this many files.")] = None,
    force: Annotated[bool, typer.Option(help="Redo results that exist.")] = False,
) -> None:
    """Stage 3: split text into components, ingredients and steps."""
    ws = _ws(ctx)
    result = pipeline.run_structure(ws, ws.load_inventory(), limit, force, on_result=_report)
    console.print(f"{result.done} structured, {result.skipped} cached, {result.failed} failed")


@app.command()
def pages(
    ctx: typer.Context,
    source: Annotated[str, typer.Argument(help="Source path, relative to the sources folder.")],
    out: Annotated[Path, typer.Option(help="Folder for the page images.")] = Path("dist/pages"),
    dpi: Annotated[int, typer.Option(help="Resolution of the rendered pages.")] = 150,
) -> None:
    """Write the page images of a scan or photo, ready to transcribe (then `register` it)."""
    ws = _ws(ctx)
    path = ws.sources / source
    if not path.is_file():
        raise typer.BadParameter(f"{path} not found")
    if path.suffix.lower() == ".pdf":
        written = render_pages(path, out, dpi)
    else:
        out.mkdir(parents=True, exist_ok=True)
        written = [out / path.name]
        written[0].write_bytes(path.read_bytes())
    for page in written:
        console.print(str(page), highlight=False)
    console.print(f"Transcribe them, then: recipify register {shlex.quote(source)} --text <file>")


@app.command()
def register(
    ctx: typer.Context,
    source: Annotated[str, typer.Argument(help="Source path, relative to the sources folder.")],
    text: Annotated[Path, typer.Option(help="Text or markdown file with the transcription.")],
    engine: Annotated[
        str, typer.Option(help="Who or what transcribed it, e.g. manual or vision.")
    ] = "manual",
    accuracy: Annotated[
        float | None, typer.Option(min=0, max=1, help="Your estimate of its accuracy.")
    ] = None,
    notes: Annotated[str, typer.Option(help="Notes kept with the transcription.")] = "",
) -> None:
    """Store a transcription made outside the pipeline (scans read by hand or by a model)."""
    ws = _ws(ctx)
    inv = ws.load_inventory()
    if source not in inv.files:
        raise typer.BadParameter(f"{source} is not in the inventory (run `recipify inventory`)")
    out = pipeline.register(ws, inv.files[source], text.read_text("utf-8"), engine, accuracy, notes)
    console.print(f"Stored {out}")


@app.command()
def catalog(ctx: typer.Context) -> None:
    """Stage 4: check every recipe against its source and decide what is ready."""
    ws = _ws(ctx)
    inv = ws.load_inventory()
    result = pipeline.build_catalog(ws, inv, _curation(ws))
    _print_summary(result, inv)
    console.print(f"Wrote {ws.catalog_path} and {ws.report_path}")


@app.command()
def run(
    ctx: typer.Context,
    folder: Annotated[
        Path | None, typer.Argument(help="Folder of recipe files (default: --sources).")
    ] = None,
    force: Annotated[bool, typer.Option(help="Redo local results that exist.")] = False,
    build_viewer: Annotated[
        bool, typer.Option("--build/--no-build", help="Also write the viewer.")
    ] = True,
    out: Annotated[Path, typer.Option(help="Where to write the viewer.")] = Path("dist/index.html"),
    title: Annotated[str, typer.Option(help="Collection name shown in the viewer.")] = "recipify",
) -> None:
    """Process a folder of recipe files end to end: every stage, then the viewer."""
    ws = _ws(ctx)
    if folder is not None:
        ws = Workspace(folder, ws.data)
    inv = _inventory(ws)
    curation = _curation(ws)
    with console.status("Extracting text..."):
        ex = pipeline.run_extract(ws, inv, force=force)
    with console.status("Splitting documents..."):
        sp = pipeline.run_split(ws, inv, curation, force=force)
    with console.status("Structuring recipes..."):
        st = pipeline.run_structure(ws, inv, force=force)
    console.print(
        f"extract: {ex.done} new, {ex.skipped} cached, {ex.failed} failed · "
        f"split: {sp.done} new, {sp.skipped} cached · "
        f"structure: {st.done} new, {st.skipped} cached, {st.failed} failed"
    )
    for path, error in ex.errors + st.errors:
        console.print(f"[red]failed[/red] {path}: {error}", highlight=False)
    result = pipeline.build_catalog(ws, inv, curation)
    _print_summary(result, inv)
    console.print(f"Report: {ws.report_path}")
    if build_viewer:
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(viewer.render(result, title), encoding="utf-8")
        console.print(f"Viewer: {out} ({len(result.by_tier(Tier.READY))} recipes)")


def _entry(ctx: typer.Context, ref: str) -> Entry:
    entries = _ws(ctx).load_catalog().entries
    found = [e for e in entries if ref in (e.id, e.ref)] or [e for e in entries if e.source == ref]
    if not found:
        raise typer.BadParameter(f"{ref} is not in the catalog")
    if len(found) > 1:
        refs = ", ".join(e.ref for e in found)
        raise typer.BadParameter(f"{ref} holds {len(found)} recipes; pick one of: {refs}")
    return found[0]


@app.command()
def trace(
    ctx: typer.Context,
    ref: Annotated[str, typer.Argument(help="Catalog id, source path, or source#recipe.")],
) -> None:
    """Follow a recipe back to its source file, checking every artifact on the way."""
    ws = _ws(ctx)
    marks = {True: "[green]✓[/green]", False: "[red]✗ mismatch[/red]", None: " "}
    for link in tracing.trace(ws, ws.load_inventory(), _entry(ctx, ref)):
        console.print(
            f"{marks[link.ok]} [bold]{link.stage:<10}[/bold] {link.detail}", highlight=False
        )
        if link.path:
            console.print(f"             {link.path}", highlight=False, style="dim")


@app.command()
def show(
    ctx: typer.Context,
    source: Annotated[str, typer.Argument(help="Catalog id, source path, or source#recipe.")],
) -> None:
    """Print one recipe's assessment and structured content."""
    entry = _entry(ctx, source)
    a = entry.assessment
    console.print(f"[bold]{entry.title}[/bold]  ({entry.source})", highlight=False)
    console.print(f"tier: {a.tier.value}  {'; '.join(a.reasons)}", highlight=False)
    console.print(
        f"engines: {entry.extraction} -> {entry.split} -> {entry.structure}", highlight=False
    )
    if entry.recipe:
        console.print_json(entry.recipe.model_dump_json(exclude_defaults=True))


@app.command()
def build(
    ctx: typer.Context,
    out: Annotated[Path, typer.Option(help="Where to write the viewer.")] = Path("dist/index.html"),
    title: Annotated[str, typer.Option(help="Collection name shown in the page.")] = "recipify",
) -> None:
    """Stage 5: write the single-file viewer with every ready recipe."""
    catalog_ = _ws(ctx).load_catalog()
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(viewer.render(catalog_, title), encoding="utf-8")
    n = len(catalog_.by_tier(Tier.READY))
    console.print(f"Wrote {out} ({out.stat().st_size // 1024} KB, {n} recipes)")


@app.command()
def demo(
    ctx: typer.Context,
    source: Annotated[Path, typer.Option(help="Sample documents.")] = Path("examples/sources"),
    out: Annotated[Path, typer.Option(help="Where to write the demo viewer.")] = Path(
        "site/demo/index.html"
    ),
    report: Annotated[Path | None, typer.Option(help="Also copy the pipeline report here.")] = None,
) -> None:
    """Run the whole free pipeline on the sample documents and build the demo viewer."""
    with tempfile.TemporaryDirectory() as tmp:
        ws = Workspace(source, Path(tmp))
        inv = pipeline.run_inventory(ws, Curation())
        pipeline.run_extract(ws, inv)
        pipeline.run_split(ws, inv, Curation())
        pipeline.run_structure(ws, inv)
        result = pipeline.build_catalog(ws, inv, Curation())
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(viewer.render(result, "recipify demo"), encoding="utf-8")
        if report:
            report.parent.mkdir(parents=True, exist_ok=True)
            report.write_text(ws.report_path.read_text("utf-8"), encoding="utf-8")
    _print_summary(result, inv)
    console.print(f"Wrote {out}")


@app.command()
def lock(
    source: Annotated[Path, typer.Argument(help="Viewer page to encrypt.")] = Path(
        "dist/index.html"
    ),
    out: Annotated[Path, typer.Option(help="Locked page, ready to publish.")] = Path(
        "site/index.html"
    ),
    verify: Annotated[bool, typer.Option(help="Only check that OUT opens with the key.")] = False,
    show_link: Annotated[bool, typer.Option(help="Print the share link with the key.")] = False,
    base_url: Annotated[
        str, typer.Option(envvar="RECIPIFY_BASE_URL", help="Where OUT is published.")
    ] = "",
) -> None:
    """Encrypt the viewer with ENCRYPTION_KEY (env or .env) for publishing on GitHub Pages."""
    load_dotenv()
    key = os.environ.get("ENCRYPTION_KEY", "")
    if not key:
        raise typer.BadParameter("ENCRYPTION_KEY is not set (environment or .env)")
    if verify:
        try:
            locking.decrypt_page(out.read_text(encoding="utf-8"), key)
        except Exception as e:
            console.print(f"[red]{out} does not open with ENCRYPTION_KEY[/red] ({e!r})")
            raise typer.Exit(1) from e
        console.print(f"{out} opens with ENCRYPTION_KEY")
        return
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(locking.encrypt_page(source.read_text(encoding="utf-8"), key), encoding="utf-8")
    console.print(f"Wrote {out} ({out.stat().st_size // 1024} KB) from {source}")
    link = (base_url or "<where you publish it>") + "#key="
    link += quote(key, safe="") if show_link else "<ENCRYPTION_KEY>"
    console.print(f"Share link: {link}", highlight=False, soft_wrap=True)
