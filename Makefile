# SPDX-License-Identifier: GPL-3.0-or-later
# `check` is hermetic so the pre-commit hook can run it on every commit;
# `check/full` adds the container suites.
#
# There is no target here that reaches a real UniFi controller or uses a real
# credential, and no acknowledgement variable is defined to unlock one. The
# `live/` targets below reach a throwaway application this repository starts
# itself, on loopback, from images pulled by digest. They are not that thing.
# See docs/contribution/README.md.

.DEFAULT_GOAL := help

SHELL := /usr/bin/env bash
.SHELLFLAGS := -eu -o pipefail -c


# Git-ignored scratch for the build assertion; targets that write here order it.
SCRATCH := .cache/scratch
$(SCRATCH):
	@mkdir -p $@
TMPDIR_BASE := $(patsubst %/,%,$(if $(TMPDIR),$(TMPDIR),/tmp))
# Keyed on the worktree name, so parallel worktrees do not share a farm.
TREE := $(notdir $(CURDIR))
FARM := $(TMPDIR_BASE)/ansible-unifi-network/$(TREE)
COLLECTION := $(FARM)/ansible_collections/abn/unifi_network

UV := uv run --no-sync --locked

# Listed explicitly, so the farm cannot accumulate stale files that get linted.
COLLECTION_CONTENT := galaxy.yml meta plugins tests changelogs docs README.md LICENSE

ANSIBLE_TEST := ansible-test
GALAXY_BUILD := ansible-galaxy

.PHONY: init sync lane-setup collection/link \
  check check/full lint fmt test sanity integration \
  uos/up uos/down uos/purge uos/status uos/logs uos/shell uos/device \
  build docs/lint docs/build changelog/lint \
  hooks/install hooks/uninstall clean help

##@ Bootstrap

init: ## Install toolchain, hooks, and the staged collection path
	@printf '\n  Installing Go-based validators (okf)\n'
	@GOBIN=$${GOBIN:-$$HOME/.local/bin} GOTOOLCHAIN=auto go install github.com/okfcli/okf/cmd/okf@latest
	@printf '\n  Syncing Python tooling environment\n'
	uv sync --locked
	@printf '\n  Installing pre-commit hooks\n'
	$(UV) pre-commit install
	@printf '\n  Materializing the collection path ansible-test requires\n'
	@$(MAKE) --no-print-directory collection/link
	@printf '\n  Ready. Run `make check`.\n\n'

sync: ## Refresh the locked Python tooling environment
	uv sync --locked

# A fresh worktree has no .venv, and `uv run --no-sync` needs one.
lane-setup: sync collection/link ## Prepare this worktree to run the gates
	@printf '  worktree ready. Run make check.\n\n'

# ansible-test enumerates through git, so a tree inside this repository, or a
# symlink, reports "All targets skipped" and checks nothing.
collection/link: ## Stage the collection where ansible-test requires it
	@rm -rf $(COLLECTION)
	@mkdir -p $(COLLECTION)
	@cp -a $(COLLECTION_CONTENT) $(COLLECTION)/
	@printf '  staged %s\n' '$(COLLECTION)'

##@ Quality gates

check: lint changelog/lint docs/lint ## Fast hermetic gates: hooks, lint, changelog, docs (no containers)
	$(UV) pre-commit run --all-files
	@printf '\n  check: OK\n'

check/full: check sanity test integration ## Everything CI runs, including containerised suites

lint: collection/link ## Lint without autofixing
	$(UV) ruff check --no-fix .
	@printf '\n  ty\n'
	# The farm, not $(COLLECTION): an import of ansible_collections.abn.unifi_network
	# resolves only against the directory that *contains* ansible_collections.
	$(UV) ty check --extra-search-path $(FARM)
	@printf '\n  ansible-lint\n'
	$(UV) ansible-lint

fmt: ## Apply formatting and safe lint fixes
	$(UV) ruff check --fix .
	$(UV) ruff format .
	@printf '\n  formatting applied. Re-run `make check`.\n\n'

##@ Tests

# `--docker` fails on some hosts and `--local` has no pytest, so the default
# mode, which bootstraps its own venv, is the local path. CI isolates with
# containers.
ANSIBLE_TEST_LOCAL := --python 3.12 --requirements --color yes

sanity: collection/link ## ansible-test sanity (validate-modules, pep8, pylint, import, ...)
	cd $(COLLECTION) && $(ANSIBLE_TEST) sanity --color yes

test: collection/link ## Unit tests
	cd $(COLLECTION) && $(ANSIBLE_TEST) units $(ANSIBLE_TEST_LOCAL)

integration: collection/link ## Integration tests
	# The farm is on the collections path: the target drives the module by its
	# fully qualified name, and ansible-test resolves that against the directory
	# containing ansible_collections rather than against the collection itself.
	cd $(COLLECTION) && ANSIBLE_COLLECTIONS_PATH=$(FARM) $(ANSIBLE_TEST) integration $(ANSIBLE_TEST_LOCAL)

##@ Build and docs

# Two checks: no git-ignored path ships in the artifact, and no tracked path is
# declared in build_ignore. Both derive from git and galaxy.yml, so a new
# development path needs no change here.
build: | $(SCRATCH) ## Build the Galaxy artifact and assert its contents
	@rm -rf build
	$(GALAXY_BUILD) collection build --force --output-path build/
	@printf '\n  verifying artifact contents\n'
	@tar tzf build/*.tar.gz | sort -u > $(SCRATCH)/artifact.txt
	@git ls-files --others --ignored --exclude-standard --directory \
		| sort -u > $(SCRATCH)/ignored.txt
	@uv run --no-sync python -c "import sys, yaml; \
print('\n'.join(yaml.safe_load(open('galaxy.yml'))['build_ignore']))" \
		> $(SCRATCH)/excluded.txt
	@: > $(SCRATCH)/leaked.txt
	@grep -F -f $(SCRATCH)/ignored.txt $(SCRATCH)/artifact.txt \
		>> $(SCRATCH)/leaked.txt < /dev/null || true
	@if [ -s $(SCRATCH)/leaked.txt ]; then \
		printf '\n  BUILD LEAKED development paths. Ignore them in git or galaxy.yml:\n'; \
		sed 's|^|    |' $(SCRATCH)/leaked.txt; \
		exit 1; \
	fi; \
	size=$$(du -m build/*.tar.gz | cut -f1); \
	if [ "$$size" -gt 20 ]; then \
		printf '\n  BUILD is %s MB, over the 20 MB Galaxy limit\n' "$$size"; exit 1; \
	fi; \
	printf '  artifact clean, %s MB\n\n' "$$size"

# Overridable so CI can pin the linter via uvx without installing the dev lock.
ANTSIBULL_DOCS ?= $(UV) antsibull-docs

docs/lint: ## Lint collection documentation
	$(ANTSIBULL_DOCS) lint-collection-docs . --plugin-docs --skip-rstcheck --no-check-extra-docs-refs

docs/build: ## Build the HTML docsite into built-docs/
	@mkdir -p built-docs
	cd built-docs && $(UV) antsibull-docs sphinx-init --use-current --squash-hierarchy \
		abn.unifi_network --dest-dir . --fail-on-error
	@printf '\n  docsite build scaffolded in built-docs/\n'

changelog/lint: ## Lint changelog fragments
	$(UV) antsibull-changelog lint

##@ Hooks

hooks/install: ## Install the pre-commit hook
	$(UV) pre-commit install

hooks/uninstall: ## Remove the pre-commit hook
	$(UV) pre-commit uninstall

##@ Throwaway controller

# Everything in this section runs against a UniFi OS Server that this repository
# starts in a virtual machine, on loopback. Nothing here can reach a controller
# the operator administers: the VM is disposable, only the console and inform
# ports are forwarded, and both are bound to 127.0.0.1.
#
# It exists for one reason. A mock encodes the expectations of whoever wrote it, so
# a suite against a mock proves the collection agrees with us. This stack is the
# application itself, so a module that sends a wrong field name or assumes a
# response shape is wrong gets told so by the real thing.
#
# UniFi OS Server rather than the legacy Network Server because an integration key
# and the official API exist only there, and because a console rate-limits logins
# to about four in a window, so the suite authenticates with a key.
UOS := tests/live/stack-uos/uos.sh

uos/up: ## Start the console, install it, and mint a key
	@$(UOS) up

uos/down: ## Stop the console, keeping its disk
	@$(UOS) down

uos/purge: ## Delete the console and everything in it
	@$(UOS) purge

uos/status: ## Show the console's health
	@$(UOS) status

uos/logs: ## Follow the console's log
	@$(UOS) logs

uos/device: ## Start the emulated device and adopt it
	@$(UOS) device

uos/shell: ## Open a shell in the console's VM
	@$(UOS) shell

# Skips rather than fails when the console is not answering or no key has been
# minted, because a suite that could not run and a suite that ran and failed are
# different states and only one of them is a defect.
live/test: collection/link ## Run the live tests against the throwaway console
	cd $(COLLECTION) && PYTHONPATH=$(FARM) $(UV) --project $(CURDIR) python -m pytest \
		tests/live -q -p no:cacheprovider

##@ Utilities

clean: ## Remove build and test output
	rm -rf build/ built-docs/ tests/output/ .cache/ .ruff_cache/ .pytest_cache/
	rm -rf $(FARM)
	find . -name __pycache__ -type d -prune -exec rm -rf {} +

help: ## Show this help
	@awk 'BEGIN {FS = ":.*##"; printf "\nUsage:\n  make \033[36m<target>\033[0m\n"} \
	  /^[a-zA-Z0-9_/-]+:.*?##/ { printf "  \033[36m%-20s\033[0m %s\n", $$1, $$2 } \
	  /^##@/ { printf "\n\033[1m%s\033[0m\n", substr($$0, 5) }' $(MAKEFILE_LIST)
