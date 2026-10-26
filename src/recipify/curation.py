"""Manual overrides, kept outside the code: ``curation.json`` in the data directory.

Keys are source file stems (the file name without extension)::

    {"titles": {"20160322193052190": "Lava recipe notebook I"},
     "labels": {"aggi desert": {"course": ["dessert"]}},
     "kind": {"Missi Lava": "reference"},
     "tier": {"Pylsubrauð": "review"}}
"""

from pathlib import Path

from pydantic import BaseModel

from recipify.models import Kind, Tier


class Curation(BaseModel):
    titles: dict[str, str] = {}
    labels: dict[str, dict[str, list[str]]] = {}
    kind: dict[str, Kind] = {}
    tier: dict[str, Tier] = {}  # force a tier after review (e.g. keep a recipe out)

    @classmethod
    def load(cls, path: Path) -> "Curation":
        if not path.is_file():
            return cls()
        return cls.model_validate_json(path.read_text(encoding="utf-8"))
