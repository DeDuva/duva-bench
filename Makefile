.DEFAULT_GOAL := help

# M0 fills this in — `setup lint fmt types test` mirroring adp-replay's Makefile, per
# docs/execution-plan.md §2. `check` exists already so that the gate has the same name
# here as everywhere else from the first commit of real code, rather than being renamed
# into line later.
.PHONY: help check check-docs

help: ## Show this help
	@grep -hE '^[a-zA-Z_-]+:.*?## ' $(MAKEFILE_LIST) | \
		awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-16s\033[0m %s\n", $$1, $$2}'

check-docs: ## Assert CLAUDE.md still points at paths that exist
	sh tools/check-claude-md.sh

check: check-docs ## The gate. Same target name in every repo in this line of work.
