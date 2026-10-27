# Pipeline design

This document explains how recipify decides that a recipe can be trusted, and how it stores progress so that expensive work is never repeated. The [README](../README.md) gives the overview.

## Goals

0. **Plug and play.** Anyone can drop an unorganised folder of recipe files into a directory and run `recipify run <folder>`. Nothing in the code knows about a particular archive. What a collection needs beyond the defaults (words in another language, its own name for photo folders, a decision about one document) goes in `curation.json`.

1. **Faithful.** A published recipe says exactly what its source document says, with nothing lost, corrected or invented, laid out so it is as easy to follow as the original.
2. **Honest about difficulty.** Some documents are easy wins (a Word file or a PDF exported from one). Others are scans that need a transcription, are whole books, or are not recipes at all. The pipeline sorts them and says why.
3. **Cheap to re-run.** Every key step is stored. Re-running skips finished work, and transcriptions of scans are never overwritten.

## Artifacts and caching

```text
data/
  inventory.json                          every source file: sha256, category, kind, pages, copies
  extractions/<sha256>/poppler@v2.json    text per document and engine version
  extractions/<sha256>/vision@v1.json     a registered transcription of a scan
  splits/<sha256>/poppler@v2/pages@v1.json  split decision per extraction and splitter version
  recipes/<unit sha256>/rules@v1.json     structured recipe, keyed by the hash of its input text
  catalog.json                            every unique document with its assessment
  report.md                               the human-readable summary and review list
  history/<time>.json                     every catalog run's tier per document (report.md lists the changes)
  runs.jsonl                              one line per stage run: counts and seconds
  curation.json                           manual overrides (titles, labels, kind, tier)
```

- **Keyed by content.** Artifacts are keyed by the source's SHA-256, so identical copies share one result and a renamed file keeps its results.
- **Versioned.** Every engine has a version. A change that alters output bumps it, and the new results are written beside the old ones instead of replacing them.
- **Costly results are protected.** They carry `costly: true` and are never recomputed automatically.
- **Typed.** The records are pydantic models ([`models.py`](../src/recipify/models.py)), written atomically, so a crash never leaves half an artifact behind.

## Stage 1: inventory

[`classify.py`](../src/recipify/classify.py) reads file content, not just names:

- A PDF is checked for a text layer with poppler.
- A `.pdf` that is really a zip is sniffed as Word or EPUB.
- Images are recognised by their magic bytes.

[`inventory.py`](../src/recipify/inventory.py) then:

- merges byte-identical copies, keeping the copy without "(2)" or "copy" in its path;
- triages each document as a **recipe**, a **book** (EPUB, or more than 8 pages), **reference** material (mise en place lists, menus, staff rules, cleaning plans, by name), or a **photo** of a plated dish (an image in a photo folder).

The words behind these decisions are in [`vocabulary.py`](../src/recipify/vocabulary.py): generic English and Icelandic defaults, which a collection extends in `curation.json`.

## Stage 2: extract

| Category | Engine | Notes |
| --- | --- | --- |
| PDF with a text layer | `poppler` | `pdftotext -raw` keeps the order in which the document was written. Word draws each column of a multi-column recipe in turn, so components stay together. `-layout` mode renders the same pages visually. |
| Word (`.docx`) | `python-docx` (own XML walker) | Reads text boxes (common in recipe templates; python-docx skips them), keeps soft line breaks, skips Word's duplicate fallback content, and doesn't repeat merged table cells. |
| `.doc`, `.odt`, `.pptx` | `libreoffice` | Converted to docx or PDF, then read as above. |
| Spreadsheets | `openpyxl` | One page per sheet. Columns separated by an empty column form blocks, read one after another, so two recipes laid out side by side stay apart; within a block a row reads across (quantity, ingredient, translation). Sheet names that say nothing ("1", "Sheet5") are left out. |
| Scans, photos of recipes | `register` | `recipify pages` writes the page images. A transcription made from them, by hand or with a vision model, is stored with `recipify register` as `<engine>@v<N>`, and is never overwritten. Photos of plated dishes (in folders such as `Myndir`) are recognised and excluded. |

**Reading-order check.** Every line from the raw extraction must appear, whole, in the layout rendering of the same pages. On the real archive the two agree on every line for 349 of 356 short PDFs. The rest are PDFs whose text is stored in fragments. They go to review rather than risking a recipe with lines in the wrong order.

## Stage 2b: split

Some documents hold several recipes: a cake collection, a box of confectionery recipes, a restaurant's Christmas menu. [`split.py`](../src/recipify/split.py) divides them into **units**, one recipe each, but only in clear cases. Everything else stays whole, with the reason recorded.

**When a document is split.** At its page breaks (PDF pages, or explicit page breaks in Word; Word's own layout breaks don't count), and only if all of these hold:

1. **Named as a collection.** The file name or title says so: "uppskriftir" (recipes), "kökur" (cakes), "tertur", "recipes". The pages of a plated dish are often its components (a sauce, a crumble, a garnish), laid out exactly like separate recipes. In practice the name was the only signal that told the two apart, so it is required.
2. **Each recipe starts on a titled page.** A page that starts a recipe opens with a title, over named components or over an ingredient list. A page that opens mid-sentence or with ingredients continues the recipe before it.
3. **Each part is a recipe, not a fragment:** at least 2 measured ingredients and 25 words.
4. **No translations.** No two parts may have exactly the same quantities, which would make them translations of each other (an Icelandic page and its English version).
5. **A repeated header names the recipes.** A header on every page must name the recipes; otherwise it is a category ("Sósur", sauces) and the document stays whole. A collection heading above the first recipe ("Brauð", a restaurant's "Jólauppskriftir", Christmas recipes) is set aside and recorded, so it doesn't become the first recipe's title.

**The invariant.** The words of all units, plus the header lines set aside, must equal the words of the document exactly. This is checked whenever a split is made. A document that is split wrongly can be kept whole in `curation.json` (`keep_whole`), and that decision is stored in the split artifact as well.

Front matter is set aside too: a cover (a title and little else) and a table of contents (lines that start or end with a page number), and a section heading above a recipe's own heading ("# Eftirréttir" over "## Skyrkaka") (`pages@v2`). Most parts must be recipes (75%, at least two); a thin part still becomes its own unit and is assessed like any other.

On the real archive, 15 documents are split, into 248 recipes. Of the rest, 105 multi-page documents stay whole because they aren't named as collections, which is the right call for plated dishes.

## Stage 3: structure

[`structure/rules.py`](../src/recipify/structure/rules.py) reads a document as a sequence of components:

```text
[name]  [ingredient label]  ingredient lines  [method label]  steps  [notes]
```

The parser is a small state machine (`start`, `ingredients`, `method`) with a few explicit rules:

- **Quantities.** A line that starts with a quantity, or ends with one and a unit ("Rolled oats 250 g"), is an ingredient. Oven settings ("140°C, vifta 2"), dates and multiplications are not.
- **Component names.** A short line directly followed by a quantity is a component name (strong evidence). A short line followed by a list of bare ingredients and then a method label is one too (weak evidence). A short line followed by prose names a component that has only a method ("Beetroot / The beetroots are baked whole…").
- **Labels and notes.** The source's own labels ("Aðferð:", "Hráefni", "Method") are kept and shown as headings. "Geymsluþol: 3 dagar." (shelf life) becomes a note, even when the PDF wrapped it over two lines.
- **Wrapped lines.** Lines wrapped in the middle of a sentence are joined back into one step. Step numbers and bullets become list markers.
- **Instructions between ingredients.** Bakery sheets often interleave short instructions with the ingredients: "Lagt í bleyti" (soak), "Þessu er hrært vel saman" (mix this well), "Bakað við 175°C í 40 mín". A line with a cooking verb and at least three words, or with a temperature or a time, closes the group of ingredients above it as its step. The source's order is kept: the viewer shows each group with its instruction (`rules@v2`).
- **Dropped lines.** A title repeated at the top or after a page break is dropped, and so is a costing table (from a header naming purchase prices or food cost to the end of the page): both are recorded in `Recipe.dropped` (`rules@v3`).

The parser never edits text. Each source line ends up in exactly one place, which is what makes the fidelity check below meaningful. It runs once per unit, and its result is stored under the SHA-256 of the unit's text. The same text always gives the same file, and a changed split or extraction gives a new file beside the old one.


## Stage 4: assess

[`assess.py`](../src/recipify/assess.py) computes, for every structured recipe:

- **Fidelity (recall).** The share of the source's words and numbers that the reader sees, counted as a multiset after case folding.
- **Precision.** The share of the shown words that occur in the source. A paraphrase, a correction or an invented quantity lowers it.
- **Reading-order agreement** from stage 2.
- **Text quality:** non-words, broken spacing and mojibake.
- **Structure:** at least two ingredients, at least two of them measured, and at least one step. Less than 40% of the words may sit outside the lists and steps.
- **Size:** at least 25 words. A document over 3,000 words is a collection, not one recipe.
- **Course material:** school assignments, with student and teacher names, are excluded.

A recipe is **ready** only if every check passes. Recall and precision must both be exactly 1.0.

The catalog then:

- merges *twins*, the same recipe saved as a `.docx` and as its PDF export (same title, at least 90% of words shared), keeping the Word file;
- gives different recipes that share a title ("Þorskur", cod) their file or folder name, so they can be told apart in the list.

## Traceability

Every recipe in the catalog can be followed back to its source file:

| Link | Stored in | Checked by `recipify trace` |
| --- | --- | --- |
| recipe (catalog entry) | `catalog.json`: id `<source sha12>[-<unit>]`, source, unit, pages, engine labels | |
| structured recipe | `recipes/<unit sha256>/rules@v1.json` | its input hash is the unit's hash, and it is the recipe in the catalog |
| unit | inside the split decision: page numbers, exact text, set-aside headers | its text hashes to its key, and every page of it occurs on those pages of the extraction |
| split decision | `splits/<sha256>/<extraction>/pages@v1.json` | decision and reasons are shown |
| extraction | `extractions/<sha256>/<engine>@v<N>.json` | it belongs to this source's hash |
| source file | `recipes/…` (and identical copies) | the file on disk still hashes to the recorded SHA-256 |

Nothing in this chain is overwritten. Each engine version and each input text gets its own file, and `history/` keeps every catalog run's tier per recipe, so a recipe's history can be compared across runs.

## Stage 5: publish

[`viewer.py`](../src/recipify/viewer.py) writes every ready recipe into one HTML page as plain markup: components, an ingredient list with parsed amounts in `data-` attributes, and numbered steps. The inline script turns that into the app. It adds search, filters, scaling, ticking off ingredients and steps, favourites and notes, and a full-screen reading view on phones. Without JavaScript, the page is still a complete, readable index.

[`lock.py`](../src/recipify/lock.py) encrypts the page with AES-256-GCM, using a key derived with PBKDF2-SHA256. The browser decrypts it with WebCrypto, using the key from the link's `#fragment`.

## What is not done yet

- **Scans (18 photographed recipe pages, plus 12 scanned PDFs).** `pages` and `register` are ready, but there is no text layer to check against, so a transcription stays in `review` until a person has checked it. Internal arithmetic can help: a scaling table whose columns are multiples of the first, and whose totals are sums, checks its own numbers.
- **Books and collections.** They need splitting into single recipes before they can be checked one by one.
- **Spreadsheets.** Costing and yield sheets need a table-aware structurer.
