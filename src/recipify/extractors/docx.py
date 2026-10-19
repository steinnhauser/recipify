from pathlib import Path

from docx import Document
from docx.table import Table
from docx.text.paragraph import Paragraph


def _paragraph(p: Paragraph) -> str:
    text = p.text.strip()
    if not text:
        return ""
    style = (p.style.name if p.style is not None else "") or ""
    if style.startswith("Heading"):
        level = style.removeprefix("Heading ").strip()
        return f"{'#' * (int(level) if level.isdigit() else 1)} {text}"
    if style == "Title":
        return f"# {text}"
    if "List" in style:
        return f"- {text}"
    return text


def _cell(text: str) -> str:
    return text.strip().replace("\n", " ").replace("|", "\\|")


def _table(t: Table) -> str:
    rows = [[_cell(c.text) for c in r.cells] for r in t.rows]
    if not rows:
        return ""
    lines = ["| " + " | ".join(rows[0]) + " |", "|" + " --- |" * len(rows[0])]
    lines += ["| " + " | ".join(r) + " |" for r in rows[1:]]
    return "\n".join(lines)


def docx_to_markdown(path: Path) -> str:
    doc = Document(str(path))
    blocks = []
    for child in doc.element.body.iterchildren():
        if child.tag.endswith("}p"):
            blocks.append(_paragraph(Paragraph(child, doc)))
        elif child.tag.endswith("}tbl"):
            blocks.append(_table(Table(child, doc)))
    return "\n\n".join(b for b in blocks if b) + "\n"
