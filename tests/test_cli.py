import itertools
import json
import subprocess
from pathlib import Path

import pytest
from typer.testing import CliRunner

from recipify import cli
from recipify.lock import decrypt_page
from recipify.metadata import Metadata

runner = CliRunner()


def invoke(*args: str) -> str:
    result = runner.invoke(cli.app, list(args), env={"COLUMNS": "200"})
    assert result.exit_code == 0, result.output
    return result.output


def fails(*args: str) -> str:
    result = runner.invoke(cli.app, list(args), env={"COLUMNS": "200"})
    assert result.exit_code != 0
    return result.output


@pytest.fixture(autouse=True)
def run_ids(monkeypatch: pytest.MonkeyPatch) -> None:
    """Distinct run ids (real ones have one-second resolution, too coarse for tests)."""
    counter = itertools.count(1)
    new_run_id = lambda: f"run{next(counter):02d}"  # noqa: E731
    monkeypatch.setattr(cli, "new_run_id", new_run_id)
    monkeypatch.setattr(cli.pipeline, "new_run_id", new_run_id)


@pytest.fixture
def workdir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, make_docx) -> Path:
    """A project with two recipes and one corrupt file, using the CLI's default paths."""
    monkeypatch.chdir(tmp_path)
    (tmp_path / "recipes" / "Aðalréttir").mkdir(parents=True)
    make_docx(tmp_path / "recipes" / "Aðalréttir" / "Lamb Stew.docx", "Lamb stew\n\nlamb 500 g")
    make_docx(tmp_path / "recipes" / "Kaka.docx", "Súkkulaðikaka\n\n200 g smjór og sykur")
    (tmp_path / "recipes" / "broken.pdf").write_bytes(b"")
    return tmp_path


def test_classify_and_list(workdir: Path):
    out = invoke("classify")
    assert "docx_files" in out and "empty_or_corrupted" in out
    listed = invoke("classify", "--list", "docx_files", "--force")
    assert "Aðalréttir/Lamb Stew.docx" in listed and "broken.pdf" not in listed
    assert "is not a directory" in fails("classify", "--recipes", "missing")


def test_sort_and_rename(workdir: Path):
    assert "Copied 3 files" in invoke("sort")
    assert (workdir / "sorted" / "docx_files" / "lamb-stew.docx").is_file()
    assert "Copied 0 files" in invoke("sort")  # existing copies are kept
    assert (workdir / "recipes" / "Kaka.docx").is_file()  # originals untouched

    assert "2 suggested renames" in invoke("rename")
    assert (workdir / "recipes" / "Kaka.docx").is_file()  # nothing renamed yet
    subprocess.run(["sh", "rename_plan.sh"], check=True)  # the plan runs as written
    renamed = {
        p.relative_to(workdir / "recipes").as_posix() for p in workdir.rglob("recipes/**/*.*")
    }
    assert renamed == {"broken.pdf", "kaka.docx", "Aðalréttir/lamb-stew.docx"}


def test_full_pipeline(workdir: Path):
    out = invoke("process", "--note", "first import")
    assert "ok  Kaka.docx" in out and "complete" in out
    assert "Nothing to convert" in invoke("process")
    assert "Nothing to convert" in invoke("process", "-c", "readable_pdfs", "--reclassify")

    assert "complete" in invoke("enrich")
    assert "already up to date" in invoke("enrich")
    curation = workdir / "curation.json"
    curation.write_text(json.dumps({"titles": {"Kaka": "Chocolate cake"}}), encoding="utf-8")
    assert "complete" in invoke("enrich", "--curation", "curation.json")

    out = invoke("tidy")
    assert "complete" in out or "Nothing to tidy" in out
    assert "Nothing to tidy" in invoke("tidy")

    assert "No known typos" in invoke("spelling")
    (workdir / "spelling.json").write_text(json.dumps({"smjór": "smjör"}), encoding="utf-8")
    assert "complete" in invoke("spelling")

    assert "Wrote viewer/v001/recipes.html" in invoke("build", "--note", "first look")
    assert "first look" in (workdir / "viewer" / "v001" / "NOTES.md").read_text()

    meta = Metadata.load_latest(workdir / "outputs")
    assert meta.recipes["Kaka.docx"]["recipe"]["title"] == "Chocolate cake"


def test_process_reports_failures(workdir: Path, monkeypatch: pytest.MonkeyPatch):
    def broken(path: Path) -> str:
        raise ValueError("cannot read")

    monkeypatch.setitem(cli.pipeline.EXTRACTORS, cli.Category.DOCX_FILES, ("broken", broken))
    out = invoke("process")
    assert "failed ValueError: cannot read  Kaka.docx" in out


def test_register(workdir: Path):
    md = workdir / "kaka.md"
    md.write_text("# Kaka\n\nTranscribed by hand.\n", encoding="utf-8")
    out = invoke(
        "register", "Kaka.docx", "--markdown", "kaka.md", "--processor", "vision",
        "--accuracy", "0.95", "--notes", "checked", "--run-id", "r1", "--note", "manual",
    )  # fmt: skip
    assert "Stored r1/docx_files/kaka.md" in out
    version = Metadata.load_latest(workdir / "outputs").recipes["Kaka.docx"]["versions"][-1]
    assert version["quality"]["score"] == 0.95 and version["processor"] == "vision"

    assert "Stored" in invoke("register", "Kaka.docx", "--markdown", "kaka.md")
    assert "not a known source" in fails("register", "nope.docx", "--markdown", "kaka.md")


def test_demo(tmp_path: Path):
    recipes = tmp_path / "examples" / "dessert"
    recipes.mkdir(parents=True)
    (recipes / "skyr.md").write_text("# Skyr cake\n\nWhisk skyr with sugar.\n", encoding="utf-8")
    (recipes / "plain.md").write_text("No heading here.\n", encoding="utf-8")
    out = tmp_path / "site" / "demo" / "index.html"
    assert "Wrote" in invoke("demo", "--source", str(tmp_path / "examples"), "--out", str(out))
    page = out.read_text(encoding="utf-8")
    assert "Skyr cake" in page and "Whisk skyr with sugar." in page and "plain" in page


def test_lock(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(cli, "load_dotenv", lambda: None)  # never read the developer's .env
    monkeypatch.delenv("ENCRYPTION_KEY", raising=False)
    (tmp_path / "viewer.html").write_text("<p>Kjötsúpa</p>", encoding="utf-8")
    assert "ENCRYPTION_KEY is not set" in fails("lock", "viewer.html")

    monkeypatch.setenv("ENCRYPTION_KEY", "pass word/1")
    out = invoke("lock", "viewer.html", "--out", "site/index.html")
    assert "#key=<ENCRYPTION_KEY>" in out
    assert decrypt_page((tmp_path / "site/index.html").read_text(), "pass word/1") == (
        "<p>Kjötsúpa</p>"
    )
    out = invoke("lock", "viewer.html", "--show-link", "--base-url", "https://example.org/")
    assert "https://example.org/#key=pass%20word%2F1" in out
    assert "opens with ENCRYPTION_KEY" in invoke("lock", "--verify")

    monkeypatch.setenv("ENCRYPTION_KEY", "other")
    assert "does not open" in fails("lock", "--verify")
