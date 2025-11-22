.PHONY: install lint typecheck test test-cov cov check clean mutation-init mutation mutation-report mutation-html typemut typemut-report typemut-html

install: ## Install all dependency groups
	uv sync --all-groups

lint: ## Run ruff linter
	uv run ruff check invariants/

lint-fix: ## Run ruff linter with auto-fix
	uv run ruff check --fix invariants/

typecheck: ## Run mypy type checking
	uv run mypy invariants/ tests/

test: ## Run all tests
	uv run pytest

test-cov: ## Run tests with coverage
	uv run pytest --cov=invariants

cov: test ## Open HTML coverage report
	open htmlcov/index.html

check: lint typecheck test ## Run lint, typecheck, and tests

mutation-init: ## Initialize mutation testing session
	@uv run cosmic-ray init cosmic-ray.toml mutation.sqlite --force
	@uv run cr-filter-operators mutation.sqlite cosmic-ray.toml
	@uv run cr-filter-pragma mutation.sqlite
	@uv run python tools/cr_filter_annotations.py mutation.sqlite

mutation-run: ## Run mutation testing
	uv run cosmic-ray exec cosmic-ray.toml mutation.sqlite

mutation-report: ## Show mutation testing report
	uv run cr-report mutation.sqlite

mutation-html: ## Generate HTML mutation report
	uv run cr-html mutation.sqlite > mutation-report.html
	open mutation-report.html

typemut: ## Run type mutation testing (typemut)
	uv run --group test typemut run

typemut-report: ## Show typemut terminal report
	uv run --group test typemut report

typemut-html: ## Generate typemut HTML report
	uv run --group test typemut html --open

clean: ## Remove cache and build artifacts
	find . -type d -name __pycache__ -exec rm -rf {} +
	find . -type d -name .mypy_cache -exec rm -rf {} +
	find . -type d -name .pytest_cache -exec rm -rf {} +
	find . -type d -name .ruff_cache -exec rm -rf {} +
	rm -rf dist/ build/ *.egg-info
	rm -f mutation.sqlite mutation-report.html typemut.sqlite typemut-report.html

help: ## Show this help
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | sort | awk 'BEGIN {FS = ":.*?## "}; {printf "\033[36m%-15s\033[0m %s\n", $$1, $$2}'

.DEFAULT_GOAL := help
