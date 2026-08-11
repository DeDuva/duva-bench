.DEFAULT_GOAL := help
PY ?= python3

.PHONY: help setup lint fmt types test test-contract check check-docs clean sync-spec generate check-generated adp-stack adp-status

help: ## Show this help
	@grep -hE '^[a-zA-Z_-]+:.*?## ' $(MAKEFILE_LIST) | \
		awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-16s\033[0m %s\n", $$1, $$2}'

setup: ## Editable install with dev extras
	$(PY) -m pip install -e ".[dev]"

# Both halves of what CI runs, in one target. They were split before — `check`
# ran the linter and CI additionally ran `ruff format --check` — so a branch
# could pass the local gate and fail CI on formatting alone. A gate that is not
# the same gate as CI is a gate that teaches people to ignore it.
lint: ## Lint and check formatting with ruff
	$(PY) -m ruff check src tests tools scripts
	$(PY) -m ruff format --check src tests tools scripts

fmt: ## Format with ruff
	$(PY) -m ruff format src tests tools scripts
	$(PY) -m ruff check --fix src tests tools scripts

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

adp-stack: ## Bring up the dedicated ADP studies record into (see tools/adp-stack.sh)
	sh tools/adp-stack.sh up

adp-status: ## Is the dedicated ADP up, and at what contract version
	sh tools/adp-stack.sh status

check-docs: ## Assert CLAUDE.md still points at paths that exist
	sh tools/check-claude-md.sh

# Two stages, and only the first needs a YAML parser. See tools/sync_adp_spec.py.
sync-spec: ## Re-vendor ADP's openapi.yaml as JSON (needs ADP_SPEC=path)
	@test -n "$$ADP_SPEC" || { echo "ADP_SPEC is not set (path to ADP's spec/openapi.yaml)"; exit 1; }
	$(PY) tools/sync_adp_spec.py --source "$$ADP_SPEC"

generate: ## Regenerate the ADP client from the vendored spec
	$(PY) tools/generate_adp_client.py

check-generated: ## Fail if the generated client is stale against the vendored spec
	$(PY) tools/generate_adp_client.py --check

check: check-docs lint types check-generated test ## The gate. Same target name in every repo in this line of work.

clean: ## Remove build and tool caches
	rm -rf build dist .pytest_cache .ruff_cache .mypy_cache htmlcov .coverage
	find . -name __pycache__ -type d -prune -exec rm -rf {} +
	find . -name '*.egg-info' -type d -prune -exec rm -rf {} +
