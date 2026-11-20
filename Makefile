PY := python
VENV := .venv

ifeq ($(OS),Windows_NT)
VENV_PY := $(VENV)/Scripts/python.exe
else
VENV_PY := $(VENV)/bin/python
endif

.PHONY: bootstrap fmt lint type test cov integration build audit docs check-docs docker db-up db-down clean

bootstrap:
	$(PY) -m venv "$(VENV)"
	"$(VENV_PY)" -m pip install --upgrade pip "setuptools>=75" wheel
	"$(VENV_PY)" -m pip install -e ".[dev]"

fmt:
	"$(VENV_PY)" -m ruff format .

lint:
	"$(VENV_PY)" -m ruff check .
	"$(VENV_PY)" -m ruff format --check .

type:
	"$(VENV_PY)" -m mypy src

test:
	"$(VENV_PY)" -m pytest

cov:
	"$(VENV_PY)" -m pytest --cov=src --cov-report=term-missing

integration:
	"$(VENV_PY)" -m pytest tests/integration

build:
	"$(VENV_PY)" -m pip wheel --no-deps --no-build-isolation --wheel-dir dist .

audit:
	uvx pip-audit --strict --disable-pip --require-hashes -r requirements.lock

docs:
	"$(VENV_PY)" scripts/generate_docs.py

check-docs:
	"$(VENV_PY)" scripts/generate_docs.py --check

db-up:
	docker compose -f deploy/docker-compose.yml up -d postgres

db-down:
	docker compose -f deploy/docker-compose.yml down -v

docker:
	docker build -t schemasentry:latest .

clean:
	rm -rf build dist .pytest_cache .mypy_cache .ruff_cache
