"""PDF text via poppler: content-stream order for reading, layout mode as a cross-check.

``pdftotext -raw`` keeps the order in which the document was written, so each component of
a multi-column recipe stays together, and keeps one line per printed line. ``-layout``
reproduces the page visually. If every raw line also appears in the layout text, the two
modes agree on how the text is cut into lines, which catches PDFs whose text is stored in
fragments that a reader would put together differently.
"""

import re
import shutil
import subprocess
from pathlib import Path

ENGINE, VERSION = "poppler", 2


def _poppler(tool: str, *args: str) -> str:
    exe = shutil.which(tool)
    if not exe:
        raise RuntimeError(f"{tool} not found: install poppler (e.g. apt install poppler-utils)")
    done = subprocess.run([exe, *args], capture_output=True, text=True, timeout=120)
    if done.returncode != 0:
        raise RuntimeError(f"{tool} failed: {done.stderr.strip() or done.returncode}")
    return done.stdout


def page_count(path: Path) -> int:
    info = _poppler("pdfinfo", str(path))
    match = re.search(r"^Pages:\s+(\d+)", info, re.M)
    return int(match.group(1)) if match else 0


def pdf_text(path: Path, mode: str = "raw", last_page: int | None = None) -> str:
    args = [f"-{mode}", "-enc", "UTF-8"]
    if last_page:
        args += ["-l", str(last_page)]
    return _poppler("pdftotext", *args, str(path), "-")


def _norm(line: str) -> str:
    return re.sub(r"\s+", " ", line).strip()


def order_agreement(raw: str, layout: str) -> float:
    """Share of raw lines that appear, whole, in the layout rendering of the same pages."""
    lines = [n for line in raw.splitlines() if (n := _norm(line))]
    if not lines:
        return 1.0
    page = "\n".join(_norm(line) for line in layout.splitlines())
    return round(sum(line in page for line in lines) / len(lines), 4)


def extract_pdf(path: Path) -> tuple[str, dict[str, float]]:
    raw = pdf_text(path, "raw")
    text = "\n\f\n".join(p.strip("\n") for p in raw.split("\f") if p.strip())  # \f: new page
    agreement = order_agreement(raw, pdf_text(path, "layout"))
    return text.strip() + "\n", {"order_agreement": agreement}


def render_pages(path: Path, out_dir: Path, dpi: int = 150) -> list[Path]:
    """Page images of a scanned PDF, for transcription (one JPEG per page)."""
    out_dir.mkdir(parents=True, exist_ok=True)
    _poppler("pdftoppm", "-r", str(dpi), "-jpeg", str(path), str(out_dir / path.stem))
    return sorted(out_dir.glob(f"{path.stem}-*.jpg"))
