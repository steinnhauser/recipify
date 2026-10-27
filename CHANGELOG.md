# Changelog

## 0.7.0

- **Editable recipes and export.** Pages built with `build --editable`, the demo and the new `recipify starter` (an editable file with a couple of sample recipes) let anyone add, edit and remove recipes and export the collection as a new file, named as they like with `.html` always added. Unsaved changes survive a reload; the export dialog lists them with an undo for each. Edited and added recipes say so and no longer claim to be checked against an original; unchanged recipes are exported byte for byte. Private collections are built without editing.
- **Browser tests** (`pytest -m browser`, own CI job): the editing and export flow in Chromium, file-name rules, and the ingredient parser compared with the pipeline's.

## 0.6.0

- **Spreadsheets.** Recipe workbooks are read sheet by sheet, each block of columns top to bottom (`openpyxl@v2`), and assessed like any other document. Costing tables (purchase prices, food cost) are set aside as dropped lines (`rules@v3`), and costing sheets count as kitchen paperwork.
- **Better splitting** (`pages@v2`). A cover and a table of contents are set aside as front matter, as are section headings above a recipe's heading. A collection is split when most of its parts are recipes, and the thin parts are assessed like any other. "recipe book" counts as a collection name.
- On the archive: 15 documents become 248 recipes, and 508 recipes are ready (up from 445).

## 0.5.0

- **Plug and play.** `recipify run <folder>` processes any folder of recipe files and writes the viewer. The words that steer triage and splitting moved out of the code into a `Vocabulary` with English and Icelandic defaults, which a collection extends in `curation.json`. The inventory records where its sources live, so `trace` finds them, and `lock` takes its publish URL from `--base-url` or `RECIPIFY_BASE_URL`.
- **Instructions between ingredients** (`rules@v2`). Short method lines written between ingredients ("soak", "mix this well", "bake at 175°C") now close their group of ingredients instead of being read as ingredients or component names. On the archive this moves 8 recipes from review to ready. `rules@v1` results stay on disk beside the new ones.

## 0.4.0

- **Split stage.** Documents that hold several recipes are split into one recipe per unit at their page breaks, in clear cases only. The document must be named as a collection, each recipe must start on a titled page, the parts must be recipes rather than fragments, and no two may be translations of each other. 10 documents become 106 recipes, and 439 recipes are now ready (up from 380). Every decision is stored with its reason, and `keep_whole` in `curation.json` overrides it.
- **Traceability.** Structured recipes are stored by the hash of their input text. Recipe IDs carry the unit number, and `recipify trace` follows a recipe back to its source file, re-checking every hash. The viewer names the page a recipe came from.
- Word extraction keeps explicit page breaks (`python-docx@v3`), and the report counts documents and recipes separately.

## 0.3.0

recipify is now a staged pipeline that verifies every recipe it publishes.

- **Stages with stored artifacts.** Inventory, extract, structure, assess and publish are separate stages. Each writes typed JSON artifacts keyed by the source's SHA-256 and the engine version, and a run log. These replace the full-copy output trees.
- **Structured recipes.** A deterministic structurer splits each document into components with ingredients, parsed quantities, method steps and notes, and keeps the source's own labels.
- **Word-for-word verification.** A recipe is published only when every word and number of the source appears in it and nothing was added, its reading order agrees between two extraction modes, and it has a real ingredient list and method. Everything else goes to `review` or `excluded`, with reasons in `report.md`.
- **Better extraction.** PDFs are read with poppler in content-stream order, which keeps the components of multi-column recipes together. Word documents are read from the XML, including text boxes.
- **Triage.** Books, collections, course material, menus and other kitchen paperwork are recognised and held back. Identical copies and `.docx`/`.pdf` twins are merged.
- **New viewer.** Recipes are shown in components, with aligned quantities, scaling from ½× to 4×, ticking off ingredients and steps, a full-screen reading view on phones, and dark mode.
- **Real sample documents.** The demo is built by running the pipeline on generated Word, PDF, image and spreadsheet files.
- **Scans are transcribed, not OCR'd.** `pages` writes page images and `register` stores the transcription as a new version, never overwriting one. Photos of plated dishes are recognised and excluded.
- **Progress history.** Every catalog run saves each document's tier, and `report.md` lists the changes since the previous run.
- **Removed:** the Mistral OCR and LLM integrations and the `mistralai` dependency, `sort`, `rename`, `tidy`, `spelling`, the EPUB extractor, and pypdf and markdown-it-py.

## 0.2.0

Versioned markdown output, local extractors, OCR, labels, the single-file viewer and encrypted publishing.
