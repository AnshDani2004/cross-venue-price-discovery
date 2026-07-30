.PHONY: install lint format format-check typecheck test check

install:
	python -m pip install -e ".[dev]"

lint:
	python -m ruff check .

format:
	python -m ruff format .

format-check:
	python -m ruff format --check .

typecheck:
	python -m mypy src

test:
	python -m pytest

check: lint format-check typecheck test
