from pathlib import Path

from pypdf import PdfReader


def pdf_to_markdown(path: Path) -> str:
    reader = PdfReader(path)
    if reader.is_encrypted:
        reader.decrypt("")
    pages = [(p.extract_text() or "").strip() for p in reader.pages]
    multi = len(pages) > 1
    parts = [f"## Page {i}\n\n{t}" if multi else t for i, t in enumerate(pages, 1) if t]
    return f"# {path.stem}\n\n" + "\n\n".join(parts) + "\n"
