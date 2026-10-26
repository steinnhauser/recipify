# recipify

[![CI](https://github.com/steinnhauser/recipify/actions/workflows/ci.yml/badge.svg)](https://github.com/steinnhauser/recipify/actions/workflows/ci.yml)
[![Coverage](https://img.shields.io/endpoint?url=https%3A%2F%2Fsteinnhm.com%2Frecipify%2Fcoverage%2Fbadge.json)](https://steinnhm.com/recipify/coverage/)
[![Python 3.12+](https://img.shields.io/badge/python-3.12%2B-blue)](pyproject.toml)
[![License: MIT](https://img.shields.io/badge/license-MIT-green)](LICENSE)

**A document-processing pipeline that turns a kitchen's archive of recipe files into verified, structured recipes, and publishes them as one offline HTML file that chefs can cook from.**

recipify started from a real archive: about 1,900 files collected over many years by a professional kitchen, mostly in Icelandic. It holds Word documents, PDFs exported from Word (often laid out in two or three columns), scanned notebooks, photos, spreadsheets, cookbooks, menus, cleaning plans and many copies of the same files. Out of that archive, recipify publishes **380 recipes that were checked word for word against their source documents**. It holds back everything it can't check yet, and the report says why for each document.

**[Live demo](https://steinnhm.com/recipify/demo/)**: the whole pipeline run in CI on the [sample documents](examples/sources) ([pipeline report](https://steinnhm.com/recipify/demo/report.md))

<p align="center">
  <img src="docs/screenshot-desktop.png" alt="A three-component recipe scaled to 2x, with one ingredient ticked off" width="72%">
  &nbsp;
  <img src="docs/screenshot-mobile.png" alt="The same viewer on a phone" width="22%">
</p>

## The pipeline

```mermaid
flowchart LR
    S[("sources<br/>docx, pdf, xlsx,<br/>scans, photos")] --> I["1 inventory<br/>hash · classify · triage"]
    I --> E["2 extract<br/>poppler · python-docx ·<br/>LibreOffice · OCR*"]
    E --> T["3 structure<br/>rules · LLM*"]
    T --> A{"4 assess<br/>word-for-word check"}
    A -- ready --> V["5 viewer<br/>one HTML file"]
    A -- review / excluded --> R["report.md<br/>with reasons"]
    V --> L["lock<br/>AES-GCM"] --> P["GitHub Pages"]
```

<sub>\* paid API stages, opt-in: they only run when asked for, and never twice for the same document</sub>

| Stage | What it does | Stored as |
| --- | --- | --- |
| **1 Inventory** | Hashes every file, classifies it by its content rather than its extension (a `.pdf` can be a Word file or an EPUB), merges identical copies and triages each document as a recipe, a book (EPUB, or more than 8 pages) or reference material (mise en place lists, menus, staff rules). | `inventory.json` |
| **2 Extract** | Gets the text out locally and for free. PDFs use poppler in content-stream order, so each component of a multi-column recipe stays together, and the result is cross-checked against poppler's layout rendering. Word documents are read from the XML, including the text boxes that python-docx skips. Scans and photos wait for OCR. | `extractions/<sha256>/<engine>@v<N>.json` |
| **3 Structure** | Splits the text into components (a sauce, a crumble, a dough), each with its ingredients, method steps and notes, and parses quantities so they can be scaled. A deterministic rule set does this by default; an LLM with a JSON schema is an opt-in fallback for layouts the rules can't follow. | `recipes/<sha256>/<engine>@v<N>.json` |
| **4 Assess** | Counts every word and number in the extracted text and in the structured recipe, and checks them against each other. It also checks reading order, garbled text, whether there is an ingredient list and a method, and how long the document is. A document is `ready` only when every check passes. | `catalog.json`, `report.md` |
| **5 Publish** | Builds one self-contained HTML file from the `ready` recipes, and optionally encrypts it for public hosting. | `dist/index.html`, `site/index.html` |

### Why it can be trusted

- **Nothing is rewritten.** The structurer only decides what each source line is: a component name, an ingredient, a step or a note. It never changes the text. The few lines it leaves out on purpose (a repeated title, step numbers the viewer draws itself) are listed in the artifact.
- **Every published recipe is proven complete.** For text-layer documents the extracted text *is* the document. Recall 1.0 (every source word is shown) and precision 1.0 (no word was added) mean the reader sees exactly what the original says, only easier to follow. An LLM goes through the same check, so a paraphrase or an "improved" quantity sends the recipe to review instead of into the app.
- **Two extractors must agree on reading order.** A PDF whose text order doesn't match its visual layout is held back, even if every word is present.
- **Hard cases are named, not hidden.** [`report.md`](https://steinnhm.com/recipify/demo/report.md) lists every document that is not ready, with the reason.

### Why it is cheap to re-run

- Every artifact is keyed by the source's SHA-256 and the engine's version. Re-running the pipeline skips everything that is already done, renamed files keep their results, and an interrupted run resumes where it stopped.
- A new engine version writes a new file beside the old one, so earlier results are never overwritten.
- Paid results (OCR, LLM calls, hand transcriptions) are never recomputed automatically, not even with `--force`. Duplicates share one result.
- On the real archive, a full free run takes about 16 seconds once the files have been hashed.

### Results on the real archive

| | Documents |
| --- | ---: |
| Source files | 1,916 |
| Unique documents (byte-identical copies merged) | 930 |
| **Ready**: verified, structured and published | **380** |
| Review: converted, but a check failed (no clear ingredient list, uncertain reading order, read from images) | 73 |
| Waiting for OCR (photos and scans) | 325 |
| Not recipes, or not yet: books, collections, course material, menus and other paperwork, PDF twins of Word files | 152 |

## The viewer

The viewer is one HTML file with no external requests, so it works offline and can be emailed.

- **Recipes in components:** each component lists its quantities in an aligned column next to numbered steps. The source's own labels ("Aðferð", "Hráefni") are kept as headings.
- **Built for cooking:** scale ½× to 4× (baker's percentages stay as they are), tick off ingredients and steps, and switch to a full-screen reading view on phones. Recipes can also be printed.
- **Finding recipes:** search that ignores accents, filters with live counts, and course, diet, cuisine and main-ingredient labels detected with [transparent keyword rules](src/recipify/labels.py). Favourites and notes are saved in the browser.
- **Readable without JavaScript:** every recipe is written into the page as plain HTML. iOS Quick Look and mail previews, which don't run scripts, still show the whole collection.
- **Private on a public host:** `recipify lock` encrypts the page (AES-256-GCM, PBKDF2-SHA256), and the key travels in the link's `#fragment`, which browsers never send to the server.

## Quick start

Requires Python 3.12+, [uv](https://docs.astral.sh/uv/) and poppler (`apt install poppler-utils` or `brew install poppler`).

```bash
git clone https://github.com/steinnhauser/recipify.git && cd recipify
uv sync
uv run recipify demo --out demo.html --report report.md   # the whole pipeline on examples/sources
open demo.html
```

### Your own collection

```bash
uv run recipify --sources path/to/files run   # inventory, extract, structure, catalog (all free)
uv run recipify build                         # dist/index.html with every ready recipe
uv run recipify show "Desserts/Ostakaka.pdf"  # one document: tier, reasons, structured recipe
```

Each stage can also run on its own (`inventory`, `extract`, `structure`, `catalog`, `build`). The paid stages are opt-in and should be piloted with `--limit`. They need `MISTRAL_API_KEY` in `.env`:

```bash
uv run recipify extract --ocr --limit 5                          # OCR for scans and photos
uv run recipify structure --engine mistral-llm --review-only --limit 5
uv run recipify register "Scans/notebook.pdf" --text notebook.md --engine manual --accuracy 0.9
```

Corrections that don't belong in code (a better title, a kind, a tier set after review) go in `data/curation.json`. Everything under `data/` is git-ignored.

### Publishing privately

```bash
echo 'ENCRYPTION_KEY="<a long random string>"' >> .env
uv run recipify lock dist/index.html --show-link   # writes site/index.html (only ciphertext), prints the link
```

On `main`, [CI](.github/workflows/ci.yml) refuses to deploy a root page that isn't encrypted. It also checks that the page opens with the `ENCRYPTION_KEY` secret, runs the pipeline on the sample documents for `/demo/`, and publishes the coverage report.

## Project layout

```text
src/recipify/
  cli.py                one command per stage, plus run, show, demo and lock
  models.py, store.py   typed stage artifacts (pydantic) and the content-addressed workspace
  pipeline.py           runs the stages: caching, costly-result protection, run log
  classify.py           file categories from content (poppler, zip sniffing, image headers)
  inventory.py          stage 1: hashing, de-duplication, triage
  extract/              stage 2: pdf (poppler), docx (XML walker), office (LibreOffice, openpyxl), ocr (Mistral)
  structure/            stage 3: rules.py (deterministic), llm.py (Mistral, JSON schema), quantities.py
  assess.py             stage 4: fidelity check, text quality, language, tiers
  labels.py, report.py  titles, labels and report.md
  viewer.py, lock.py    stage 5: the viewer and its encryption (templates/)
examples/
  recipes/              the sample recipes, written for this project (markdown)
  make_sources.py       turns them into realistic documents in examples/sources/
tests/                  unit tests per stage and an end-to-end run on examples/sources
```

More detail on the design and the checks is in [docs/pipeline.md](docs/pipeline.md).

## Development

```bash
uv sync
uv run pytest --cov                    # 100% line coverage; CI fails below that
uv run ruff check src tests examples && uv run ruff format --check src tests examples
uv run mypy src                        # strict
uv run pre-commit install              # optional: the same checks before each commit
```

CI runs these on Python 3.12 and 3.13 with poppler installed.

## License

[MIT](LICENSE). The sample recipes in `examples/` were written for this project. Recipes you process remain the property of their authors.
