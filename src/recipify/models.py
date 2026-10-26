"""Typed records passed between pipeline stages and stored as JSON artifacts."""

from datetime import UTC, datetime
from enum import StrEnum

from pydantic import BaseModel, Field

from recipify.categories import Category


def now_iso() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


class Kind(StrEnum):
    RECIPE = "recipe"  # one recipe (possibly several components) per document
    BOOK = "book"  # cookbooks, binders and long collections: kept for later
    REFERENCE = "reference"  # mise en place lists, menus, staff lists, plans
    PHOTO = "photo"  # a picture of a plated dish, not of a recipe


class Tier(StrEnum):
    READY = "ready"  # verified against the source and published
    REVIEW = "review"  # converted, but a check failed: needs a person or a better engine
    EXCLUDED = "excluded"  # not a recipe, a duplicate, or not converted yet


# --- stage 1: inventory ------------------------------------------------------------------


class SourceFile(BaseModel):
    path: str  # relative to the sources directory
    sha256: str
    size: int
    mtime: float
    category: Category
    reason: str  # why the classifier chose the category
    pages: int | None = None
    kind: Kind = Kind.RECIPE
    duplicate_of: str | None = None  # canonical path when the bytes are identical


class Inventory(BaseModel):
    created_at: str = Field(default_factory=now_iso)
    files: dict[str, SourceFile] = {}

    def canonical(self) -> list[SourceFile]:
        return [f for f in self.files.values() if f.duplicate_of is None]


# --- stage 2: extraction ------------------------------------------------------------------


class Extraction(BaseModel):
    """Plain text of one source document, with light markdown hints (#, -, 1., |)."""

    sha256: str
    engine: str
    version: int
    created_at: str = Field(default_factory=now_iso)
    text: str
    costly: bool = False  # transcribed by hand or by a vision model: never overwritten
    checks: dict[str, float] = {}  # e.g. reading-order agreement between two extractors
    accuracy: float | None = None  # stated accuracy of a manual or vision transcription
    notes: str = ""


# --- stage 3: structure -------------------------------------------------------------------


class Ingredient(BaseModel):
    text: str  # the line exactly as it appears in the source
    amount: float | None = None  # parsed quantity, used for scaling
    amount_max: float | None = None  # upper end of a range ("2-3 tsk")
    quantity: str = ""  # the quantity as written ("1,5", "½", "2-3")
    unit: str = ""
    name: str = ""


class Section(BaseModel):
    """One component of a dish (a sauce, a crumble, a dough...)."""

    name: str = ""
    ingredients_label: str = ""  # the source's own label, e.g. "Hráefni"
    ingredients: list[Ingredient] = []
    method_label: str = ""  # e.g. "Aðferð:"
    steps: list[str] = []
    notes: list[str] = []


class Recipe(BaseModel):
    title: str
    title_in_text: bool = True  # False when the document has no title line (named after its file)
    intro: list[str] = []
    sections: list[Section] = []
    dropped: list[str] = []  # source lines left out on purpose (repeated titles, step numbers)

    def ingredient_count(self) -> int:
        return sum(len(s.ingredients) for s in self.sections)

    def step_count(self) -> int:
        return sum(len(s.steps) for s in self.sections)

    def lines(self) -> list[str]:
        """Every piece of the document's text the reader sees, in display order."""
        out = [self.title] if self.title_in_text else []
        out += self.intro
        for s in self.sections:
            out += [s.name, s.ingredients_label, *(i.text for i in s.ingredients)]
            out += [s.method_label, *s.steps, *s.notes]
        return [line for line in out if line]


class Structured(BaseModel):
    sha256: str
    engine: str
    version: int
    extraction: str  # "<engine>@v<version>" of the input text
    created_at: str = Field(default_factory=now_iso)
    recipe: Recipe


# --- stage 4: assessment and catalog ------------------------------------------------------


class Assessment(BaseModel):
    tier: Tier
    reasons: list[str] = []
    fidelity: float | None = None  # share of source words found in the recipe (1.0 = all)
    precision: float | None = None  # share of recipe words found in the source (1.0 = none added)
    order_agreement: float | None = None
    text_quality: float | None = None
    language: str = ""
    words: int = 0


class Entry(BaseModel):
    id: str  # stable: first 12 hex digits of the source's sha256
    source: str
    category: Category
    kind: Kind
    pages: int | None = None
    duplicates: list[str] = []
    extraction: str = ""
    structure: str = ""
    title: str = ""
    labels: dict[str, list[str]] = {}
    assessment: Assessment
    recipe: Recipe | None = None


class Catalog(BaseModel):
    created_at: str = Field(default_factory=now_iso)
    entries: list[Entry] = []

    def by_tier(self, tier: Tier) -> list[Entry]:
        return [e for e in self.entries if e.assessment.tier == tier]
