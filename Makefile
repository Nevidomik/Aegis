UV_CACHE_DIR ?= /tmp/aegis-uv-cache

.PHONY: sync lock lock-check lint format test check

sync:
	UV_CACHE_DIR=$(UV_CACHE_DIR) uv sync --locked --all-packages --all-extras

lock:
	UV_CACHE_DIR=$(UV_CACHE_DIR) uv lock

lock-check:
	UV_CACHE_DIR=$(UV_CACHE_DIR) ./.venv/bin/uv lock --check

lint:
	./.venv/bin/ruff check .

format:
	./.venv/bin/ruff format .

test:
	./.venv/bin/pytest

check:
	UV_CACHE_DIR=$(UV_CACHE_DIR) ./.venv/bin/uv lock --check
	./.venv/bin/ruff check .
	./.venv/bin/ruff format --check .
	./.venv/bin/pytest
