"""Manual overrides, kept outside the code: ``curation.json`` in the data directory.

Keys are source file stems (the file name without extension)::

    {"titles": {"IMG_0042": "Recipe notebook I"},
     "labels": {"desserts": {"course": ["dessert"]}},
     "kind": {"Missi": "reference"},
     "tier": {"Pylsubrauð": "review"},
     "keep_whole": ["Sósur og soð"],
     "vocabulary": {"collection_names": ["recettes"]}}
"""

from pathlib import Path

from pydantic import BaseModel

from recipify.models import Kind, Tier
from recipify.vocabulary import Vocabulary


class Curation(BaseModel):
    titles: dict[str, str] = {}
    labels: dict[str, dict[str, list[str]]] = {}
    kind: dict[str, Kind] = {}
    tier: dict[str, Tier] = {}  # force a tier after review (e.g. keep a recipe out)
    keep_whole: list[str] = []  # documents the split stage must not split
    vocabulary: Vocabulary = Vocabulary()  # words added to the defaults (see vocabulary.py)

    @classmethod
    def load(cls, path: Path) -> "Curation":
        if not path.is_file():
            return cls()
        return cls.model_validate_json(path.read_text(encoding="utf-8"))
