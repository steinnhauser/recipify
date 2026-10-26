"""Find and parse the quantity at the start of an ingredient line ("1,5 kg smjör")."""

import re

from recipify.models import Ingredient

UNITS = (
    "kg|kilo|grömm|gramm|grams?|gr|g|mg|ltr|lítrar|lítri|liters?|litres?|l|dl|cl|ml"
    "|msk|tsk|tbsp|tbs|tsp|cups?|bollar|bolli|oz|lbs?|pcs|pc|pieces?|stk|st|ea|blöð|blað|sheets?"
    "|cloves?|geirar|geiri"
    "|dósir|dós|cans?|pakkar|pakki|pk|búnt|bunch|klípa|pinch|dash|sneiðar|sneið|slices?|%"
)
FRACTIONS = {"½": 0.5, "¼": 0.25, "¾": 0.75, "⅓": 1 / 3, "⅔": 2 / 3, "⅛": 0.125}
_NUM = r"\d+(?:[.,]\d+)?"
_FRAC = "[" + "".join(FRACTIONS) + "]"
_AMOUNT = rf"(?:{_NUM}\s*{_FRAC}|{_NUM}/\d+|{_NUM}|{_FRAC})"
QUANTITY = re.compile(
    rf"^(?P<approx>(?:ca|c\.a|u\.?þ\.?b|approx|about)\.?\s*)?"
    rf"(?P<a>{_AMOUNT})(?:\s*(?:-|–|til|to)\s*(?P<b>{_AMOUNT}))?"
    rf"\s*(?P<unit>(?:{UNITS})(?![^\W\d_]))?\.?\s*(?P<name>.*)$",
    re.I,
)
TRAILING = re.compile(  # "Rolled oats 250 g", "Oat milk 1L": English sheets put it last
    rf"^(?P<name>[^\W\d_].*?)\s+(?P<a>{_AMOUNT})(?:\s*(?:-|–)\s*(?P<b>{_AMOUNT}))?"
    rf"\s*(?P<unit>(?:{UNITS}))\.?$",
    re.I,
)
NUMBERED_STEP = re.compile(r"^(\d{1,2})[.)]\s+(?=[^\W\d_])")  # "1. Boil the potatoes"


def amount(text: str) -> float:
    """'1,5' -> 1.5, '1 ½' -> 1.5, '3/4' -> 0.75, '¼' -> 0.25."""
    text = text.replace(" ", "")
    whole, frac = text.rstrip("".join(FRACTIONS)), text[-1] if text[-1] in FRACTIONS else ""
    if "/" in whole:
        top, bottom = whole.split("/")
        value = int(top) / int(bottom)
    else:
        value = float(whole.replace(",", ".")) if whole else 0.0
    return value + FRACTIONS.get(frac, 0.0)


def parse_ingredient(line: str) -> Ingredient | None:
    """An Ingredient when the line starts (or, with a unit, ends) with a quantity."""
    if NUMBERED_STEP.match(line):
        return None
    m = QUANTITY.match(line)
    if m and (m.group("name") or m.group("unit")) and _plausible(m):
        end = m.start("unit") if m.group("unit") else m.end("b") if m.group("b") else m.end("a")
        return _ingredient(line, m, line[:end].strip())
    m = TRAILING.match(line)
    if m:
        return _ingredient(line, m, line[m.start("a") : m.start("unit")].strip())
    return None


def _plausible(m: re.Match[str]) -> bool:
    """Reject numbers that are not amounts: '140°C, vifta 2', '4.-10. Júní', '4 x 2,5'."""
    if m.group("unit"):
        return True
    name = m.group("name")
    return not (name.startswith(("°", "*c", "*C", "-", "–", ".", "/")) or re.match(r"x\b", name))


def _ingredient(line: str, m: re.Match[str], quantity: str) -> Ingredient:
    return Ingredient(
        text=line,
        amount=amount(m.group("a")),
        amount_max=amount(m.group("b")) if m.group("b") else None,
        quantity=quantity,
        unit=m.group("unit") or "",
        name=m.group("name").strip(),
    )
