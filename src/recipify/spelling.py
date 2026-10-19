"""Conservative whole-word spelling fixes from a reviewed list (``spelling.json``).

Only unambiguous non-words are listed (found by comparing rare words with very frequent
near-identical ones in the corpus, then reviewed by hand). Original files and the raw
transcriptions are never touched; fixes only appear in new output versions.
"""

import json
import re
from pathlib import Path

WORD = re.compile(r"[^\W\d_]+")


def load_spelling(path: Path) -> dict[str, str]:
    return json.loads(path.read_text(encoding="utf-8")) if path.is_file() else {}


def _match_case(old: str, new: str) -> str:
    if old.isupper() and len(old) > 1:
        return new.upper()
    return new[:1].upper() + new[1:] if old[:1].isupper() else new


def fix_spelling(text: str, fixes: dict[str, str]) -> tuple[str, int]:
    count = 0

    def repl(m: re.Match[str]) -> str:
        nonlocal count
        new = fixes.get(m.group(0).lower())
        if new is None:
            return m.group(0)
        count += 1
        return _match_case(m.group(0), new)

    return WORD.sub(repl, text), count
