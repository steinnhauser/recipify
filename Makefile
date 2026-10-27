.PHONY: metadata-list check

metadata-list:  ## transcriptions of scans and photos, least certain first (also data/transcriptions.md)
	uv run recipify catalog
	uv run recipify transcriptions --out data/transcriptions.md

check:  ## everything CI runs, except the browser tests
	uv run ruff check src tests examples && uv run ruff format --check src tests examples
	uv run mypy src
	uv run pytest --cov
