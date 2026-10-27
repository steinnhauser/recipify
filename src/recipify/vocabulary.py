"""Words that steer triage, splitting and the course-material check.

recipify makes no assumptions about a particular archive: these defaults are generic English
and Icelandic kitchen vocabulary. A collection in another language, or with its own habits,
adds words in ``curation.json`` under ``"vocabulary"``; they extend the defaults::

    {"vocabulary": {"collection_names": ["recettes"], "photo_folders": ["fotos"]}}

All entries are regular expressions matched against folded text (lowercase, no accents,
þ→th, ð→d, æ→ae): at the start of a word, except collection names, which also match inside
compound words ("Kökuuppskriftir" contains "uppskrift").
"""

import re
from functools import cached_property

from pydantic import BaseModel

# Kitchen paperwork that is not a recipe, recognised by file name.
REFERENCE_NAMES = [
    "menu", "mise en place", "prep list", "order list", "cleaning", "rota\\b", "staff",
    "rules", "price list", "cooking times", "costing",
    "missi", "\\w*sedill", "thrif", "pantanir", "simaskra", "starfsm", "reglur", "rutina",
    "vaktstjor", "innihaldslys", "\\w*utreikn", "hladbord", "leidarbok", "eldunartim",
]  # fmt: skip
# Folders that hold photos of dishes rather than of recipes.
PHOTO_FOLDERS = ["photos?", "pictures?", "images?", "img", "myndir"]
# File names or titles that announce a collection of recipes (one per page).
COLLECTION_NAMES = ["recipes", "recipe book", "uppskrift", "kokur\\b", "tertur\\b"]
# Form fields of school assignments and exams (student and teacher names).
COURSEWORK_MARKERS = [
    "student\\b", "teacher\\b", "nemandi", "nemendur", "kennari", "kennarar", "namstadur",
    "sveinsprof",
]  # fmt: skip


def _pattern(words: list[str], word_start: bool = True) -> re.Pattern[str]:
    return re.compile((r"\b" if word_start else "") + "(?:" + "|".join(words) + ")")


class Vocabulary(BaseModel):
    """Additions to the default word lists (the defaults always apply)."""

    reference_names: list[str] = []
    photo_folders: list[str] = []
    collection_names: list[str] = []
    coursework_markers: list[str] = []

    @cached_property
    def reference(self) -> re.Pattern[str]:
        return _pattern(REFERENCE_NAMES + self.reference_names)

    @cached_property
    def photo_folder(self) -> re.Pattern[str]:
        return re.compile(r"^(?:" + "|".join(PHOTO_FOLDERS + self.photo_folders) + r")$")

    @cached_property
    def collection(self) -> re.Pattern[str]:
        return _pattern(COLLECTION_NAMES + self.collection_names, word_start=False)

    @cached_property
    def coursework(self) -> re.Pattern[str]:
        return _pattern(COURSEWORK_MARKERS + self.coursework_markers)
