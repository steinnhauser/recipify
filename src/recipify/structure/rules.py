"""Deterministic structurer: plain text -> title, components, ingredients, steps, notes.

It never rewrites text; it only decides what each source line is. Every source line ends up
in the recipe exactly once, except for a few listed in ``Recipe.dropped`` (an echoed title,
step numbers that the viewer shows as list numbers), so the assessment stage can prove that
no word or number was lost or invented.

A recipe document is read as a sequence of components::

    [name]  [ingredient label]  ingredient lines  [method label]  steps  [notes]

with the source's own labels ("Hráefni", "Aðferð:", "Method") kept as headings.
"""

import re
from dataclasses import dataclass

from recipify.models import Ingredient, Recipe, Section
from recipify.structure.quantities import NUMBERED_STEP, parse_ingredient
from recipify.text import fold

ENGINE, VERSION = "rules", 2

METHOD_LABEL = re.compile(  # matched on the original text, so the rest keeps its offsets
    r"^(?:a[ðd]fer[ðd]|method|methods|directions|instructions|preparation|framkvæmd"
    r"|lei[ðd]beiningar|vinnsla|vinnslan)\b\s*[:.]?\s*",
    re.I,
)
INGREDIENTS_LABEL = re.compile(r"^(?:hraefni|innihald|ingredients|uppskrift)\b\s*[:.]?\s*$")
NOTE_LABEL = re.compile(
    r"^(?:geymsluthol|shelf ?life|storage|geymsla|yield|magn|skammtar|serves|portions"
    r"|ath\b|athugid|note|notes|tip|allergens?|ofnaemisvald\w*|samsetning|plating"
    r"|framreidsla|served?\b|thessi uppskrift|uppskriftin gefur|makes\b|dugar)",
)
# Single words that are ingredients even without a quantity, never component names.
BARE_INGREDIENTS = {
    "salt", "pipar", "pepper", "sykur", "sugar", "vatn", "water", "olia", "oil",
    "salt og pipar", "salt & pipar", "salt and pepper", "salt & pepper", "smjor", "butter",
}  # fmt: skip
# "Smá vatn", "a pinch of salt": amounts in words, so ingredients even without a number.
AMOUNT_WORDS = re.compile(r"^(?:sma|ogn|dash|pinch|klipa|a little|some|handful|hnefi)\b")
LONG_INGREDIENT = 8  # words; longer lines that start with a number are sentences
# Cooking verbs (folded), for instruction lines written between ingredients:
# "Lagt í bleyti", "Þessu er hrært vel saman", "Bake at 180°C", "Weigh 550 g per tin".
METHOD_VERBS = set(
    "hraert hrara hraerid blandad blandid bakad bakid vigtad vigtid rullad rullid lagt sett "
    "settur sodid thett theytt theytid pensla penslad kaelt kaelid steikt latid unnid "
    "hnodad hnodid baett baetid skorid sigtad smakkad maukad fryst hitad hitid braett saxad "
    "strad hellt smurt sprautad pakkad eldad grillad ristad mulid hefast dreift kaela "
    "mix stir bake whisk add combine beat knead roll weigh cool chill fold heat boil simmer "
    "pour spread cut fry season blend rest preheat sift soak melt".split()
)
TEMPERATURE_OR_TIME = re.compile(r"\d\s*°|\bgrad|\b\d+\s*(?:min|klst|hours?|sek)\b")
WRAP_CHARS = 35  # a step line shorter than this ended there; it was not wrapped
BULLET = re.compile(r"^[-•*–]\s+")
HEADING = re.compile(r"^#{1,6}\s+")
TERMINAL = (".", "!", "?", ":")
FIELD = re.compile(r"^[^\W\d_]+\s+:\s")  # "Námstaður : Hótel- og..." is a form field, not a title
SENTENCE_BREAK = re.compile(r"[.!?]\s+\S")
SHORT_WORDS, SHORT_CHARS = 6, 50


@dataclass
class Line:
    text: str
    para_start: bool  # first line after a blank line
    page_start: bool = False  # first line of a new PDF page
    bullet: bool = False
    heading: bool = False
    number: str = ""  # "3" for a numbered step "3. ..."

    @property
    def folded(self) -> str:
        return fold(self.text)

    @property
    def short(self) -> bool:
        words = self.text.split()
        return (
            len(words) <= SHORT_WORDS
            and len(self.text) <= SHORT_CHARS
            and not self.text.endswith((".", ",", ";"))
        )


def _lines(text: str) -> list[Line]:
    out: list[Line] = []
    blank, page = True, False
    for raw in text.split("\n"):
        if "\f" in raw:
            page = True
        line = raw.strip()
        if not line or set(line) <= set("|-: \f"):  # blank lines, page breaks, table rules
            blank = True
            continue
        item = Line(line, para_start=blank, page_start=page)
        if HEADING.match(line):
            item.text, item.heading = HEADING.sub("", line), True
        elif BULLET.match(line):
            item.text, item.bullet = BULLET.sub("", line), True
        elif m := NUMBERED_STEP.match(line):
            item.number = m.group(1)  # stripped only if the line becomes a step
        if "|" in item.text:  # a table row: "600 g | cod" or "| 600 g | cod |"
            cells = [c.strip() for c in item.text.strip("|").split("|")]
            item.text = " · ".join(c for c in cells if c)
        out.append(item)
        blank = page = False
    return out


def _instruction(line: Line) -> bool:
    """A method step written between ingredients ("Lagt í bleyti", "Bakað 180°C í 20 mín")."""
    if _is_qty(line):
        return False
    if TEMPERATURE_OR_TIME.search(line.folded):
        return True
    words = re.findall(r"\w+", line.folded)
    return len(words) >= 3 and any(w in METHOD_VERBS for w in words)


def _is_qty(line: Line) -> bool:
    return not line.number and parse_ingredient(line.text.replace(" · ", " ")) is not None


class _Parser:
    def __init__(self, lines: list[Line], title: str):
        self.lines = lines
        self.recipe = Recipe(title=title)
        self.section = Section()
        self.mode = "start"  # start (after a name) | ingredients | method
        self.note_open = False  # last note ended with ':' and takes the next line
        self.last_line_len = 0  # of the last physical line added to a step
        self.inline = False  # the last step was an instruction between ingredients

    # -- lookahead ---------------------------------------------------------------------

    def _evidence(self, i: int) -> int:
        """How sure we are that line i names a component: 0 no, 1 weak, 2 strong.

        Strong: a heading, or a short line directly followed by a quantity or an ingredient
        label. Weak: a short line followed by more short lines and then a method label, which
        is either a component name over a list of bare ingredients, or one of those ingredients.
        """
        line = self.lines[i]
        if line.heading:
            return 2
        bare = line.folded in BARE_INGREDIENTS or AMOUNT_WORDS.match(line.folded)
        if not line.short or line.bullet or line.number or bare or _instruction(line):
            return 0
        if line.text[:1].islower() or _is_qty(line) or SENTENCE_BREAK.search(line.text):
            return 0
        if METHOD_LABEL.match(line.text) or NOTE_LABEL.match(line.folded):
            return 0
        following = self.lines[i + 1 : i + 30]
        if following and (INGREDIENTS_LABEL.match(following[0].folded) or _is_qty(following[0])):
            return 2
        if following and self._names_prose(line, following):
            return 1
        for run, nxt in enumerate(following):
            if METHOD_LABEL.match(nxt.text):
                return 1 if run else 0
            if not nxt.short or nxt.heading or nxt.text[:1].islower() or _is_qty(nxt):
                return 0
        return 0

    def _at_top(self) -> bool:
        """Still before the first component: text here is an introduction."""
        s = self.section
        return self.mode == "start" and not self.recipe.sections and not (s.name or s.notes)

    def _wraps(self, i: int) -> bool:
        """The sentence continues on the next line, so this is prose, not a list item."""
        nxt = self.lines[i + 1 : i + 2]
        return bool(nxt) and not nxt[0].para_start and nxt[0].text[:1].islower()

    def _names_prose(self, line: Line, following: list[Line]) -> bool:
        """'Beetroot' + 'The beetroots are baked whole...': a component with only a method."""
        steps, nxt = self.section.steps, following[0]
        after_step = self.mode == "method" and bool(steps) and steps[-1].endswith(TERMINAL)
        at_start = self.mode == "start" and not self.section.name and not steps
        # in narrow columns prose lines are short too; a wrapped next line gives them away
        prose = not nxt.short or (len(following) > 1 and following[1].text[:1].islower())
        return (
            (after_step or at_start)
            and not line.text.endswith(":")
            and prose
            and nxt.text[:1].isupper()
            and not _is_qty(nxt)
        )

    # -- building ----------------------------------------------------------------------

    def _close(self) -> None:
        s = self.section
        if s.name or s.ingredients or s.steps or s.notes or s.method_label or s.ingredients_label:
            self.recipe.sections.append(s)
        self.section = Section()

    def _start_component(self, name: str = "") -> None:
        self._close()
        self.section.name = name
        self.mode = "start"

    def _add_step(self, line: Line) -> None:
        steps = self.section.steps
        if line.number:  # the viewer numbers the steps itself
            self.recipe.dropped.append(line.number)
            line = Line(NUMBERED_STEP.sub("", line.text), line.para_start, number=line.number)
        continues = (
            steps
            and not line.para_start
            and not line.bullet
            and not line.number
            and not steps[-1].endswith(TERMINAL)
            and (line.text[:1].islower() or line.text[:1].isdigit() or steps[-1][-1:] in ",;-–(")
        )
        if continues:
            steps[-1] += " " + line.text
        else:
            steps.append(line.text)
        self.last_line_len = len(line.text)
        self.inline = False

    def _add_note(self, line: Line) -> None:
        notes = self.section.notes
        if self.note_open and notes:
            notes[-1] += " " + line.text
        else:
            notes.append(line.text)
        self.note_open = line.text.endswith(":")

    def _name(self, line: Line) -> None:
        name = line.text.rstrip(":").strip()
        s = self.section
        if s.name or s.ingredients or s.steps or s.notes or s.method_label:
            self._start_component(name)
        else:
            self.section.name = name
        self.mode = "start"

    def parse(self) -> Recipe:
        for i, line in enumerate(self.lines):
            if self.note_open and not line.heading:  # "Geymsluþol:" + "4 dagar."
                self._add_note(line)
                continue
            self.note_open = False
            folded, empty = line.folded, not (self.section.ingredients or self.section.steps)
            evidence = self._evidence(i)
            if INGREDIENTS_LABEL.match(folded):
                if not empty or self.section.ingredients_label:
                    self._start_component()
                self.section.ingredients_label = line.text
                self.mode = "ingredients"
            elif m := METHOD_LABEL.match(line.text):
                if self.section.steps or self.section.method_label:
                    self._start_component()
                self.section.method_label = line.text[: m.end()].strip()
                self.mode = "method"
                if rest := line.text[m.end() :].strip():
                    self._add_step(Line(rest, para_start=True))
            elif NOTE_LABEL.match(folded) and not _is_qty(line):
                if self._at_top():  # "Serves 4." before the first component
                    self.recipe.intro.append(line.text)
                else:
                    self._add_note(line)
            elif self.mode == "ingredients" and _instruction(line):
                self._add_step(Line(line.text, para_start=True))  # closes the group above
                self.inline = True
                self.mode = "method"
            elif evidence == 2 or (evidence == 1 and self.mode == "method"):
                self._name(line)
            elif evidence == 1 and self.mode == "start" and empty and not self.section.name:
                self._name(line)
            elif _is_qty(line) and self._qty_is_ingredient(i):
                if self.mode == "method" and self.section.steps:
                    self._start_component()
                self.section.ingredients.append(_ingredient(line.text))
                self.mode = "ingredients"
            elif self.mode == "method" or line.number:
                self._add_step(line)
                self.mode = "method"
            elif (
                line.short
                and (self.mode == "ingredients" or self.section.name)
                and not self._wraps(i)
            ):
                self.section.ingredients.append(Ingredient(text=line.text, name=line.text))
                self.mode = "ingredients"
            elif self._at_top():
                self.recipe.intro.append(line.text)
            else:  # prose after a list or under a name: the method, without a label
                self.mode = "method"
                self._add_step(line)
        self._close()
        return self.recipe

    def _qty_is_ingredient(self, i: int) -> bool:
        """In a method, '2 dl af soðinu sett í pott...' is a step, not a new list."""
        line = self.lines[i]
        long = len(line.text.split()) > LONG_INGREDIENT
        if self.mode != "method":
            return not (long and self.mode == "ingredients" and self._wraps(i))
        steps = self.section.steps
        if not steps:
            return not long
        wrapped = self.last_line_len >= WRAP_CHARS and not steps[-1].endswith(TERMINAL)
        if not line.para_start and wrapped:
            return False  # a wrapped step line that happens to start with a number
        if self.inline:
            return not long  # after "Lagt í bleyti": the next group of ingredients
        nxt = self.lines[i + 1 : i + 2]
        found = parse_ingredient(line.text)
        return not long and (
            bool(nxt and _is_qty(nxt[0]))
            or bool(found and found.unit and len(line.text.split()) <= 5)
        )


def _ingredient(text: str) -> Ingredient:
    found = parse_ingredient(text.replace(" · ", " "))
    assert found is not None  # callers checked _is_qty
    return found.model_copy(update={"text": text})


def structure(text: str, fallback_title: str) -> Recipe:
    lines = _lines(text)
    if not lines:
        return Recipe(title=fallback_title, title_in_text=False)
    first = lines[0]
    parser = _Parser([], fallback_title)
    no_title = first.text.endswith(":") or FIELD.match(first.text)
    if _is_qty(first) or len(first.text) > 90 or no_title:
        title, body = fallback_title, lines  # no title line: "Muffins:" names a component
        parser.recipe.title_in_text = False
    else:
        title, body = first.text.rstrip(":").strip(), lines[1:]
        parser.recipe.title = title
    key = fold(title)
    for n, line in enumerate(body):  # echoes of the title: repeated headings, page headers
        if fold(line.text).rstrip(":").strip() == key and (n < 3 or line.page_start):
            parser.recipe.dropped.append(line.text)
        else:
            parser.lines.append(line)
    return parser.parse()
