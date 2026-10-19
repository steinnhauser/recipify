"""EPUB cookbooks -> markdown using only the standard library."""

import posixpath
import re
import zipfile
from html.parser import HTMLParser
from pathlib import Path
from xml.etree import ElementTree as ET

BLOCK = {"p", "div", "li", "tr", "br", "section", "blockquote"}
HEADINGS = {f"h{i}": "#" * i for i in range(1, 7)}


class _Text(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self.skip = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in {"script", "style", "head"}:
            self.skip += 1
        elif tag in HEADINGS:
            self.parts.append(f"\n\n{HEADINGS[tag]} ")
        elif tag == "li":
            self.parts.append("\n- ")
        elif tag in BLOCK:
            self.parts.append("\n\n")

    def handle_endtag(self, tag: str) -> None:
        if tag in {"script", "style", "head"}:
            self.skip = max(0, self.skip - 1)
        elif tag in HEADINGS or tag in BLOCK:
            self.parts.append("\n")

    def handle_data(self, data: str) -> None:
        if not self.skip:
            self.parts.append(re.sub(r"\s+", " ", data))


def _html_to_text(html: str) -> str:
    parser = _Text()
    parser.feed(html)
    text = "".join(parser.parts)
    text = re.sub(r"[ \t]+\n", "\n", text)
    return re.sub(r"\n{3,}", "\n\n", text).strip()


def _spine(zf: zipfile.ZipFile) -> list[str]:
    container = ET.fromstring(zf.read("META-INF/container.xml"))
    rootfile = next(e for e in container.iter() if e.tag.endswith("rootfile"))
    opf_path = rootfile.attrib["full-path"]
    opf = ET.fromstring(zf.read(opf_path))
    manifest = {e.attrib["id"]: e.attrib["href"] for e in opf.iter() if e.tag.endswith("}item")}
    base = posixpath.dirname(opf_path)
    refs = [e.attrib["idref"] for e in opf.iter() if e.tag.endswith("}itemref")]
    return [posixpath.normpath(posixpath.join(base, manifest[r])) for r in refs if r in manifest]


def epub_to_markdown(path: Path) -> str:
    with zipfile.ZipFile(path) as zf:
        names = set(zf.namelist())
        pages = [n for n in _spine(zf) if n in names]
        blocks = [f"# {path.stem}"]
        for name in pages:
            text = _html_to_text(zf.read(name).decode("utf-8", errors="replace"))
            if text:
                blocks.append(text)
    return "\n\n".join(blocks) + "\n"
