"""Display titles and auto-detected labels (keyword rules; no AI calls).

Manual corrections live in ``curation.json`` (keys are original file stems):
``{"titles": {stem: title}, "labels": {stem: {facet: [..]}}, "kind": {stem: "reference"}}``.
"""

import json
import re
from pathlib import Path
from typing import Any

LABEL_METHOD = "keywords-v1"
FACETS = ("course", "dish", "diet", "cuisine", "ingredients")


def fold(text: str) -> str:
    """Lowercase, strip accents and map Icelandic letters so one pattern covers spellings."""
    import unicodedata

    text = text.lower().replace("þ", "th").replace("ð", "d").replace("æ", "ae").replace("ö", "o")
    return "".join(c for c in unicodedata.normalize("NFD", text) if not unicodedata.combining(c))


def fix_mojibake(text: str) -> str:
    """Repair names that were cp850 bytes shown as latin-1 (e.g. 'S¢sa' -> 'Sósa')."""
    if not re.search(r"[¢£\x80-\x9f]", text):
        return text
    try:
        return text.encode("latin-1").decode("cp850")
    except UnicodeError:
        return text


def _rx(*words: str) -> re.Pattern[str]:
    return re.compile(r"\b(?:" + "|".join(words) + r")")


# ingredient label -> pattern (folded text, word-start match)
INGREDIENTS = {
    "lamb": _rx("lamb", "lambs"),
    "beef": _rx("naut", "beef", "entrecote", "ribeye", "veal", "kalf"),
    "pork": _rx(
        "svina", "svin", "pork", "bacon", "beikon", "skinka", "ham\\b", "prosciutto", "pancetta"
    ),
    "chicken": _rx("kjukling", "chicken"),
    "duck": _rx("anda(?:bring|laeri|fit)", "duck", "andar"),
    "goose": _rx("gaes", "goose"),
    "fish": _rx(
        "lax",
        "salmon",
        "thors",
        "cod\\b",
        "ysa",
        "haddock",
        "bleikj",
        "arctic char",
        "silung",
        "urrida",
        "trout",
        "karfi",
        "fisk",
        "tuna",
        "tunfisk",
    ),
    "shellfish": _rx(
        "humar",
        "rak(?:ja|jur)",
        "shrimp",
        "prawn",
        "krabb",
        "crab",
        "hotaskel",
        "scallop",
        "kraklingur",
        "mussel",
        "lobster",
        "langoustine",
    ),
    "egg": _rx("egg(?!aldin)", "eggs?\\b"),
    "dairy": _rx(
        "smjor",
        "butter",
        "rjom",
        "cream",
        "mjolk",
        "milk",
        "ostur",
        "osti",
        "ost\\b",
        "cheese",
        "skyr",
        "jogurt",
        "yogurt",
        "mascarpone",
        "feta",
        "parmesan",
    ),
    "chocolate": _rx("sukkulad", "chocolate", "kakao", "cocoa", "ganache"),
    "mushroom": _rx("svepp", "mushroom", "portobello", "shiitake"),
    "potato": _rx("kartofl", "potato"),
    "rice": _rx("hrisgrjon", "rice", "risotto"),
    "pasta": _rx(
        "pasta", "spaghetti", "tagliatelle", "lasagn", "gnocchi", "nudl", "noodle", "ravioli"
    ),
    "nuts": _rx(
        "hnet", "mondl", "almond", "hazelnut", "pistas", "pecan", "walnut", "cashew", "heslihnet"
    ),
    "berries": _rx(
        "jardaber",
        "strawberr",
        "hindber",
        "raspberr",
        "bla ?ber",
        "blueberr",
        "kirsuber",
        "cherr",
        "cranberr",
        "berry",
    ),
    "citrus": _rx("sitron", "lemon", "lime", "appelsin", "orange", "grapefruit"),
    "apple": _rx("epli", "apple"),
    "tomato": _rx("tomat"),
    "onion & garlic": _rx("laukur", "laukar", "onion", "hvitlauk", "garlic", "shallot", "skalot"),
    "vegetables": _rx(
        "gulrot",
        "carrot",
        "kal\\b",
        "cabbage",
        "rofu",
        "rofa",
        "beet",
        "paprik",
        "agurk",
        "cucumber",
        "spinat",
        "salat",
        "lettuce",
        "brokkoli",
        "broccoli",
        "kurbit",
        "zucchini",
        "eggaldin",
        "eggplant",
        "sellerí",
        "celery",
        "fennel",
        "fenikk",
    ),
    "legumes": _rx("baun", "bean", "linsu", "lentil", "chickpea", "kjuklingabaun", "hummus"),
    "tofu": _rx("tofu"),
    "honey": _rx("hunang", "honey"),
    "gelatin": _rx("gelat", "matarlim"),
}
MEAT_FISH = {"lamb", "beef", "pork", "chicken", "duck", "goose", "fish", "shellfish", "gelatin"}
ANIMAL_OTHER = {"dairy", "egg", "honey"}
SHOW_INGREDIENTS = 5
GENERIC = {
    "citrus",
    "onion & garlic",
    "vegetables",
    "dairy",
    "egg",
    "honey",
    "nuts",
    "berries",
    "apple",
    "tomato",
    "potato",
}

COURSES = {
    "starter": _rx("forrett", "starter", "appetizer", "appetiser", "amuse"),
    "main": _rx("adalrett", "main course", "entree", "aðalrétt"),
    "dessert": _rx(
        "eftirrett",
        "dessert",
        "desert",
        "konfekt",
        "mousse",
        "sorbet",
        "ice cream",
        "macaron",
        "cookie",
        "smakok",
        "brownie",
        "pudding",
        "brulee",
        "madelen",
        "dragee",
        "truffle",
        "tart\\b",
        "cheesecake",
        "panna cotta",
        "parfait",
        "cake\\b",
        "kaka\\b",
        "kokur",
        "sukkuladi",
    ),
    "bread & pastry": _rx(
        "bakari",
        "brauð",
        "braud",
        "bread",
        "croissant",
        "deig",
        "dough",
        "brioche",
        "pastry",
        "bolla",
        "focaccia",
        "snudur",
        "cinnamon roll",
    ),
    "sauce & basics": _rx(
        "sosa",
        "sosu",
        "sauce",
        "dressing",
        "marinad",
        "paste\\b",
        "grunn",
        "pickl",
        "chutney",
        "mayo",
        "vinaigrette",
        "relish",
        "salsa",
        "pækill",
        "paekill",
        "krydd",
        "rub\\b",
        "stock",
        "soð",
        "sod\\b",
        "glaze",
    ),
    "breakfast": _rx(
        "morgunmat",
        "morgunverd",
        "breakfast",
        "granola",
        "pancake",
        "ponnukok",
        "brunch",
        "overnight oats",
        "hafragrautur",
    ),
    "drink": _rx("drykk", "drink", "smoothie", "cocktail", "juice", "safi", "latte", "shake\\b"),
    "snack & canapé": _rx(
        "smurbraud", "pinnamat", "canape", "snack", "bites?\\b", "tapas", "finger food", "nasl"
    ),
    "side": _rx("medlaeti", "side dish", "sides?\\b", "slaw", "gratin"),
}
COURSE_ORDER = list(COURSES)

DISH = {
    "salad": _rx("salat", "salad", "slaw"),
    "soup": _rx("supa", "supu", "soup", "broth", "chowder", "bisque"),
    "rice": _rx("hrisgrjon", "rice", "risotto", "paella"),
    "pasta": _rx("pasta", "spaghetti", "lasagn", "gnocchi", "noodle", "ravioli"),
    "burger & sandwich": _rx(
        "hamborg",
        "burger",
        "sandwich",
        "samloka",
        "smurbraud",
        "bao",
        "wrap",
        "taco",
        "burrito",
        "blt\\b",
    ),
    "ice cream & sorbet": _rx("ice cream", "sorbet", "gelato", "frozen yog"),
    "cake & biscuit": _rx(
        "cake\\b",
        "kaka\\b",
        "kokur",
        "cookie",
        "smakok",
        "brownie",
        "madelen",
        "macaron",
        "biscuit",
        "tart\\b",
    ),
    "dough": _rx("deig", "dough", "brioche", "croissant"),
    "smoothie": _rx("smoothie"),
    "egg dish": _rx("omelett", "scrambled", "hrarra", "frittata", "eggjakaka"),
}

CUISINES = {
    "Mexican & Latin": _rx(
        "taco",
        "empanada",
        "mole\\b",
        "salsa",
        "guacamole",
        "tortilla",
        "anticucho",
        "chicharron",
        "burrito",
        "chili",
        "jalapeno",
        "chipotle",
        "ceviche",
        "tequila",
        "burro",
        "pico de gallo",
        "quesadilla",
        "aji\\b",
    ),
    "Asian": _rx(
        "soy",
        "soja",
        "miso",
        "sesam",
        "sesame",
        "engifer",
        "ginger",
        "wasabi",
        "sushi",
        "ramen",
        "teriyaki",
        "kimchi",
        "sriracha",
        "wok",
        "nori\\b",
        "bao\\b",
        "dashi",
        "mirin",
        "hoisin",
        "lemongrass",
        "thai",
        "kokos",
        "coconut milk",
        "ponzu",
        "yuzu",
    ),
    "Indian": _rx(
        "curry",
        "masala",
        "tikka",
        "naan",
        "paneer",
        "garam",
        "tandoori",
        "turmeric",
        "kurkuma",
        "cardamom",
        "kardimomm",
    ),
    "Italian": _rx(
        "risotto",
        "parmesan",
        "parmigiano",
        "mozzarella",
        "pesto",
        "focaccia",
        "ciabatta",
        "tiramisu",
        "prosciutto",
        "gnocchi",
        "panna cotta",
        "balsam",
        "burrata",
        "lasagn",
        "amaretto",
        "ricotta",
        "pizza",
        "spaghetti",
        "carpaccio",
    ),
    "French": _rx(
        "brulee",
        "brioche",
        "croissant",
        "tarte",
        "confit",
        "beurre",
        "vinaigrette",
        "ganache",
        "macaron",
        "madelen",
        "bechamel",
        "gratin",
        "ratatouille",
        "foie gras",
        "eclair",
        "choux",
        "patissiere",
        "creme fraiche",
        "tuile",
        "fondant",
        "dijon",
    ),
    "Nordic": _rx(
        "skyr",
        "rugbraud",
        "hardfisk",
        "hangikjot",
        "lambahrygg",
        "skarkol",
        "hverabraud",
        "surkal",
        "baeber",
        "rhubarb",
        "rabarbar",
        "krakiber",
        "aevntyri",
        "angelica",
        "hvonn",
        "gravlax",
        "grafin",
        "grafid",
        "birki",
        "wild herbs",
        "icelandic",
        "nordic",
    ),
    "American": _rx(
        "bbq",
        "burger",
        "ranch",
        "mac and cheese",
        "brownie",
        "pancake",
        "hot dog",
        "coleslaw",
        "buffalo",
        "bourbon",
        "maple",
        "pecan",
        "cornbread",
        "s'mores",
        "smores",
        "blt\\b",
        "baked beans",
        "sausage",
    ),
    "Mediterranean": _rx(
        "feta",
        "tzatziki",
        "hummus",
        "falafel",
        "couscous",
        "tahini",
        "olive",
        "halloumi",
        "pita",
        "labneh",
        "za'atar",
        "chorizo",
        "paella",
        "manchego",
        "gazpacho",
        "jamon",
        "romesco",
        "harissa",
        "sumac",
    ),
}

REFERENCE_NAME = _rx(
    "missi",
    "magnutreikn",
    "simaskra",
    "thrifaplan",
    "hladbord",
    "utreikn",
    "starfsmenn",
    "verdutreikn",
    "pantanir",
)

COURSE_ALIASES = {
    "starter",
    "main",
    "dessert",
    "bread & pastry",
    "sauce & basics",
    "breakfast",
    "drink",
    "snack & canapé",
    "side",
}
UNTITLED = re.compile(
    r"untitled|^\d{6,}$|^(?:new|nytt|document|doc|scan|img|image|copy of)\b|^recipe$", re.I
)


def load_curation(path: Path) -> dict[str, Any]:
    if path.is_file():
        curation: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
        return curation
    return {"titles": {}, "labels": {}, "kind": {}}


def _first_heading(text: str) -> str | None:
    m = re.search(r"^#\s+(.+)$", text, re.M)
    return m.group(1).strip() if m else None


def _content_title(text: str) -> str | None:
    """First short plain line after the heading: a better name for 'untitled' files."""
    lines = [ln.strip() for ln in text.splitlines()]
    for ln in lines[1:]:
        ln = re.sub(r"^[#>*|\s-]+|[*|\s]+$", "", ln)
        if (
            3 <= len(ln) <= 60
            and not ln.isdigit()
            and not ln.lower().startswith(("page", "transcribed"))
        ):
            return ln
    return None


def refine_title(original: str, text: str, stem: str, curated: dict[str, str]) -> str:
    if stem in curated:
        return curated[stem]
    title = fix_mojibake(original)
    title = re.sub(r"(?<=\d)_(?=\d)", ".", title)
    title = re.sub(r"_+", " ", title)
    title = re.sub(r"\s*\(\d{1,2}\)$", "", title)
    title = re.sub(r"\s{2,}", " ", title).strip(" :.,;–-")
    if UNTITLED.search(title):
        title = _content_title(text) or title
    if len(title) > 3 and title.isupper() and " " in title:
        title = title.capitalize()
    return title[:1].upper() + title[1:] if title else original


def _counts(patterns: dict[str, re.Pattern[str]], text: str) -> dict[str, int]:
    return {k: len(p.findall(text)) for k, p in patterns.items() if p.search(text)}


def detect_labels(title: str, source: str, text: str) -> dict[str, list[str]]:
    ft, fp, fx = fold(title), fold(source), fold(text)
    labels: dict[str, list[str]] = {f: [] for f in FACETS}

    scores: dict[str, int] = {}
    for course, rx in COURSES.items():
        s = 3 * bool(rx.search(ft)) + 2 * bool(rx.search(fp)) + (len(rx.findall(fx)) >= 3)
        if s >= 2:
            scores[course] = s
    labels["course"] = sorted(scores, key=lambda c: (-scores[c], COURSE_ORDER.index(c)))[:2]

    labels["dish"] = [d for d, rx in DISH.items() if rx.search(ft) or len(rx.findall(fx)) >= 4][:3]

    counts = _counts(INGREDIENTS, fx)
    ranked = sorted(counts, key=lambda k: (-counts[k], k))
    present = {k for k, n in counts.items() if n >= 1}
    labels["ingredients"] = [k for k in ranked if k not in {"dairy", "egg", "honey", "gelatin"}][
        :SHOW_INGREDIENTS
    ]
    if "dairy" in counts and not labels["ingredients"]:
        labels["ingredients"] = ["dairy"]

    diet: list[str] = []
    if len(fx) >= 200 and not (present & MEAT_FISH):
        diet = ["vegetarian", "vegan"] if not present & ANIMAL_OTHER else ["vegetarian"]
    elif len(fx) >= 200:
        # themes: only when the animal ingredient is a real part of the dish
        def strong(names: set[str]) -> bool:
            return any(counts.get(n, 0) >= 2 or INGREDIENTS[n].search(ft) for n in names)

        if strong({"fish", "shellfish"}):
            diet.append("seafood")
        if strong({"lamb", "beef", "pork", "chicken", "duck", "goose"}):
            diet.append("meat")
    if re.search(r"gluten ?free|glutenlaus|gluteinlaus|glutenfri", ft + " " + fx):
        diet.append("gluten-free")
    if set(labels["course"]) & {"dessert"}:
        diet.append("sweet")
    labels["diet"] = diet

    cuis = {}
    for name, rx in CUISINES.items():
        hits = {m for m in rx.findall(fx)}
        n = len(hits) + 2 * bool(rx.search(ft))
        if n >= 3:
            cuis[name] = n
    labels["cuisine"] = sorted(cuis, key=lambda c: -cuis[c])[:2]
    return labels


def describe(key: str, text: str, curation: dict[str, Any]) -> dict[str, Any]:
    stem = Path(key).stem
    original = _first_heading(text) or stem
    title = refine_title(original, text, stem, curation.get("titles", {}))
    labels = detect_labels(title, key, text)
    for facet, values in curation.get("labels", {}).get(stem, {}).items():
        labels[facet] = values
    kind = curation.get("kind", {}).get(stem) or (
        "reference" if REFERENCE_NAME.search(fold(stem)) else "recipe"
    )
    return {
        "title": title,
        "original_title": original,
        "original_filename": Path(key).name,
        "kind": kind,
        "labels": labels,
        "label_method": LABEL_METHOD,
    }
