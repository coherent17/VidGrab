# VidGrab developer task runner (Linux / macOS).
# Windows: use scripts\build.ps1 or scripts\build.bat instead.

SHELL       := /bin/bash
.SHELLFLAGS := -e -o pipefail -c
.ONESHELL:
VENV        := .venv
PY          := $(VENV)/bin/python
PIP         := $(VENV)/bin/pip

.PHONY: setup run lint test build clean

setup: ## create venv + install runtime & dev deps (one-time)
	python3 -m venv $(VENV)
	$(PIP) install --upgrade pip -q
	$(PIP) install -r requirements-dev.txt -q

run: ## launch the GUI (auto-setup on first use)
	@[ -x $(PY) ] || $(MAKE) setup
	$(PY) -m vidgrab

lint: ## ruff over the source
	@[ -x $(PY) ] || $(MAKE) setup
	$(PY) -m ruff check vidgrab tests scripts

test: ## full pytest suite incl. headless GUI smoke test
	@[ -x $(PY) ] || $(MAKE) setup
	SMOKE_GUI=1 QT_QPA_PLATFORM=offscreen $(PY) -m pytest -v

build: ## build the self-contained Linux binary
	@[ -x $(PY) ] || $(MAKE) setup
	$(PY) scripts/generate_icon.py
	$(PY) -m PyInstaller VidGrab.spec --noconfirm

clean: ## remove build artifacts and caches
	rm -rf build dist .pytest_cache .ruff_cache
	find . -type d -name __pycache__ -prune -exec rm -rf {} +