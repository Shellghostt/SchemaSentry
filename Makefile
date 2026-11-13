PY := python
VENV := .venv

.PHONY: bootstrap fmt lint type test cov build docker clean

bootstrap:
	$(PY) -m venv $(VENV)
	$(VENV)/Scripts/python -m pip install --upgrade pip 2>/dev/null || $(VENV)/bin/python -m pip install --upgrade pip
	$(VENV)/Scripts/python -m pip install -e ".[dev]" 2>/dev/null || $(VENV)/bin/python -m pip install -e ".[dev]"

fmt:
	$(VENV)/Scripts/python -m ruff format . 2>/dev/null || $(VENV)/bin/python -m ruff format .

lint:
	$(VENV)/Scripts/python -m ruff check . 2>/dev/null || $(VENV)/bin/python -m ruff check .

type:
	$(VENV)/Scripts/python -m mypy src 2>/dev/null || $(VENV)/bin/python -m mypy src

test:
	$(VENV)/Scripts/python -m pytest 2>/dev/null || $(VENV)/bin/python -m pytest

cov:
	$(VENV)/Scripts/python -m pytest --cov=src --cov-report=term-missing 2>/dev/null || $(VENV)/bin/python -m pytest --cov=src --cov-report=term-missing

docker:
	docker build -t schemasentry:latest .

clean:
	rm -rf build dist .pytest_cache .mypy_cache .ruff_cache
