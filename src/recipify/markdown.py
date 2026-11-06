"""Recipes written in markdown: the file is the recipe, so it goes straight to the catalog.

A document converted from a PDF or Word file has to be extracted, split, structured and
checked word for word. A recipe written in markdown needs none of that: its headings already
say what each line is. This reader turns one into a Recipe and its labels, close to the end
of the pipeline.

    ---
    course: main                  labels for the viewer's filters, comma separated
    cuisine: Italian              (course, dish, diet, cuisine, ingredients); any left out
    ingredients: rice, tomato     or empty are detected as for any other recipe
    status: draft                 a draft is shown, and says it is one
    ---
    # Tomato risotto
    Serves 4.                     intro lines
    ## Ingredients                (or ## <component name> for each component)
    - 300 g arborio rice          ingredients; quantities are parsed for scaling
    ## Method                     (or ### Method inside a component)
    1. Toast the rice.            steps; the viewer numbers them itself
    > Use a wide pan.             notes
"""

import re
from dataclasses import dataclass, field
from pathlib import Path

from recipify.labels import FACETS
from recipify.models import Ingredient, Recipe, Section
from recipify.structure.quantities import parse_ingredient

ENGINE, VERSION = "markdown", 1
SUFFIXES = {".md", ".markdown"}

INGREDIENT_HEADINGS = {"ingredients", "hráefni"}
METHOD_HEADINGS = {"method", "aðferð", "directions", "instructions", "steps"}
STEP = re.compile(r"^\d{1,2}[.)]\s*")
COMMENT = re.compile(r"<!--.*?-->", re.DOTALL)


@dataclass
class Written:
    recipe: Recipe
    labels: dict[str, list[str]] = field(default_factory=dict)
    draft: bool = False


def _front_matter(lines: list[str]) -> tuple[dict[str, str], list[str]]:
    if not lines or lines[0].strip() != "---" or "---" not in (x.strip() for x in lines[1:]):
        return {}, lines
    end = next(i for i, x in enumerate(lines[1:], 1) if x.strip() == "---")
    meta = {}
    for line in lines[1:end]:
        key, sep, value = line.partition(":")
        if sep:
            meta[key.strip().lower()] = re.sub(r"\s+#.*$", "", value).strip()
    return meta, lines[end + 1 :]


def _ingredient(line: str) -> Ingredient:
    return parse_ingredient(line) or Ingredient(text=line, name=line)


def parse(text: str, stem: str) -> Written:
    """The recipe in a markdown file; `stem` (the file name) titles one without a `# ` line."""
    meta, lines = _front_matter(COMMENT.sub("", text).splitlines())
    recipe = Recipe(title=stem, title_in_text=False)
    part, in_method = Section(), False

    def close() -> None:
        if part.name or part.ingredients or part.steps or part.notes:
            recipe.sections.append(part)

    for raw in lines:
        line = raw.strip()
        if not line:
            continue
        heading = re.match(r"^(#+)\s+(.*)$", line)
        if heading:
            level, name = len(heading.group(1)), heading.group(2).strip()
            key = name.rstrip(":").casefold()
            if level == 1 and not recipe.title_in_text:
                recipe.title, recipe.title_in_text = name, True
            elif key in INGREDIENT_HEADINGS:
                in_method = False
                if level > 2 or name != "Ingredients":  # the source's own label is kept
                    part.ingredients_label = name
            elif key in METHOD_HEADINGS:
                in_method = True
                if level > 2 or name != "Method":
                    part.method_label = name
            else:  # a component: a sauce, a crumble, a dough...
                close()
                part, in_method = Section(name=name), False
        elif line in ("-", "*"):  # an empty bullet, waiting to be filled in
            continue
        elif line.startswith(("- ", "* ")):
            part.ingredients.append(_ingredient(line[2:].strip()))
        elif line.startswith(">"):
            part.notes.append(line.lstrip("> ").strip())
        elif STEP.match(line) or in_method:
            step = STEP.sub("", line).strip()
            if step:
                part.steps.append(step)
        elif not (part.name or part.ingredients or part.steps or recipe.sections):
            recipe.intro.append(line)
        else:
            part.notes.append(line)
    close()
    labels = {f: [v.strip() for v in meta[f].split(",") if v.strip()] for f in FACETS if f in meta}
    labels = {f: v for f, v in labels.items() if v}
    return Written(recipe, labels, meta.get("status", "").casefold() == "draft")


def slug(title: str) -> str:
    """A file name for a title: lower case, letters (accents kept) and digits joined by "-"."""
    return re.sub(r"[\W_]+", "-", title.casefold().replace("'", "")).strip("-") or "recipe"


def template(title: str) -> str:
    """A new recipe to fill in: the labels to state, and the headings the reader expects."""
    labels = "".join(f"{f}:\n" for f in FACETS)
    body = f"# {title}\n\n## Ingredients\n\n- \n\n## Method\n\n1. \n"
    return f"---\n{labels}status: draft\n---\n\n{body}"


def read(path: Path) -> Written:
    return parse(path.read_text(encoding="utf-8"), path.stem)
