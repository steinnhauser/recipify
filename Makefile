# Everyday commands. `make` lists them.
#
# Collections live outside the repository, each in $(COLLECTIONS)/<name>/ with sources/,
# data/ and dist/. Pick one with C=<name> (default: personal). Settings for this machine
# (COLLECTIONS, SITE_URL) go in local.mk, which is git-ignored.

-include local.mk
COLLECTIONS ?= ../recipify-collections
SITE_URL ?=
C ?= personal
PORT ?= 8765

# The published collections: viewer title, the variable holding its key (in .env), its page.
PUBLISHED := kitchen personal
kitchen_TITLE := recipify
kitchen_KEY := ENCRYPTION_KEY
kitchen_PAGE := site/index.html
kitchen_URL := $(SITE_URL)/
personal_TITLE := Personal recipes
personal_KEY := PERSONAL_ENCRYPTION_KEY
personal_PAGE := site/personal/index.html
personal_URL := $(SITE_URL)/personal/

DIR = $(COLLECTIONS)/$(C)
RECIPIFY = uv run recipify --sources "$(DIR)/sources" --data "$(DIR)/data"
VIEWER = $(DIR)/dist/index.html

.DEFAULT_GOAL := help
.PHONY: help new build preview lock update kitchen personal pages verify link links report \
	serve publish metadata-list check test browser format demo examples

help:  ## list the commands
	@awk 'BEGIN {FS = ":.*## "} /^##@/ {printf "\n%s\n", substr($$0, 5)} \
		/^[a-z-]+:.*## / {printf "  make %-14s %s\n", $$1, $$2}' $(MAKEFILE_LIST)
	@echo; echo "  C=<collection> picks one (default: $(C)); collections in $(COLLECTIONS)"

##@ Recipes (C=personal by default; C=kitchen for the kitchen archive)

new:  ## start a recipe from the markdown template: make new T="Pad thai" [F=subfolder]
	@test -n "$(T)" || { echo 'Give a title: make new T="Pad thai"'; exit 1; }
	$(RECIPIFY) new "$(T)" --folder "$(F)"

build:  ## run every stage and write the collection's viewer to its dist/
	$(RECIPIFY) run --out "$(VIEWER)" --title "$($(C)_TITLE)"

preview: build  ## build, then open the viewer on http://127.0.0.1:8765/ (PORT=...; Ctrl+C stops)
	@echo "Preview: http://127.0.0.1:$(PORT)/"
	python3 -m http.server $(PORT) --bind 127.0.0.1 --directory "$(DIR)/dist"

report:  ## the collection's pipeline report (what is ready, what is held back and why)
	@cat "$(DIR)/data/report.md"

##@ Publishing (encrypted pages in site/, one key per collection)

lock:  ## encrypt the built viewer into its page in site/, and save its share link
	$(RECIPIFY) lock "$(VIEWER)" --key-env $($(C)_KEY) --out $($(C)_PAGE) \
		--base-url "$(if $(SITE_URL),$($(C)_URL))" --link-file "$(DIR)/share-link.txt"

update: build lock  ## build and lock one collection (C=...)

personal:  ## update the personal page (site/personal/)
	@$(MAKE) --no-print-directory update C=personal

kitchen:  ## update the kitchen page (site/)
	@$(MAKE) --no-print-directory update C=kitchen

pages: kitchen personal verify  ## update every published page, then verify them

verify:  ## check each page opens with its own key, and the personal page not with the kitchen key
	@for c in $(PUBLISHED); do \
		$(MAKE) --no-print-directory -s _verify C=$$c || exit 1; done
	@if uv run recipify lock --verify --out $(personal_PAGE) >/dev/null 2>&1; then \
		echo "$(personal_PAGE) opens with $(kitchen_KEY): the keys must differ"; exit 1; fi
	@echo "Keys are separate: $(personal_PAGE) does not open with $(kitchen_KEY)"

_verify:
	uv run recipify lock --verify --key-env $($(C)_KEY) --out $($(C)_PAGE)

link:  ## print the collection's share link (it holds the key: share it with care)
	@cat "$(DIR)/share-link.txt"

links:  ## (re)write every share link from the keys in .env (a page changes only if its viewer did)
	@for c in $(PUBLISHED); do $(MAKE) --no-print-directory C=$$c lock || exit 1; done

serve:  ## serve site/ (the locked pages, and the demo after `make demo`) on 127.0.0.1:8765 (PORT=...)
	@echo "Locked pages: http://127.0.0.1:$(PORT)/ and http://127.0.0.1:$(PORT)/personal/ (add #key=...)"
	python3 -m http.server $(PORT) --bind 127.0.0.1 --directory site

publish: pages  ## update every page, verify, and commit the changed ones (pushing stays manual)
	@git add $(foreach c,$(PUBLISHED),$($(c)_PAGE))
	@if git diff --cached --quiet -- $(foreach c,$(PUBLISHED),$($(c)_PAGE)); then \
		echo "No page changed: nothing to commit"; \
	else \
		git commit -m "chore: update the published collections" -- \
			$(foreach c,$(PUBLISHED),$($(c)_PAGE)) && git log --oneline -1; fi

metadata-list: C = kitchen
metadata-list:  ## transcriptions of scans and photos, least certain first (also data/transcriptions.md)
	$(RECIPIFY) catalog
	$(RECIPIFY) transcriptions --out "$(DIR)/data/transcriptions.md"

##@ Development

check:  ## everything CI runs, except the browser tests
	uv run ruff check src tests examples && uv run ruff format --check src tests examples
	uv run mypy src
	uv run pytest --cov

test:  ## the unit tests with coverage (100% required)
	uv run pytest --cov

browser:  ## the viewer tests in Chromium
	uv run pytest -m browser

format:  ## format and auto-fix the code
	uv run ruff format src tests examples && uv run ruff check --fix src tests examples

demo:  ## the whole pipeline on the sample documents, written to site/demo/ (see `make serve`)
	uv run recipify demo --report site/demo/report.md

examples:  ## regenerate examples/sources from examples/recipes (needs LibreOffice)
	uv run python examples/make_sources.py
