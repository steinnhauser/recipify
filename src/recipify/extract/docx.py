"""Word documents, read from the XML in document order.

python-docx's convenience API skips text boxes (common in recipe templates) and repeats
merged table cells, so this walks the body directly:

- text boxes are read where they are anchored; Word's legacy duplicate (``mc:Fallback``)
  is skipped, so their text appears once;
- soft line breaks stay line breaks, so ingredient lists keep one ingredient per line;
- explicit page breaks (not the ones Word adds while laying out text) become a form feed
  line, so the split stage can see where the author started a new page;
- headings become ``# ...`` and list items ``- ...``;
- a table whose cells each hold one line is read row by row ("600 g | cod"); a layout
  table with whole paragraphs in its cells is read cell by cell.
"""

from collections.abc import Iterator
from pathlib import Path

from docx import Document
from docx.text.paragraph import Paragraph
from lxml.etree import _Element

ENGINE, VERSION = "python-docx", 3
PAGE_BREAK = "\f"  # explicit page breaks become a line of their own, as between PDF pages

W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
MC_FALLBACK = "{http://schemas.openxmlformats.org/markup-compatibility/2006}Fallback"


class _Reader:
    def __init__(self, path: Path):
        self.doc = Document(str(path))

    def blocks(self, container: _Element) -> Iterator[str]:
        for child in container:
            if child.tag == f"{W}p":
                yield from self._paragraph(child)
            elif child.tag == f"{W}tbl":
                yield from self._table(child)
            elif child.tag == f"{W}sdt":  # content controls wrap ordinary blocks
                content = child.find(f"{W}sdtContent")
                if content is not None:
                    yield from self.blocks(content)

    def _runs(self, el: _Element, out: list[str], boxes: list[_Element]) -> None:
        for child in el:
            tag = child.tag
            if tag == MC_FALLBACK:
                continue
            if tag == f"{W}txbxContent":
                boxes.append(child)
            elif tag == f"{W}t":
                out.append(child.text or "")
            elif tag == f"{W}br" and child.get(f"{W}type") == "page":
                out.append(f"\n{PAGE_BREAK}\n")
            elif tag in (f"{W}br", f"{W}cr"):
                out.append("\n")
            elif tag == f"{W}tab":
                out.append(" ")
            else:
                self._runs(child, out, boxes)

    def _paragraph(self, p: _Element) -> Iterator[str]:
        parts: list[str] = []
        boxes: list[_Element] = []
        if p.find(f"{W}pPr/{W}pageBreakBefore") is not None:
            parts.append(f"{PAGE_BREAK}\n")
        self._runs(p, parts, boxes)
        lines = [line.strip(" \t\r\n") for line in "".join(parts).split("\n")]
        lines = [line for line in lines if line]
        text = [i for i, line in enumerate(lines) if line != PAGE_BREAK]
        if text:
            style = Paragraph(p, self.doc).style  # type: ignore[arg-type]  # p is a CT_P
            name = (style.name if style is not None else "") or ""
            if name.startswith("Heading") or name == "Title":
                level = name.removeprefix("Heading").strip()
                first = text[0]
                lines[first] = "#" * (int(level) if level.isdigit() else 1) + " " + lines[first]
            elif "List" in name or p.find(f"{W}pPr/{W}numPr") is not None:
                lines = [line if line == PAGE_BREAK else f"- {line}" for line in lines]
        if lines:
            yield "\n".join(lines)
        for box in boxes:
            yield from self.blocks(box)

    def _cell_blocks(self, tc: _Element) -> list[str]:
        return [b for b in self.blocks(tc) if b.strip()]

    def _table(self, tbl: _Element) -> Iterator[str]:
        rows = [
            [self._cell_blocks(tc) for tc in tr.findall(f"{W}tc")] for tr in tbl.findall(f"{W}tr")
        ]
        one_line = all(len(cell) <= 1 and "\n" not in "".join(cell) for r in rows for cell in r)
        if one_line:
            lines = [" | ".join(c[0] for c in row if c) for row in rows]
            text = "\n".join(line for line in lines if line)
            if text:
                yield text
            return
        for row in rows:
            for cell in row:
                yield from cell


def extract_docx(path: Path) -> str:
    reader = _Reader(path)
    return "\n\n".join(reader.blocks(reader.doc.element.body)) + "\n"
