.DEFAULT_GOAL := help
.PHONY: help install requirements lint format test run classes eval eval-hybrid eval-llm-only docker-build docker-run clean

# Parametry (nadpisz: make eval MODE=llm_only LIMIT=10 MODEL=nazwa)
MODE ?=
MODEL ?=
LIMIT ?=
WORKERS ?= 4
# Wyniki każdego przebiegu: results/<timestamp>/ (raport JSON, log, dump per dokument)
RUN_DIR := $(or $(RUN_DIR),results/$(shell date +%Y%m%d-%H%M%S))
SHELL := /bin/bash
.SHELLFLAGS := -o pipefail -c
EXTRA = $(if $(MODE),--mode $(MODE)) $(if $(MODEL),--model $(MODEL)) --workers $(WORKERS)

help: ## Lista komend
	@grep -E '^[a-zA-Z_-]+:.*?## ' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "} {printf "  %-16s %s\n", $$1, $$2}'

install: ## Zależności (uv sync)
	uv sync

requirements: ## Wygeneruj requirements.txt z uv.lock (wymóg dostawy organizatora)
	uv export --no-dev --no-hashes --no-emit-project -o requirements.txt

lint: ## Ruff: sprawdzenie kodu i formatowania
	uv run ruff check .
	uv run ruff format --check .

format: ## Ruff: napraw i sformatuj kod
	uv run ruff check --fix .
	uv run ruff format .

test: ## Testy (pytest)
	uv run pytest -q

run: ## Przetwórz input/ do output/ (MODE=hybrid|llm_only)
	uv run python -m src run $(EXTRA)

classes: ## Wypisz wczytane klasy
	uv run python -m src classes

eval: ## F1 na data/dane (MODE, MODEL, LIMIT), wyniki do results/<timestamp>/
	@mkdir -p $(RUN_DIR)
	uv run python -m src eval $(EXTRA) $(if $(LIMIT),--limit $(LIMIT)) --out-json $(RUN_DIR)/report.json --dump $(RUN_DIR)/dump 2>&1 | tee $(RUN_DIR)/eval.log

eval-hybrid: ## F1 w trybie hybrid, raport i dump do results/<timestamp>/
	@mkdir -p $(RUN_DIR)
	uv run python -m src eval --mode hybrid --workers $(WORKERS) --out-json $(RUN_DIR)/hybrid.json --dump $(RUN_DIR)/dump-hybrid 2>&1 | tee $(RUN_DIR)/hybrid.log

eval-llm-only: ## F1 w trybie llm_only, raport i dump do results/<timestamp>/
	@mkdir -p $(RUN_DIR)
	uv run python -m src eval --mode llm_only --workers $(WORKERS) --out-json $(RUN_DIR)/llm_only.json --dump $(RUN_DIR)/dump-llm_only 2>&1 | tee $(RUN_DIR)/llm_only.log

docker-build: ## Zbuduj obraz
	docker compose build

docker-run: ## Uruchom run w kontenerze
	docker compose run --rm app run

clean: ## Usuń output/, trace/ i cache
	rm -rf output trace .pytest_cache
	find . -name __pycache__ -not -path './.venv/*' -prune -exec rm -rf {} +
