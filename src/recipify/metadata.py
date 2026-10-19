"""Central metadata.json: one entry per source file, with version history."""

import json
import os
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

SCHEMA_VERSION = 1


def now_iso() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def new_run_id() -> str:
    return datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")


class Metadata:
    """One metadata.json per output version (outputs/<run-id>/metadata.json).

    The newest run's file is the working state; every run writes a full snapshot, so
    older snapshots remain as history. Structure::

    {"schema_version": 1, "recipes": {"<source path relative to recipes dir>": {
        "source", "sha256", "size", "category", "classification_reason",
        "suggested_name", "slug", "original_format", "original_form", "language",
        "versions": [{"version", "run_id", "output", "processor", "created_at", "status",
        "error", "language", "quality": {"score", "method", "flags", "notes"}}],
        "recipe": {}   # reserved: ingredients, steps, prep time, ...
    }}, "runs": {"<run_id>": {"created_at", "note"}}}
    """

    def __init__(self, path: Path):
        self.path = path
        self.data: dict[str, Any] = {"schema_version": SCHEMA_VERSION, "recipes": {}, "runs": {}}
        if path.exists():
            self.data = json.loads(path.read_text(encoding="utf-8"))
            self.data.setdefault("runs", {})

    @classmethod
    def load_latest(cls, outputs_dir: Path) -> "Metadata":
        """Open the newest run's metadata.json (or an empty one if there is none)."""
        snapshots = sorted(outputs_dir.glob("*/metadata.json")) if outputs_dir.is_dir() else []
        return cls(snapshots[-1]) if snapshots else cls(outputs_dir / "_unsaved" / "metadata.json")

    @property
    def recipes(self) -> dict[str, dict[str, Any]]:
        recipes: dict[str, dict[str, Any]] = self.data["recipes"]
        return recipes

    def entry(self, key: str) -> dict[str, Any]:
        return self.recipes.setdefault(key, {"versions": [], "recipe": {}})

    def start_run(self, run_id: str, note: str = "") -> None:
        run = self.data["runs"].setdefault(run_id, {"created_at": now_iso(), "note": ""})
        if note:
            run["note"] = note

    def write_run(self, outputs_dir: Path, run_id: str) -> None:
        """Write the metadata snapshot and CHANGELOG.md into outputs_dir/run_id/."""
        from recipify.changelog import render_changelog

        run_dir = outputs_dir / run_id
        run_dir.mkdir(parents=True, exist_ok=True)
        self.path = run_dir / "metadata.json"
        self.save()
        (run_dir / "CHANGELOG.md").write_text(render_changelog(self, run_id), encoding="utf-8")

    def save(self) -> None:
        tmp = self.path.with_suffix(".json.tmp")
        tmp.write_text(
            json.dumps(self.data, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        os.replace(tmp, self.path)
