.PHONY: lint format test check

lint:
  ruff check .

format:
  ruff format .

test:
  pytest

check:
  ruff check .
  ruff format --check .
  pytest