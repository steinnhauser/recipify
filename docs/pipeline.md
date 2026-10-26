# Pipeline design

This document explains how recipify decides that a recipe can be trusted, and how it stores progress so that expensive work is never repeated. The [README](../README.md) gives the overview.

## Goals

1. **Faithful.** A published recipe says exactly what its source document says, with nothing lost, corrected or invented, laid out so it is as easy to follow as the original.
2. **Honest about difficulty.** Some documents are easy wins (a Word file or a PDF exported from one). Others need OCR, are whole books, or are not recipes at all. The pipeline sorts them and says why.
3. **Cheap to re-run.** Every key step is stored. Re-running skips finished work, and paid work (OCR, LLM calls, hand transcriptions) is never done twice.

## Artifacts and caching

```text
data/
  inventory.json                          every source file: sha256, category, kind, pages, copies
  extractions/<sha256>/poppler@v2.json    text per document and engine version
  extractions/<sha256>/vision-transcription@v1.json
  recipes/<sha256>/rules@v1.json          structured recipe per structurer version
  catalog.json                            every unique document with its assessment
  report.md                               the human-readable summary and review list
  runs.jsonl                              one line per stage run: counts, seconds, API usage
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
- triages each document as a **recipe**, a **book** (EPUB, or more than 8 pages) or **reference** material (mise en place lists, menus, staff rules, cleaning plans, by name).

## Stage 2: extract

| Category | Engine | Notes |
| --- | --- | --- |
| PDF with a text layer | `poppler` | `pdftotext -raw` keeps the order in which the document was written. Word draws each column of a multi-column recipe in turn, so components stay together. `-layout` mode renders the same pages visually. |
| Word (`.docx`) | `python-docx` (own XML walker) | Reads text boxes (common in recipe templates; python-docx skips them), keeps soft line breaks, skips Word's duplicate fallback content, and doesn't repeat merged table cells. |
| `.doc`, `.odt`, `.pptx` | `libreoffice` | Converted to docx or PDF, then read as above. |
| Spreadsheets | `openpyxl` | One line per row. |
| Scans, photos | `mistral-ocr` (opt-in, paid), or `register` | A transcription made by hand or by a vision model can be stored with `recipify register`. |

**Reading-order check.** Every line from the raw extraction must appear, whole, in the layout rendering of the same pages. On the real archive the two agree on every line for 349 of 356 short PDFs. The rest are PDFs whose text is stored in fragments. They go to review rather than risking a recipe with lines in the wrong order.

## Stage 3: structure

[`structure/rules.py`](../src/recipify/structure/rules.py) reads a document as a sequence of components:

```text
[name]  [ingredient label]  ingredient lines  [method label]  steps  [notes]
```

The parser is a small state machine (`start`, `ingredients`, `method`) with a few explicit rules:

- **Quantities.** A line that starts with a quantity, or ends with one and a unit ("Chia seeds 250 g"), is an ingredient. Oven settings ("140°C, vifta 2"), dates and multiplications are not.
- **Component names.** A short line directly followed by a quantity is a component name (strong evidence). A short line followed by a list of bare ingredients and then a method label is one too (weak evidence). A short line followed by prose names a component that has only a method ("Scallop tartare / Each scallop is cut…").
- **Labels and notes.** The source's own labels ("Aðferð:", "Hráefni", "Method") are kept and shown as headings. "Geymsluþol: 4 dagar." becomes a note, even when the PDF wrapped it over two lines.
- **Wrapped lines.** Lines wrapped in the middle of a sentence are joined back into one step. Step numbers and bullets become list markers.
- **Dropped lines.** A title repeated at the top or after a page break is dropped, and recorded in `Recipe.dropped`.

The parser never edits text. Each source line ends up in exactly one place, which is what makes the fidelity check below meaningful.

[`structure/llm.py`](../src/recipify/structure/llm.py) is an opt-in fallback for layouts the rules can't follow:

- It calls Mistral with temperature 0 and a strict JSON schema generated from a pydantic model.
- The prompt asks it to copy every line verbatim.
- Its output gets no special trust: it goes through the same assessment, and when both a rules result and an LLM result exist for the same text, the catalog keeps whichever passes more checks, preferring the rules on a tie.

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
- gives different recipes that share a title ("Þorskur") their file or folder name, so they can be told apart in the list.

## Stage 5: publish

[`viewer.py`](../src/recipify/viewer.py) writes every ready recipe into one HTML page as plain markup: components, an ingredient list with parsed amounts in `data-` attributes, and numbered steps. The inline script turns that into the app. It adds search, filters, scaling, ticking off ingredients and steps, favourites and notes, and a full-screen reading view on phones. Without JavaScript, the page is still a complete, readable index.

[`lock.py`](../src/recipify/lock.py) encrypts the page with AES-256-GCM, using a key derived with PBKDF2-SHA256. The browser decrypts it with WebCrypto, using the key from the link's `#fragment`.

## What is not done yet

- **Scans and photos (325 documents).** The pipeline is ready (`extract --ocr`, `register`), but there is no text layer to check against. An OCR or vision transcription can only reach `review` until a person has checked it.
- **Books and collections.** They need splitting into single recipes before they can be checked one by one.
- **Spreadsheets.** Costing and yield sheets need a table-aware structurer.
