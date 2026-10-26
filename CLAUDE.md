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

# XState: start visualizer (auto-clones statelyai/sketch, requires node + pnpm or npx)
uv run python -m invariants.viz serve examples.example
```

## Architecture

### Core: `invariants/state.py`

- **`Statefull`** — Marker type for abstract fields. At runtime it's a class with `__get_pydantic_core_schema__` (returns `any_schema()`); under `TYPE_CHECKING` it aliases `Any` so mypy allows child overrides with any concrete type.
- **`StateMeta`** — Metaclass extending Pydantic's `ModelMetaclass`. Enforces at class creation: child states cannot add new fields, and must override all `Statefull` fields with concrete types.
- **`State`** — Base class (`BaseModel` + `StateMeta`). Frozen, strict. A `model_validator(mode="before")` prevents instantiation if the class still has `Statefull` fields.

- **`StateMachine[T]`** — Generic abstract base (`__slots__ = ()`) for commands/queries over a state hierarchy `T`. Legacy form: the `execute` signature (`input → output`) defines valid state transitions. New code uses `Operation`/`Query` below.

Class hierarchy: `State` (root) → root child (declares `Statefull` fields) → concrete state (overrides all `Statefull` fields). The metaclass validation triggers on the concrete level (`is_base_state` check).

### Hierarchy introspection: `invariants/hierarchy.py`

Shared by operations and viz: `get_root_state` (the `T` of `StateMachine[T]`), `get_concrete_states`, `is_concrete_state`, `unwrap_state_types`, `find_state_root`, `detect_nesting`/`NestingRelation`, `get_nested_roots` (transitive roots nested in a root's fields). `invariants/viz/xstate.py` re-exports them.

### Operations: `invariants/operations.py`

DDD-style transitions: an **event is a change of the business state** (the state class, not field values); **edge of the state graph = event**, and every edge `A → B` has one event and one owner operation. States have no methods; behaviour lives in `...Operation` classes.

- **`Event[From, To]`** — frozen strict pydantic model, name ends with `Event`. `From`/`To` are single concrete states of one root (generic metadata, not fields — payload is only user fields); `From = None` is the null state (creation); `Event[A, A]` is forbidden. `get_event_edge(cls)` returns `(From, To)` (also through generic user bases).
- **`EdgeRegistry`** — like `MapperRegistry`: `(From, To)` → event class and → owner operation class (loops are never registered). Default registry on `Event`/`Operation`; pass `registry=EdgeRegistry()` in the class definition to isolate (tests do this for every ad-hoc event/operation).
- **`Transition[S, E]`** — generic `NamedTuple` (`state`, `events: tuple[E, ...]`), covariant; no methods. mypy infers `E` from the declared return type, except when `execute` returns a *union* of `Transition`s — then annotate a local variable (see `ActivateDebtLoanOperation`).
- **`OperationMeta`** — `dataclass_transform` metaclass; in `__new__` turns each subclass into `dataclass(frozen=True, kw_only=True, slots=True)` (that creates a new class — hence a metaclass, and the recreated class is detected by `__dataclass_fields__` in its namespace) and then calls `validate_operation`.
- **`Operation[T]`** (`T` = root state) — validated at class creation: name ends with `Operation`; dataclass fields (dependencies) are only `Operation`/`Query` (time and external data are `execute` arguments); each `execute` signature (each `typing.get_overloads` entry, else `execute` itself) has at most one positional parameter — a single concrete source state of `T` (none = creation from `None`) — other parameters keyword-only, and returns `Transition[B, E]` or a union of them. For `A ≠ B`, `E` holds exactly one event of root `T`, and it is `Event[A, B]`. A loop `A → A` holds no root events, only nested ones, possibly none (`Transition[A, Never]`); loops are not owned and may appear in any number of operations. Other events must belong to roots nested in `T` (`get_nested_roots`). An edge is declared once per operation. **Ownership/delegation**: an edge `A → B` is *delegated* if a dependency (transitively, through operations and queries) implements it, otherwise the operation owns it and registers it — a second independent owner raises `TypeError`. Every declared event (own edge or nested) must be the event of an owned or delegated edge. Each class stores `__implemented_edges__` (owned + delegated, transitively). `get_operation_edges(cls)` returns the parsed `OperationEdge`s. `execute` is wrapped at runtime (signature/annotations/overloads preserved) to raise `TransitionError` if the result isn't a declared `Transition`, carries undeclared events, or doesn't emit the edge event exactly once.
- **`Query[T]`** — same dataclass/dependency rules, `execute` is free-form (e.g. returns `int`).

`examples/` is the reference domain (loans with a payment schedule inside debts). Money is never stored in states: `examples/calculations.py` derives paid amounts, penalties (0.01% of `financed_amount` per overdue day up to `booking_date`; a payment pays penalty first, then installments in order) and overdue installments by pure functions over structural `LoanFacts` protocols. `Installment` is a frozen value object, not a state; `ReceivedPayment` (`examples/payment.py`) is a nested entity of the loan. Patterns: creation (`IssueLoanOperation`), overloads (`CloseLoanOperation`), union with an event-less loop (`RecalculateLoanTermsOperation`), pure loops (`AccruePenaltyOperation`, `ReceiveLoanPaymentOperation`), nested aggregates by delegation (`RecalculateDebtOperation`), delegated root edge (`ReceiveDebtPaymentOperation` → `CancelDebtOverdueOperation`).

### Validators: `invariants/conditions.py`

`ContainsOne` — Pydantic `AfterValidator` ensuring a collection contains at least one instance of a specified type.

### Factories: `invariants/factories/`

- **`StateFactory[T]`** (`state.py`) — Wraps Polyfactory's `ModelFactory`. Validates at `__init_subclass__` that the target state has no `Statefull` fields.
- **`SQLAlchemyStateFactory[R, T]`** (`sqlalchemy.py`) — Generic over State (`R`) + ORM model (`T`). Inherits `StateFactory[R]` but `build()` returns `T` (the ORM instance). Supports sync/async persistence via SQLAlchemy sessions.

### XState Visualization: `invariants/viz/xstate.py`

Generates XState v5 JS code from `StateMachine` subclasses for use with
[Stately Sketch](https://sketch.stately.ai) ([statelyai/sketch](https://github.com/statelyai/sketch)).

- **Transition extraction** — For operations (`execute` returns `Transition[...]`) uses `get_operation_edges`: one transition per edge, named after the edge event; a loop is an internal (targetless, unguarded) transition `Operation: [{}]` named after the operation; an edge from `None` sets the machine's `initial` instead of becoming an `on` entry; a delegated edge declared by several operations is drawn once. Legacy `execute(self, input: StateA) -> StateB` signatures are still parsed; union types (`StateA | StateB`) produce multiple transitions named after the machine.
- **Nesting detection** — Scans concrete state field annotations to find parent→child state hierarchy relationships (e.g., `DebtState` containing `LoanState` tuples).
- **Guard generation** — Derives guards from field annotations: `ContainsOne(X)` → `"anyX"`, `tuple[X, ...]` → `"onlyX"`, combined → `and([...])` over those names.
- **Code rendering** — `build_xstate_config` produces one config per root state; `render_configs` turns configs into JS, `render_xstate_code` is the two together. Output is `setup({ guards }).createMachine()` when a machine has guards, plain `createMachine()` otherwise. Leaf guards are registered as `() => true` stubs in `setup()`; compound guards are inlined with the xstate combinator (`guard: and(['a', 'b'])`).
- **CLI** — `python -m invariants.viz {print,serve} <module>`. `serve` auto-clones [statelyai/sketch](https://github.com/statelyai/sketch) into `invariants/.sketch/` (gitignored), starts its dev server with `VITE_REGISTRY_API_URL` pointed at Sketch's own local sqlite API (so no Stately account is involved, `DB_PATH=:memory:`), stores **one document per root machine** through `POST /api/viz/create-source-file` (Sketch renders only the first machine of a document) and opens each `/viz/<id>` in the browser. The Node/browser half (`_ensure_sketch`, `serve`) is `# pragma: no cover`; the URL/env/payload helpers are unit-tested in `tests/test_viz/test_xstate/test_sketch.py`.

## Workflow

- After making any code changes, always run `make check` (lint + typecheck + tests) at the end and fix all errors before finishing.
- Use `make lint-fix` to auto-fix lint errors where possible, then fix remaining errors manually.
- **Never change linter/type-checker configs** (`pyproject.toml` `[tool.mypy]`, `[tool.ruff]`, etc.) without explicit user approval. You may suggest config changes, but must not apply them. The `strict = true` mypy setting must never be changed.

## Testing

- pytest with pytest-asyncio (auto mode).
- `tests/support/` contains shared fixtures: example state hierarchies (`LoanState`, `DebtState` and their children, with legacy `StateMachine`s used by the viz tests) and SQLAlchemy ORM base.
- Operation tests (`tests/test_operations/`) use the states/events of `examples/`; every event or operation defined inside a test passes `registry=EdgeRegistry()` so edges don't clash. `test_examples.py` holds the end-to-end loan/debt scenarios.
- Uses `dirty-equals` for flexible assertions.
- SQLAlchemy tests use in-memory SQLite with aiosqlite for async tests.
- Factory tests reset `BaseFactory._factory_type_mapping` between runs via fixture.
- **Tests must only call public API.** Never call private (`_method`) or protected methods directly in tests. Test behavior through the public interface — trigger errors via class creation, `.build()`, etc.
