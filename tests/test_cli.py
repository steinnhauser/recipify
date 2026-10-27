import json
import shutil
from pathlib import Path

import pytest
from typer.testing import CliRunner

from recipify import cli
from recipify.lock import decrypt_page

runner = CliRunner()
EXAMPLES = Path(__file__).parent.parent / "examples" / "sources"


def invoke(*args: str) -> str:
    result = runner.invoke(cli.app, list(args))
    assert result.exit_code == 0, result.output
    return result.output


def fails(*args: str) -> str:
    result = runner.invoke(cli.app, list(args))
    assert result.exit_code != 0
    return result.output


@pytest.fixture
def workdir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, ws) -> Path:
    monkeypatch.chdir(tmp_path)
    return tmp_path


def test_stage_by_stage(workdir: Path):
    assert "5 files, 4 unique" in invoke("inventory")
    assert "2 extracted" in invoke("extract")
    assert "2 decided" in invoke("split")
    assert "2 cached" in invoke("split")
    assert "2 structured" in invoke("structure")
    out = invoke("catalog")
    assert "readable_pdfs" in out and "book (1)" in out
    out = invoke("show", "Bakarí/Tartdeig.pdf")
    assert "tier: ready" in out and '"title": "Tartdeig"' in out
    assert "tier: excluded" in invoke("show", "Handbook.pdf")
    assert "not in the catalog" in fails("show", "nope.pdf")
    out = invoke("trace", "Bakarí/Tartdeig.pdf")
    assert "✓ source" in out and "pages@v2: whole: one page" in out
    assert "1 recipes" in invoke("build", "--out", "out/index.html")
    assert 'data-editable=""' in (workdir / "out/index.html").read_text()
    invoke("build", "--out", "out/edit.html", "--editable")
    assert 'data-editable="1"' in (workdir / "out/edit.html").read_text()
    assert (workdir / "out/index.html").is_file()


def test_run_and_errors(workdir: Path):
    assert "Report:" in invoke("run")
    assert "1 structured" in invoke("structure", "--force", "--limit", "1")
    assert "not a directory" in str(
        runner.invoke(cli.app, ["--sources", "missing", "run"]).exception
    )


def test_pages(workdir: Path):
    out = invoke("pages", "Handbook.pdf", "--out", "pages", "--dpi", "20")
    assert "pages/Handbook-01.jpg" in out and "recipify register Handbook.pdf" in out
    assert "pages/photo.jpg" in invoke("pages", "photo.jpg", "--out", "pages")
    assert "not found" in fails("pages", "nope.pdf")


def test_run_reports_failures(workdir: Path, monkeypatch: pytest.MonkeyPatch):
    from recipify.categories import Category
    from recipify.extract import LOCAL, Engine

    def broken(path: Path):
        raise ValueError("unreadable")

    monkeypatch.setitem(LOCAL, Category.DOCX_FILES, Engine("broken", 1, broken))
    assert "failed Eftirréttir/Skyrkaka.docx: ValueError: unreadable" in invoke("run")


def test_register(workdir: Path):
    invoke("inventory")
    (workdir / "t.md").write_text("Rauðrófur\n4 rauðrófur\n2 msk hunang\nAðferð:\nBakað.", "utf-8")
    assert "vision@v1.json" in invoke(
        "register", "photo.jpg", "--text", "t.md", "--engine", "vision"
    )
    assert "not in the inventory" in fails("register", "nope.jpg", "--text", "t.md")
    invoke("run")
    data = json.loads((workdir / "data/catalog.json").read_text())
    photo = next(e for e in data["entries"] if e["source"] == "photo.jpg")
    assert photo["assessment"]["tier"] == "review"
    assert photo["transcribed"] and photo["accuracy"] is None


def test_transcriptions_least_certain_first(workdir: Path):
    invoke("inventory")
    (workdir / "t.md").write_text("Rauðrófur\n4 rauðrófur | 2 stk\nAðferð:\nBakað.", "utf-8")
    invoke("register", "photo.jpg", "--text", "t.md", "--engine", "vision", "--accuracy", "0.8")
    out = invoke("transcriptions", "--out", "t.md")  # before a catalog: no titles yet
    assert "80%" in out and "photo.jpg" in out and "1 transcription(s)" in out
    invoke("run")
    invoke("transcriptions", "--out", "list.md")
    table = (workdir / "list.md").read_text("utf-8").splitlines()
    assert table[2] == "| Certainty | Source | Recipes | Tier | Engine | Notes |"
    assert table[4] == "| 80% | photo.jpg | Rauðrófur | review | vision@v1 |  |"
    assert "0 transcription(s)" in invoke("transcriptions", "--below", "0.8")


def test_demo(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.chdir(tmp_path)
    shutil.copytree(EXAMPLES, tmp_path / "examples/sources")
    out = invoke("demo", "--report", "site/report.md")
    assert "Wrote site/demo/index.html" in out
    assert 'data-editable="1"' in (tmp_path / "site/demo/index.html").read_text()
    out = invoke("starter", "mine.html", "--limit", "1", "--title", "Mínar uppskriftir")
    assert "(1 recipes)" in out
    starter = (tmp_path / "mine.html").read_text()
    assert "<title>Mínar uppskriftir</title>" in starter and 'data-editable="1"' in starter
    report = (tmp_path / "site/report.md").read_text()
    assert "15 recipes ready" in report and "Split documents: 1 into 2 recipes" in report


def test_lock(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(cli, "load_dotenv", lambda: None)  # never read the developer's .env
    monkeypatch.delenv("ENCRYPTION_KEY", raising=False)
    (tmp_path / "viewer.html").write_text("<p>Plokkfiskur</p>", encoding="utf-8")
    assert "ENCRYPTION_KEY is not set" in fails("lock", "viewer.html")
    monkeypatch.setenv("ENCRYPTION_KEY", "pass word/1")
    out = invoke("lock", "viewer.html", "--out", "site/index.html")
    assert "#key=<ENCRYPTION_KEY>" in out
    locked = (tmp_path / "site/index.html").read_text(encoding="utf-8")
    assert (
        "Plokkfiskur" not in locked and decrypt_page(locked, "pass word/1") == "<p>Plokkfiskur</p>"
    )
    out = invoke("lock", "viewer.html", "--show-link", "--base-url", "https://example.org/")
    assert "https://example.org/#key=pass%20word%2F1" in out
    assert "opens with ENCRYPTION_KEY" in invoke("lock", "--verify")
    monkeypatch.setenv("ENCRYPTION_KEY", "other")
    assert "does not open" in fails("lock", "--verify")


def test_ambiguous_reference(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.chdir(tmp_path)
    shutil.copytree(EXAMPLES / "Bakery", tmp_path / "my files")  # any folder, as dropped
    out = invoke("run", "my files", "--title", "Bakery")
    assert "Viewer: dist/index.html (3 recipes)" in out
    assert "<title>Bakery</title>" in (tmp_path / "dist/index.html").read_text()
    assert "Viewer" not in invoke("run", "my files", "--no-build")
    out = fails("trace", "Kökur - uppskriftir.pdf")
    assert "holds 2 recipes" in out and "Kökur - uppskriftir.pdf#2" in out
    out = invoke("trace", "Kökur - uppskriftir.pdf#2")
    assert "✓ unit" in out and "✓ source" in out  # found where it was scanned
