"""LLM structurer (Mistral, JSON-schema output) for documents the rules cannot read.

The model only arranges text; it is told to copy every line verbatim. Its output is not
trusted: the assessment stage counts every word and number against the source, so any
paraphrase, correction or invented quantity sends the recipe to review instead of the app.
"""

from collections import Counter

from pydantic import BaseModel, ConfigDict

from recipify.models import Ingredient, Recipe, Section
from recipify.structure.quantities import parse_ingredient
from recipify.text import tokens

ENGINE, VERSION = "mistral-llm", 1
MODEL = "mistral-small-latest"

SYSTEM = """\
You turn the text of one recipe document from a professional kitchen into JSON.
Rules:
- Copy text exactly as written, character for character: keep spelling mistakes, units,
  abbreviations and punctuation. Never translate, correct, reword, summarise or add text.
- Every line of the input appears exactly once in the output. If a sentence was wrapped
  over several lines, join the lines with one space.
- A component (a sauce, a dough, a garnish...) has a name, a list of ingredients (one line
  each) and method steps. Keep the document's own labels, such as "Aðferð:" or "Hráefni",
  in method_label and ingredients_label.
- Lines that are neither ingredients nor steps (storage time, serving notes) go in notes.
  Text before the first component goes in intro. The title is the document's heading.
"""


class _Section(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str
    ingredients_label: str
    ingredients: list[str]
    method_label: str
    steps: list[str]
    notes: list[str]


class _Recipe(BaseModel):
    model_config = ConfigDict(extra="forbid")
    title: str
    intro: list[str]
    sections: list[_Section]


def _ingredient(line: str) -> Ingredient:
    return parse_ingredient(line) or Ingredient(text=line, name=line)


def to_recipe(raw: _Recipe) -> Recipe:
    return Recipe(
        title=raw.title,
        intro=raw.intro,
        sections=[
            Section(
                name=s.name,
                ingredients_label=s.ingredients_label,
                ingredients=[_ingredient(i) for i in s.ingredients],
                method_label=s.method_label,
                steps=s.steps,
                notes=s.notes,
            )
            for s in raw.sections
        ],
    )


def structure(text: str, fallback_title: str) -> tuple[Recipe, dict[str, int]]:
    from mistralai.client import Mistral
    from mistralai.client.models import (
        AssistantMessage,
        JSONSchema,
        ResponseFormat,
        SystemMessage,
        ToolMessage,
        UserMessage,
    )

    from recipify.extract.ocr import api_key

    messages: list[AssistantMessage | SystemMessage | ToolMessage | UserMessage] = [
        SystemMessage(content=SYSTEM),
        UserMessage(content=f"File name: {fallback_title}\n\n{text}"),
    ]
    schema = JSONSchema(name="recipe", schema_definition=_Recipe.model_json_schema(), strict=True)
    response = Mistral(api_key=api_key()).chat.complete(
        model=MODEL,
        temperature=0,
        messages=messages,
        response_format=ResponseFormat(type="json_schema", json_schema=schema),
    )
    message = response.choices[0].message
    content = message.content if message else None
    if not isinstance(content, str):
        raise ValueError("the model returned no JSON")
    recipe = to_recipe(_Recipe.model_validate_json(content))
    # the model may borrow the file name as a title: then it is not part of the text
    recipe.title_in_text = Counter(tokens(recipe.title)) <= Counter(tokens(text))
    usage = {
        "prompt_tokens": response.usage.prompt_tokens or 0,
        "completion_tokens": response.usage.completion_tokens or 0,
    }
    return recipe, usage
