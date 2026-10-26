"""Spreadsheets and legacy office documents, converted locally (LibreOffice for old formats)."""

import shutil
import subprocess
import tempfile
from pathlib import Path

from openpyxl import load_workbook

from recipify.extract.docx import extract_docx
from recipify.extract.pdf import extract_pdf

SPREADSHEET_ENGINE, SPREADSHEET_VERSION = "openpyxl", 1
LEGACY_ENGINE, LEGACY_VERSION = "libreoffice", 2
MAX_ROWS = 2000


def _soffice(path: Path, target: str, outdir: Path) -> Path:
    exe = shutil.which("soffice") or shutil.which("libreoffice")
    if not exe:
        raise RuntimeError("LibreOffice (soffice) is required to convert this format")
    with tempfile.TemporaryDirectory() as profile:
        subprocess.run(
            [
                exe,
                f"-env:UserInstallation=file://{profile}",
                "--headless",
                "--convert-to",
                target,
                "--outdir",
                str(outdir),
                str(path),
            ],
            check=True,
            capture_output=True,
            timeout=180,
        )
    out = outdir / f"{path.stem}.{target}"
    if not out.exists():
        raise RuntimeError(f"LibreOffice produced no {target} output")
    return out


def _cell(value: object) -> str:
    if value is None:
        return ""
    if isinstance(value, float) and value.is_integer():
        value = int(value)
    elif isinstance(value, float):
        value = round(value, 4)
    return str(value).strip().replace("\n", " ").replace("|", "/")


def _xlsx(path: Path, title: str) -> str:
    wb = load_workbook(path, read_only=True, data_only=True)
    blocks = [f"# {title}"]
    for ws in wb.worksheets:
        rows = [[_cell(c) for c in row] for row in ws.iter_rows(values_only=True, max_row=MAX_ROWS)]
        lines = [" | ".join(c for c in r if c) for r in rows]
        lines = [line for line in lines if line]
        if lines:
            blocks.append(f"## {ws.title}\n\n" + "\n".join(lines))
    wb.close()
    return "\n\n".join(blocks) + "\n"


def extract_spreadsheet(path: Path) -> str:
    if path.suffix.lower() in {".xlsx", ".xlsm"}:
        return _xlsx(path, path.stem)
    with tempfile.TemporaryDirectory() as tmp:
        return _xlsx(_soffice(path, "xlsx", Path(tmp)), path.stem)


def extract_legacy(path: Path) -> str:
    with tempfile.TemporaryDirectory() as tmp:
        if path.suffix.lower() in {".ppt", ".pptx", ".odp"}:
            return extract_pdf(_soffice(path, "pdf", Path(tmp)))[0]
        return extract_docx(_soffice(path, "docx", Path(tmp)))
