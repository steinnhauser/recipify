"""Stage 3: turn extracted text into a structured recipe.

``rules`` is deterministic, local and free, and is the default. ``mistral-llm`` is an
opt-in fallback for layouts the rules cannot follow; both go through the same checks.
"""

from collections.abc import Callable
from dataclasses import dataclass

from recipify.models import Recipe
from recipify.structure import llm, rules

Result = tuple[Recipe, dict[str, int]]


@dataclass(frozen=True)
class Structurer:
    name: str
    version: int
    run: Callable[[str, str], Result]
    costly: bool = False

    @property
    def label(self) -> str:
        return f"{self.name}@v{self.version}"


RULES = Structurer(
    rules.ENGINE, rules.VERSION, lambda text, title: (rules.structure(text, title), {})
)
LLM = Structurer(llm.ENGINE, llm.VERSION, llm.structure, costly=True)
STRUCTURERS = {s.name: s for s in (RULES, LLM)}
