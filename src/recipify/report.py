"""The pipeline report (``report.md``): what was converted, what was held back, and why."""

import re
from collections import Counter, defaultdict

from recipify.categories import Category
from recipify.models import Catalog, Extraction, Inventory, SourceFile, Tier

TIERS = (Tier.READY, Tier.REVIEW, Tier.EXCLUDED)


def reason_group(reason: str) -> str:
    """'reading order uncertain (97% of lines agree)' -> 'reading order uncertain'."""
    reason = re.sub(r"\s*\(.*?\)", "", reason)
    reason = re.sub(r"duplicate of .*", "identical copy of another file", reason)
    reason = re.sub(
        r"same recipe as .*", "same recipe as another file (e.g. .docx and .pdf)", reason
    )
    return reason.split(":")[0].strip()


def tier_table(catalog: Catalog, inv: Inventory) -> list[tuple[str, int, int, int, int, int]]:
    """Per category: files, unique documents, and recipes ready, in review and excluded."""
    files = Counter(f.category for f in inv.files.values())
    documents: dict[Category, set[str]] = defaultdict(set)
    by_cat: dict[Category, Counter[Tier]] = defaultdict(Counter)
    for e in catalog.entries:
        documents[e.category].add(e.source)
        by_cat[e.category][e.assessment.tier] += 1
    rows = []
    for cat in Category:
        if files[cat]:
            t = by_cat[cat]
            rows.append(
                (
                    cat.value,
                    files[cat],
                    len(documents[cat]),
                    t[Tier.READY],
                    t[Tier.REVIEW],
                    t[Tier.EXCLUDED],
                )
            )
    return rows


def transcription_rows(
    found: list[tuple[SourceFile, Extraction]], catalog: Catalog
) -> list[dict[str, str]]:
    """One row per transcription: certainty, source, recipes, tier, engine and notes."""
    by_source: dict[str, list[str]] = defaultdict(list)
    tiers: dict[str, str] = {}
    for e in catalog.entries:
        by_source[e.source].append(e.title)
        tiers[e.source] = e.assessment.tier.value
    return [
        {
            "certainty": "not stated" if x.accuracy is None else f"{x.accuracy:.0%}",
            "source": f.path,
            "recipes": "; ".join(by_source.get(f.path, [])),
            "tier": tiers.get(f.path, ""),
            "engine": f"{x.engine}@v{x.version}",
            "notes": x.notes,
        }
        for f, x in found
    ]


def _cell(value: str) -> str:
    return value.replace("|", "\\|").replace("\n", " ")


def transcription_table(rows: list[dict[str, str]]) -> str:
    """The rows as a markdown table, for a file that is easy to read and share."""
    head = ["certainty", "source", "recipes", "tier", "engine", "notes"]
    out = [
        "# Transcriptions, least certain first",
        "",
        "| " + " | ".join(h.capitalize() for h in head) + " |",
        "|" + " --- |" * len(head),
    ]
    out += ["| " + " | ".join(_cell(r[h]) for h in head) + " |" for r in rows]
    return "\n".join(out) + "\n"


def render_report(
    catalog: Catalog, inv: Inventory, changes: list[tuple[str, str, str]] | None = None
) -> str:
    ready = catalog.by_tier(Tier.READY)
    out = [
        "# Pipeline report",
        "",
        f"Built {catalog.created_at}. {len(inv.files)} source files, "
        f"{len({e.source for e in catalog.entries})} unique documents, "
        f"**{len(ready)} recipes ready** (verified word for word against their source).",
        "",
        "Ready, Review and Excluded count recipes: a split document counts once per recipe.",
        "",
        "| Category | Files | Documents | Ready | Review | Excluded |",
        "| --- | ---: | ---: | ---: | ---: | ---: |",
    ]
    out += [f"| {r[0]} | " + " | ".join(map(str, r[1:])) + " |" for r in tier_table(catalog, inv)]

    split: dict[str, list[str]] = defaultdict(list)
    for e in sorted(catalog.entries, key=lambda e: (e.source, e.unit or 0)):
        if e.unit is not None:
            split[e.source].append(f"{e.unit}. {e.title} (p. {', '.join(map(str, e.unit_pages))})")
    if split:
        n = sum(map(len, split.values()))
        out += ["", f"## Split documents: {len(split)} into {n} recipes", ""]
        out += [f"- `{source}`: " + "; ".join(units) for source, units in split.items()]

    if changes:
        out += ["", f"## Changes since the last run: {len(changes)}", ""]
        out += [f"- `{source}`: {old} -> {new}" for source, old, new in changes]

    for tier in (Tier.REVIEW, Tier.EXCLUDED):
        entries = catalog.by_tier(tier)
        if not entries:
            continue
        reasons = Counter(reason_group(r) for e in entries for r in e.assessment.reasons)
        out += ["", f"## {tier.value.capitalize()}: {len(entries)}", ""]
        out += ["| Reason | Documents |", "| --- | ---: |"]
        out += [f"| {r} | {n} |" for r, n in reasons.most_common()]

    review = catalog.by_tier(Tier.REVIEW)
    if review:
        out += ["", "## Review list", ""]
        for e in sorted(review, key=lambda e: e.source):
            out.append(f"- `{e.source}`: {'; '.join(e.assessment.reasons)}")
    return "\n".join(out) + "\n"
