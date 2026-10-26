# Examples

These fictional recipes were written for this project. They show the pipeline on documents that look like a real kitchen archive, with no private data.

- `recipes/`: the recipes in a small markdown dialect. `# Title`, then intro lines. `## Name` starts a component, `### Aðferð:` or `### Method` labels its method, `- ` lines are ingredients, `1. ` or plain lines under a method label are steps, and `> ` lines are notes. A single-component recipe uses `## Ingredients` and `## Method`.
- `make_sources.py`: renders the markdown into the documents in `sources/`. It needs LibreOffice and poppler: `uv run python examples/make_sources.py`.
- `sources/`: the generated documents, committed so CI and the tests can run without LibreOffice.

| Document | What it exercises | Expected tier |
| --- | --- | --- |
| Word files with soft line breaks (`Bakery/`, `Drinks/`, `Restaurant/Sauces/`) | the docx XML walker | ready |
| `Restaurant/Desserts/Skyr cheesecake.docx` | an ingredient table | ready |
| `Restaurant/Mains/Cod with brown butter.docx` | headed components | ready |
| PDFs exported from Word (`Restaurant/Mains/`, `Sides/`, `Canapés/`, `Breakfast/`) | poppler extraction and the reading-order check | ready |
| `Restaurant/Eftirréttir/Skyr og bláber.pdf` | a two-column, three-component Icelandic recipe | ready |
| `Old/Plokkfiskur (1).pdf` | an exact copy | merged into its original |
| `Restaurant/Desserts/Chocolate mousse.pdf` | the PDF twin of a `.docx` | excluded (same recipe) |
| `Scans/Beetroot salad.png` | a photo | excluded (needs OCR) |
| `Kitchen handbook 2019.pdf` | a 14-page book | excluded (book) |
| `Missi listi.docx` | a mise en place list | excluded (reference) |
| `Costing - lamb shank.xlsx` | a costing sheet | review (spreadsheet) |

`uv run recipify demo --report report.md` runs the whole pipeline on them. [`tests/test_examples.py`](../tests/test_examples.py) checks every row of this table.
