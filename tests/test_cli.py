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
    assert "2 structured" in invoke("structure")
    out = invoke("catalog")
    assert "readable_pdfs" in out and "book (1)" in out
    out = invoke("show", "Bakarí/Tartdeig.pdf")
    assert "tier: ready" in out and '"title": "Tartdeig"' in out
    assert "tier: excluded" in invoke("show", "Handbook.pdf")
    assert "not in the catalog" in fails("show", "nope.pdf")
    assert "1 recipes" in invoke("build", "--out", "out/index.html")
    assert (workdir / "out/index.html").is_file()


def test_run_review_only_and_errors(workdir: Path):
    assert "Report:" in invoke("run")
    out = invoke("structure", "--review-only", "--force")
    assert "1 structured" in out  # only the docx is in review (too short)
    assert "unknown engine" in fails("structure", "--engine", "nope")
    assert "not a directory" in str(
        runner.invoke(cli.app, ["--sources", "missing", "run"]).exception
    )


def test_run_reports_failures(workdir: Path, monkeypatch: pytest.MonkeyPatch):
    from recipify.categories import Category
    from recipify.extract import LOCAL, Engine

    def broken(path: Path):
        raise ValueError("unreadable")

    monkeypatch.setitem(LOCAL, Category.DOCX_FILES, Engine("broken", 1, broken))
    assert "failed Eftirréttir/Skyrkaka.docx: ValueError: unreadable" in invoke("run")


def test_structure_reports_usage(workdir: Path, monkeypatch: pytest.MonkeyPatch):
    from recipify.models import Recipe
    from recipify.structure import STRUCTURERS, Structurer

    invoke("run")
    fake = Structurer("fake", 1, lambda t, n: (Recipe(title=n), {"prompt_tokens": 5}), costly=True)
    monkeypatch.setitem(STRUCTURERS, "fake", fake)
    assert "API usage: {'prompt_tokens': 10}" in invoke("structure", "--engine", "fake")


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


def test_demo(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.chdir(tmp_path)
    shutil.copytree(EXAMPLES, tmp_path / "examples/sources")
    out = invoke("demo", "--report", "site/report.md")
    assert "Wrote site/demo/index.html" in out
    assert "13 recipes ready" in (tmp_path / "site/report.md").read_text()


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
