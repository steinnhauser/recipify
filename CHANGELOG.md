# Changelog

## 0.3.0

recipify is now a staged pipeline that verifies every recipe it publishes.

- **Stages with stored artifacts.** Inventory, extract, structure, assess and publish are separate stages. Each writes typed JSON artifacts keyed by the source's SHA-256 and the engine version, and a run log. These replace the full-copy output trees.
- **Structured recipes.** A deterministic structurer splits each document into components with ingredients, parsed quantities, method steps and notes, and keeps the source's own labels. An LLM structurer (Mistral, JSON schema) is available as an opt-in fallback.
- **Word-for-word verification.** A recipe is published only when every word and number of the source appears in it and nothing was added, its reading order agrees between two extraction modes, and it has a real ingredient list and method. Everything else goes to `review` or `excluded`, with reasons in `report.md`.
- **Better extraction.** PDFs are read with poppler in content-stream order, which keeps the components of multi-column recipes together. Word documents are read from the XML, including text boxes.
- **Triage.** Books, collections, course material, menus and other kitchen paperwork are recognised and held back. Identical copies and `.docx`/`.pdf` twins are merged.
- **New viewer.** Recipes are shown in components, with aligned quantities, scaling from ½× to 4×, ticking off ingredients and steps, a full-screen reading view on phones, and dark mode.
- **Real sample documents.** The demo is built by running the pipeline on generated Word, PDF, image and spreadsheet files.
- **Removed:** `sort`, `rename`, `tidy`, `spelling`, the EPUB extractor and the pypdf and markdown-it-py dependencies.

## 0.2.0

Versioned markdown output, local extractors, OCR, labels, the single-file viewer and encrypted publishing.
