"""The pipeline workspace: every stage's output is a JSON artifact on disk.

Layout of the data directory::

    inventory.json                      stage 1: every source file, hashed and classified
    extractions/<sha256>/<engine>@v<N>.json   stage 2: text per document and extractor version
    recipes/<sha256>/<engine>@v<N>.json       stage 3: structured recipe per structurer version
    catalog.json, report.md             stage 4: assessed recipes and the human-readable summary
    runs.jsonl                          append-only log of every stage run

Artifacts are keyed by the source's content hash, so duplicates share work, renamed files
keep their results, and a new engine version writes a new file next to the old one.
"""

import json
import os
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from pydantic import BaseModel

from recipify.models import Catalog, Extraction, Inventory, Structured


def write_json(path: Path, data: BaseModel | dict[str, Any]) -> None:
    """Atomic write: a crash never leaves a half-written artifact behind."""
    path.parent.mkdir(parents=True, exist_ok=True)
    text = (
        data.model_dump_json(indent=2)
        if isinstance(data, BaseModel)
        else json.dumps(data, ensure_ascii=False, indent=2)
    )
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(text + "\n", encoding="utf-8")
    os.replace(tmp, path)


@dataclass(frozen=True)
class Workspace:
    sources: Path
    data: Path

    @property
    def inventory_path(self) -> Path:
        return self.data / "inventory.json"

    @property
    def catalog_path(self) -> Path:
        return self.data / "catalog.json"

    @property
    def report_path(self) -> Path:
        return self.data / "report.md"

    def load_inventory(self) -> Inventory:
        if not self.inventory_path.is_file():
            return Inventory()
        return Inventory.model_validate_json(self.inventory_path.read_text(encoding="utf-8"))

    def load_catalog(self) -> Catalog:
        if not self.catalog_path.is_file():
            raise FileNotFoundError(f"{self.catalog_path} not found: run `recipify catalog` first")
        return Catalog.model_validate_json(self.catalog_path.read_text(encoding="utf-8"))

    # -- versioned artifacts ---------------------------------------------------------------

    def extraction_path(self, sha256: str, engine: str, version: int) -> Path:
        return self.data / "extractions" / sha256 / f"{engine}@v{version}.json"

    def structured_path(self, sha256: str, engine: str, version: int) -> Path:
        return self.data / "recipes" / sha256 / f"{engine}@v{version}.json"

    def has_extraction(self, sha256: str) -> bool:
        return any((self.data / "extractions" / sha256).glob("*.json"))

    def extractions(self, sha256: str) -> Iterator[Extraction]:
        """All stored extractions of a document, newest first."""
        found = [
            Extraction.model_validate_json(p.read_text(encoding="utf-8"))
            for p in (self.data / "extractions" / sha256).glob("*.json")
        ]
        yield from sorted(found, key=lambda e: e.created_at, reverse=True)

    def structured(self, sha256: str) -> Iterator[Structured]:
        found = [
            Structured.model_validate_json(p.read_text(encoding="utf-8"))
            for p in (self.data / "recipes" / sha256).glob("*.json")
        ]
        yield from sorted(found, key=lambda s: s.created_at, reverse=True)

    def log_run(self, record: dict[str, Any]) -> None:
        self.data.mkdir(parents=True, exist_ok=True)
        with (self.data / "runs.jsonl").open("a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")
