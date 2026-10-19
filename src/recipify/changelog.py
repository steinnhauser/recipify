"""Per-run CHANGELOG.md generated from metadata."""

from collections import Counter
from typing import TYPE_CHECKING

from recipify.quality import REVIEW_THRESHOLD

if TYPE_CHECKING:
    from recipify.metadata import Metadata


def _score(version: dict) -> float | None:
    return (version.get("quality") or {}).get("score")


def render_changelog(meta: "Metadata", run_id: str) -> str:
    run = meta.data["runs"].get(run_id, {})
    rows = []
    for key, entry in sorted(meta.recipes.items()):
        for v in entry["versions"]:
            if v["run_id"] == run_id:
                rows.append((key, entry, v))
    carried = [r for r in rows if r[2].get("carried_from")]
    rows = [r for r in rows if not r[2].get("carried_from")]
    ok = [r for r in rows if r[2]["status"] == "ok"]
    failed = [r for r in rows if r[2]["status"] != "ok"]
    prior = lambda e, v: any(  # noqa: E731
        o["status"] == "ok" and o["version"] < v["version"] for o in e["versions"]
    )
    new = [r for r in ok if not prior(r[1], r[2])]
    updated = [r for r in ok if prior(r[1], r[2])]

    out = [f"# Changelog: {run_id}", ""]
    if run.get("created_at"):
        out.append(f"Created: {run['created_at']}  ")
    if run.get("note"):
        out += ["", run["note"]]
    out += [
        "",
        "## Summary",
        "",
        f"- {len(new)} new recipe file(s) converted",
        f"- {len(updated)} existing file(s) got a new version",
        f"- {len(failed)} failure(s)",
        f"- {len(carried)} unchanged output(s) copied forward from earlier versions",
        f"- {len(meta.recipes)} source file(s) tracked in total",
        "",
    ]
    by = Counter((e["category"], v["processor"]) for _, e, v in ok)
    if by:
        out += ["| Category | Processor | Files |", "| --- | --- | --- |"]
        out += [f"| {c} | {p} | {n} |" for (c, p), n in sorted(by.items())]
        out.append("")

    current = [  # every recipe's latest output in this version, copied forward or new
        (k, e, v)
        for k, e in sorted(meta.recipes.items())
        for v in e["versions"][-1:]
        if v["run_id"] == run_id and v["status"] == "ok"
    ]
    review = [r for r in current if (s := _score(r[2])) is not None and s < REVIEW_THRESHOLD]
    if review:
        out += [f"## Needs manual review (accuracy < {REVIEW_THRESHOLD})", ""]
        for key, _, v in sorted(review, key=lambda r: _score(r[2]) or 0.0):
            flags = ", ".join(v["quality"].get("flags", []))
            out.append(f"- `{key}`: {_score(v)} ({flags}) {v['quality'].get('notes', '')}".rstrip())
        out.append("")
    if failed:
        out += ["## Failures", ""]
        out += [f"- `{k}`: {v['error']}" for k, _, v in failed]
        out.append("")

    out += [
        "## Files",
        "",
        "| Source | Output | v | Lang | Accuracy | Processor |",
        "| --- | --- | --- | --- | --- | --- |",
    ]
    for key, _, v in ok:
        s = _score(v)
        out.append(
            f"| {key} | {v['output']} | {v['version']} | {v.get('language', '')} | "
            f"{'' if s is None else s} | {v['processor']} |"
        )
    return "\n".join(out) + "\n"
