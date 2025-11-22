# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project

Invariants is a Python library for splitting entity invariants into separate type-safe state classes using Pydantic. It enforces constraints via a custom metaclass (`StateMeta`): root states declare fields as `Statefull` (abstract marker), child states must override all `Statefull` fields with concrete types, and cannot add new fields. All states are frozen/immutable.

Optional factory support bridges Pydantic states with Polyfactory (`StateFactory`) and SQLAlchemy ORM models (`SQLAlchemyStateFactory`). XState integration generates visualizable state machine diagrams from Python type annotations.

## Commands

```bash
# Install with all dev groups
uv sync --all-groups

# Run all tests
uv run pytest

# Run a single test
uv run pytest tests/test_state.py::TestStateErrors::test_name

# Type checking (run on both app and tests)
uv run mypy invariants/ tests/

# Linting
uv run ruff check invariants/

# Run all checks (lint + typecheck + tests)
make check

# XState: print generated JS code
uv run python -m invariants.viz print examples.example

# XState: start visualizer (auto-clones nkhitrov/xstate-display, requires yarn/node)
uv run python -m invariants.viz serve examples.example
```

## Architecture

### Core: `invariants/state.py`

- **`Statefull`** — Marker type for abstract fields. At runtime it's a class with `__get_pydantic_core_schema__` (returns `any_schema()`); under `TYPE_CHECKING` it aliases `Any` so mypy allows child overrides with any concrete type.
- **`StateMeta`** — Metaclass extending Pydantic's `ModelMetaclass`. Enforces at class creation: child states cannot add new fields, and must override all `Statefull` fields with concrete types.
- **`State`** — Base class (`BaseModel` + `StateMeta`). Frozen, strict. A `model_validator(mode="before")` prevents instantiation if the class still has `Statefull` fields.

- **`StateMachine[T]`** — Generic abstract base for commands/queries over a state hierarchy `T`. The `execute` method's type signature (`input → output`) defines valid state transitions.

Class hierarchy: `State` (root) → root child (declares `Statefull` fields) → concrete state (overrides all `Statefull` fields). The metaclass validation triggers on the concrete level (`is_base_state` check).

### Validators: `invariants/conditions.py`

`ContainsOne` — Pydantic `AfterValidator` ensuring a collection contains at least one instance of a specified type.

### Factories: `invariants/factories/`

- **`StateFactory[T]`** (`state.py`) — Wraps Polyfactory's `ModelFactory`. Validates at `__init_subclass__` that the target state has no `Statefull` fields.
- **`SQLAlchemyStateFactory[R, T]`** (`sqlalchemy.py`) — Generic over State (`R`) + ORM model (`T`). Inherits `StateFactory[R]` but `build()` returns `T` (the ORM instance). Supports sync/async persistence via SQLAlchemy sessions.

### XState Visualization: `invariants/viz/xstate.py`

Generates XState v5 JS code from `StateMachine` subclasses for use with stately.ai/viz.

- **Transition extraction** — Parses `execute(self, input: StateA) -> StateB` signatures to discover valid transitions. Union types (`StateA | StateB`) produce multiple transitions.
- **Nesting detection** — Scans concrete state field annotations to find parent→child state hierarchy relationships (e.g., `DebtState` containing `LoanState` tuples).
- **Guard generation** — Derives guards from field annotations: `ContainsOne(X)` → `"anyX"`, `tuple[X, ...]` → `"onlyX"`, combined → named compound guard using `and()`.
- **Code rendering** — Outputs `setup({ guards }).createMachine()` or plain `createMachine()` depending on whether guards are present. Compound guards are registered by name in `setup()` (not inline) for visualizer compatibility.
- **CLI** — `python -m invariants.viz {print,serve} <module>`. The `serve` command auto-clones [nkhitrov/xstate-display](https://github.com/nkhitrov/xstate-display) into `.xstate-viz/` and starts a dev server with the generated code pre-filled.

## Workflow

- After making any code changes, always run `make check` (lint + typecheck + tests) at the end and fix all errors before finishing.
- Use `make lint-fix` to auto-fix lint errors where possible, then fix remaining errors manually.
- **Never change linter/type-checker configs** (`pyproject.toml` `[tool.mypy]`, `[tool.ruff]`, etc.) without explicit user approval. You may suggest config changes, but must not apply them. The `strict = true` mypy setting must never be changed.

## Testing

- pytest with pytest-asyncio (auto mode).
- `tests/support/` contains shared fixtures: example state hierarchies (`LoanState`, `DebtState` and their children) and SQLAlchemy ORM base.
- Uses `dirty-equals` for flexible assertions.
- SQLAlchemy tests use in-memory SQLite with aiosqlite for async tests.
- Factory tests reset `BaseFactory._factory_type_mapping` between runs via fixture.
- **Tests must only call public API.** Never call private (`_method`) or protected methods directly in tests. Test behavior through the public interface — trigger errors via class creation, `.build()`, etc.
