# recipify

[![CI](https://github.com/steinnhauser/recipify/actions/workflows/ci.yml/badge.svg)](https://github.com/steinnhauser/recipify/actions/workflows/ci.yml)
[![Python 3.12+](https://img.shields.io/badge/python-3.12%2B-blue)](pyproject.toml)
[![License: MIT](https://img.shields.io/badge/license-MIT-green)](LICENSE)

**Turn a messy folder of recipe files into clean, versioned markdown and a single-file recipe viewer you can share privately, even to phones.**

recipify started with a real problem: a professional kitchen's recipe archive of almost 2,000 files collected over many years. It held text PDFs, scanned notebooks with handwriting, Word documents, spreadsheets, photos, EPUB cookbooks and the occasional corrupted file, mostly in Icelandic. recipify sorts that archive by how hard each file is to read, converts everything it can to markdown without overwriting anything, and builds one HTML file that chefs can open on any device to search the collection.

**[Live demo](https://steinnhauser.github.io/recipify/demo/)** (built from the sample recipes in [`examples/`](examples/recipes))

<p align="center">
  <img src="docs/screenshot-desktop.png" alt="recipify viewer on desktop: recipe list, filters and a recipe" width="72%">
  &nbsp;
  <img src="docs/screenshot-mobile.png" alt="recipify viewer on a phone" width="22%">
</p>

## Highlights

- **Sorts files by how hard they are to extract.** Each file gets a category: readable PDFs, scanned PDFs, Word documents, images, spreadsheets, legacy Office files, EPUB books, empty or corrupted files. This decides which files are free to process and which need paid OCR.
- **Converts locally first.** pypdf, python-docx, openpyxl, LibreOffice and a standard-library EPUB reader handle everything that has a text layer. Only scans and photos go to OCR (Mistral), or to a vision model through `register`.
- **Never overwrites output.** Every run writes a complete, timestamped output tree with a `metadata.json` snapshot and a `CHANGELOG.md`. Unchanged files (same SHA-256) are carried forward rather than converted again, so no OCR call is ever paid for twice. Original files are never modified.
- **Scores quality and flags files for review.** A heuristic accuracy score (non-words, broken spacing, mojibake, very short text) puts weak extractions on a manual-review list.
- **Adds labels.** Titles, course, dish, diet, cuisine and main ingredients are detected with transparent heuristics (Icelandic and English), with manual overrides in `curation.json`. Cleanup steps (`tidy`, `spelling`) each produce a new version, so the raw extraction is always kept.
- **One HTML file with no dependencies.** The viewer has instant diacritic-insensitive search, filters with live counts, favourites, per-recipe notes, printing, a resizable split view and a focus mode. Everything is embedded in the file and it works offline.
- **Readable even without JavaScript.** iOS and macOS open local HTML files in Quick Look, which doesn't run scripts. The recipes are therefore written into the page as plain HTML with a course index, and the script builds the interactive app on top of that wherever JavaScript runs.
- **Private sharing on a public host.** `recipify lock` encrypts the viewer (AES-256-GCM, PBKDF2-SHA256), and GitHub Pages serves it. The key goes in the link's `#fragment`, which browsers never send to the server.

## How it works

```text
recipes/ ──classify──▶ process / register ──▶ outputs/<run-id>/
   │                      (local extractors,     ├── metadata.json   full snapshot: sources, versions, quality, labels
   │                       OCR, vision)          ├── CHANGELOG.md    summary + "needs manual review"
   │                                             └── <category>/<slug>.md
   ├─ sort    copy into sorted/<category>/ (originals untouched)
   └─ rename  write rename_plan.sh to review (nothing is renamed)

outputs/ ──enrich / tidy / spelling──▶ new versions (raw always kept)
outputs/ ──build──▶ viewer (single HTML) ──lock──▶ site/index.html (encrypted) ──▶ GitHub Pages
```

| Category | Processing |
| --- | --- |
| `readable_pdfs` | local text extraction (pypdf) |
| `docx_files` | local conversion (python-docx: headings, lists, tables) |
| `image_based_pdfs`, `image_files` | Mistral OCR, or a vision transcription stored with `register` |
| `spreadsheets` | openpyxl (`.xls` via LibreOffice), one markdown table per sheet |
| `legacy_office` (`.doc`, `.odt`, `.pptx`) | LibreOffice headless conversion |
| `epub_books` | standard-library EPUB reader |
| `empty_or_corrupted`, `ignored`, `other_formats` | skipped, with the reason recorded |

## Quick start

Requires Python 3.12+ and [uv](https://docs.astral.sh/uv/).

```bash
git clone https://github.com/steinnhauser/recipify.git && cd recipify
uv sync
uv run recipify demo --out demo.html     # build the viewer from the sample recipes
open demo.html                           # or double-click it
```

### Processing your own collection

Put your files in `recipes/` (it is git-ignored, along with all outputs). Then run:

```bash
uv run recipify classify                         # summary table of categories
uv run recipify process -c docx_files            # convert locally (free)
uv run recipify process -c image_files --limit 5 # OCR, needs MISTRAL_API_KEY in .env
uv run recipify enrich                           # titles + labels (new version)
uv run recipify tidy && uv run recipify spelling # reader-ready text (new versions)
uv run recipify build                            # viewer/vNNN/recipes.html
```

`process` converts only new or changed files; `--force` makes a new version of everything. To store a transcription made outside the pipeline (for example by a vision model), use `uv run recipify register SOURCE... --markdown file.md --processor <name> [--accuracy 0-1]`. `uv run recipify --help` lists every command.

## Sharing privately with GitHub Pages

The plain viewer is never committed. Instead:

```bash
echo 'ENCRYPTION_KEY="<a long random string>"' >> .env
uv run recipify lock path/to/recipes.html --show-link \
    --base-url https://<user>.github.io/<repo>/  # writes site/index.html (encrypted), prints the share link
git add site/index.html && git commit -m "Update collection" && git push
```

Pushing triggers [`pages.yml`](.github/workflows/pages.yml). It refuses to publish any root page that isn't encrypted, checks that the page opens with the `ENCRYPTION_KEY` repository secret (if set), builds the public demo and deploys.

When someone opens the link, the page takes the key out of the address bar, decrypts in the browser with WebCrypto and remembers the key on that device. Visitors without the key see a key prompt.

**What this protects:** the recipe text on GitHub, in the repository and in the Pages site, which only ever hold ciphertext. **What it doesn't:** anyone you send the link to can forward it. To revoke access, change the key, run `lock` again, push, and send the new link.

## Design decisions

- **Versioned output trees instead of in-place updates.** Every run is a complete, self-contained snapshot, so you can always compare versions, roll back, and see when and how each file was converted. Carrying unchanged files forward keeps runs cheap.
- **Local-first, cost-aware OCR.** Paid OCR only runs when explicitly asked for (`-c image_files`, `--limit`). Everything with a text layer is converted for free.
- **Single-file HTML over PDF or Excel.** PDF only offers basic find-in-page and Excel is poor for long free text on a phone. One HTML file gives real search and filters, opens anywhere, and can be emailed.
- **Progressive enhancement.** The page is plain HTML first, so it stays readable in previews that don't run scripts (iOS Quick Look, Mail and Messages attachments).
- **Heuristics over a black box.** Labels and quality scores come from readable rules ([`labels.py`](src/recipify/labels.py), [`quality.py`](src/recipify/quality.py)) and can be overridden by hand, which matters when people rely on diet labels.

## Project layout

```text
src/recipify/
  cli.py                 Typer CLI (classify, sort, rename, process, register, enrich, tidy, spelling, build, demo, lock)
  classify.py            category detection (PDF text layer, file signatures, empty/corrupt files)
  extractors/            pdf, docx, office (openpyxl / LibreOffice), epub, ocr (Mistral)
  pipeline.py            runs, carry-forward versioning, processing
  metadata.py            metadata.json schema and snapshots
  quality.py             language detection and accuracy heuristics
  labels.py, tidy.py, spelling.py   enrichment and cleanup passes
  viewer.py              viewer builder (+ viewer_template.html)
  lock.py                encryption for publishing (+ locked_template.html)
examples/recipes/        sample recipes for the demo (one folder per course)
site/                    published to GitHub Pages (encrypted collection; demo built in CI)
```

## Development

```bash
uv sync
uv run pytest
uv run ruff check src tests && uv run ruff format --check src tests
uv run mypy src
```

CI runs all of these on Python 3.12 and 3.13.

## License

[MIT](LICENSE). The sample recipes in `examples/` were written for this project. Recipes you process remain the property of their authors.
