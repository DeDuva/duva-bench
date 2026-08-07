.DEFAULT_GOAL := help
PY ?= python3

.PHONY: help setup lint fmt types test test-contract check clean

help: ## Show this help
	@grep -hE '^[a-zA-Z_-]+:.*?## ' $(MAKEFILE_LIST) | \
		awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-16s\033[0m %s\n", $$1, $$2}'

setup: ## Editable install with dev extras
	$(PY) -m pip install -e ".[dev]"

lint: ## Lint with ruff
	$(PY) -m ruff check src tests

fmt: ## Format with ruff
	$(PY) -m ruff format src tests
	$(PY) -m ruff check --fix src tests

types: ## Type-check with mypy
	$(PY) -m mypy

test: ## Run the suite, excluding tests that need a live dependency
	$(PY) -m pytest -m "not contract and not harbor"

# Kept separate and never folded into `test`: these need a live ADP, and a suite
# that silently skips when the dependency is missing reports a pass and an
# untested path with the same exit code.
test-contract: ## Run contract tests against a live ADP (needs DUVA_ADP_BASE_URL and both tokens)
	@test -n "$$DUVA_ADP_BASE_URL" || { echo "DUVA_ADP_BASE_URL is not set"; exit 1; }
	@test -n "$$DUVA_ADP_RUNNER_TOKEN" || { echo "DUVA_ADP_RUNNER_TOKEN is not set"; exit 1; }
	@test -n "$$DUVA_ADP_GRADER_TOKEN" || { echo "DUVA_ADP_GRADER_TOKEN is not set"; exit 1; }
	$(PY) -m pytest -m contract

check: lint types test ## Lint, type-check, and test

clean: ## Remove build and tool caches
	rm -rf build dist .pytest_cache .ruff_cache .mypy_cache htmlcov .coverage
	find . -name __pycache__ -type d -prune -exec rm -rf {} +
	find . -name '*.egg-info' -type d -prune -exec rm -rf {} +
