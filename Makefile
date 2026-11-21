.DEFAULT_GOAL := help
.PHONY: help install test run classes eval eval-hybrid eval-llm-only docker-build docker-run clean

# Parametry (nadpisz: make eval MODE=llm_only LIMIT=10 MODEL=nazwa)
MODE ?=
MODEL ?=
LIMIT ?=
WORKERS ?= 4
EXTRA = $(if $(MODE),--mode $(MODE)) $(if $(MODEL),--model $(MODEL)) --workers $(WORKERS)

help: ## Lista komend
	@grep -E '^[a-zA-Z_-]+:.*?## ' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "} {printf "  %-16s %s\n", $$1, $$2}'

install: ## Zależności (uv sync)
	uv sync

test: ## Testy (pytest)
	uv run pytest -q

run: ## Przetwórz input/ do output/ (MODE=hybrid|llm_only)
	uv run python -m src run $(EXTRA)

classes: ## Wypisz wczytane klasy
	uv run python -m src classes

eval: ## F1 na data/dane (MODE, MODEL, LIMIT)
	uv run python -m src eval $(EXTRA) $(if $(LIMIT),--limit $(LIMIT))

eval-hybrid: ## F1 w trybie hybrid, raport do docs/bench/
	uv run python -m src eval --mode hybrid --workers $(WORKERS) --out-json docs/bench/hybrid.json

eval-llm-only: ## F1 w trybie llm_only, raport do docs/bench/
	uv run python -m src eval --mode llm_only --workers $(WORKERS) --out-json docs/bench/llm_only.json

docker-build: ## Zbuduj obraz
	docker compose build

docker-run: ## Uruchom run w kontenerze
	docker compose run --rm app run

clean: ## Usuń output/, trace/ i cache
	rm -rf output trace .pytest_cache
	find . -name __pycache__ -not -path './.venv/*' -prune -exec rm -rf {} +
