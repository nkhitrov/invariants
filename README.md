# invariants

[![PyPI](https://img.shields.io/pypi/v/invariants)](https://pypi.org/project/invariants/)
[![Python](https://img.shields.io/pypi/pyversions/invariants)](https://pypi.org/project/invariants/)
[![License](https://img.shields.io/github/license/nkhitrov/invariants)](https://github.com/nkhitrov/invariants/blob/main/LICENSE)

Type-safe state modeling for Python. Split entity invariants into separate, validated, immutable state classes using Pydantic.

## Why?

When an entity has multiple states, each state often has different field requirements. Typically, this is modeled with optional fields and runtime checks. **invariants** enforces these constraints at the type level:

- Each state is a separate class with its own field types
- A metaclass ensures child states override all abstract fields and don't add new ones
- All states are immutable and have no behaviour
- Every edge of the state graph has exactly one `Event` and one `Operation`
- Operation signatures are the state graph: mypy checks the calls, and the same annotations drive the diagram

## Installation

```bash
pip install invariants
```

## Quick Start

Define a root state with `Statefull` fields (abstract markers), then create concrete states that override them:

```python
from datetime import datetime
from typing import Literal

from invariants.state import State, Statefull


class LoanState(State):
    id: int
    status: Statefull
    postponement_date: Statefull


class ActiveLoan(LoanState):
    status: Literal["active"] = "active"
    postponement_date: datetime


class ClosedLoan(LoanState):
    status: Literal["closed"] = "closed"
    postponement_date: None = None


class OverdueLoan(LoanState):
    status: Literal["overdue"] = "overdue"
    postponement_date: datetime
```

The metaclass enforces two rules at class creation time:
1. Child states **cannot add new fields** — only override parent fields
2. Child states **must override all `Statefull` fields** with concrete types

## Operations and Events

States are plain data. Moving a state from `A` to `B` is an **edge** of the state graph, and each edge has
exactly one **event** and is implemented by exactly one **operation**.

### Events — one per edge

`Event[From, To]` is a frozen, strict Pydantic model. `From = None` is the null state (creation). The payload
is exactly the fields you declare:

```python
from invariants.operations import Event


class LoanIssuedEvent(Event[None, ActiveLoan]):  # ∅ → ActiveLoan
    loan_id: int


class LoanBecameOverdueEvent(Event[ActiveLoan, OverdueLoan]):
    loan_id: int


class ActiveLoanClosedEvent(Event[ActiveLoan, ClosedLoan]):
    loan_id: int


class OverdueLoanClosedEvent(Event[OverdueLoan, ClosedLoan]):
    loan_id: int
```

Checked at class creation: the name ends with `Event`, `From`/`To` are concrete states of one hierarchy,
`From ≠ To`, and no other event already describes the same edge.

### Operations — one signature per edge

An operation returns a `Transition[State, Events]` — a plain named tuple of the new state and the events:

```python
from typing import overload

from invariants.operations import Operation, Transition


class IssueLoanOperation(Operation[LoanState]):  # no state parameter: starts from the null state
    def execute(
        self, *, loan_id: int, postponement_date: datetime
    ) -> Transition[ActiveLoan, LoanIssuedEvent]:
        loan = ActiveLoan(id=loan_id, postponement_date=postponement_date)
        return Transition(loan, (LoanIssuedEvent(loan_id=loan_id),))


class MakeLoanOverdueOperation(Operation[LoanState]):
    def execute(self, loan: ActiveLoan) -> Transition[OverdueLoan, LoanBecameOverdueEvent]:
        overdue = OverdueLoan(id=loan.id, postponement_date=loan.postponement_date)
        return Transition(overdue, (LoanBecameOverdueEvent(loan_id=loan.id),))


class CloseLoanOperation(Operation[LoanState]):  # several edges: one @overload per edge
    @overload
    def execute(self, loan: ActiveLoan) -> Transition[ClosedLoan, ActiveLoanClosedEvent]: ...
    @overload
    def execute(self, loan: OverdueLoan) -> Transition[ClosedLoan, OverdueLoanClosedEvent]: ...
    def execute(
        self, loan: ActiveLoan | OverdueLoan
    ) -> Transition[ClosedLoan, ActiveLoanClosedEvent | OverdueLoanClosedEvent]:
        closed = ClosedLoan(id=loan.id)
        match loan:
            case ActiveLoan():
                return Transition(closed, (ActiveLoanClosedEvent(loan_id=loan.id),))
            case OverdueLoan():
                return Transition(closed, (OverdueLoanClosedEvent(loan_id=loan.id),))


loan, issued = IssueLoanOperation().execute(loan_id=1, postponement_date=datetime(2026, 1, 1))
closed, events = CloseLoanOperation().execute(loan)  # events: tuple[ActiveLoanClosedEvent, ...]
```

Signature rules, checked when the operation class is created:

- the class name ends with `Operation`, and `T` in `Operation[T]` is the root state;
- the first parameter is a single concrete source state (no state parameter means creation from `None`);
  all other parameters are keyword-only;
- the return type is `Transition[B, E]`, or a union of them when the target depends on data;
- for `A → B` (`A ≠ B`), `E` contains exactly one event of the root, and it is `Event[A, B]`;
- an edge belongs to one operation (per registry) and is declared once.

At runtime `execute` is wrapped (its signature is unchanged for mypy): returning an undeclared state or event,
or not emitting the edge event exactly once, raises `TransitionError`.

### Dependencies and nested aggregates

Operations are frozen, keyword-only, slotted dataclasses. Their fields are their dependencies — only other
`Operation`s or `Query`s. Time, repository data and settings are `execute` arguments.

Events of nested aggregates travel up with the parent's own event:

```python
from typing import Annotated

from invariants.conditions import ContainsOne


class DebtState(State):
    id: int
    status: Statefull
    loans: Statefull


class ActiveDebt(DebtState):
    status: Literal["active"] = "active"
    loans: Annotated[tuple[ActiveLoan | ClosedLoan, ...], ContainsOne(ActiveLoan)]


class OverdueDebt(DebtState):
    status: Literal["overdue"] = "overdue"
    loans: Annotated[
        tuple[OverdueLoan | ActiveLoan | ClosedLoan, ...], ContainsOne(OverdueLoan)
    ]


class DebtBecameOverdueEvent(Event[ActiveDebt, OverdueDebt]):
    debt_id: int
    overdue_loan_id: int


class MakeDebtOverdueOperation(Operation[DebtState]):
    make_loan_overdue: MakeLoanOverdueOperation  # dependency = dataclass field

    def execute(
        self, debt: ActiveDebt, *, loan_id: int
    ) -> Transition[OverdueDebt, DebtBecameOverdueEvent | LoanBecameOverdueEvent]:
        loans: list[OverdueLoan | ActiveLoan | ClosedLoan] = []
        loan_events: list[LoanBecameOverdueEvent] = []
        for loan in debt.loans:
            match loan:
                case ActiveLoan(id=id_) if id_ == loan_id:
                    overdue, events = self.make_loan_overdue.execute(loan)  # nested edge
                    loans.append(overdue)
                    loan_events.extend(events)
                case _:
                    loans.append(loan)
        new_debt = OverdueDebt(id=debt.id, loans=tuple(loans))
        return Transition(
            new_debt,
            (DebtBecameOverdueEvent(debt_id=debt.id, overdue_loan_id=loan_id), *loan_events),
        )


operation = MakeDebtOverdueOperation(make_loan_overdue=MakeLoanOverdueOperation())
```

Events other than the root's own must come from hierarchies nested in the root's fields (here `LoanState` inside
`DebtState`). Forgetting `LoanBecameOverdueEvent` in the annotation is a mypy error.

### Loops

A loop `A → A` is an edge too, owned by one operation, but it has **no root event** (`Event[A, A]` is forbidden):
the root's invariant held and something nested changed, so the transition carries only nested events (at least one):

```python
class AddLoanToDebtOperation(Operation[DebtState]):
    issue_loan: IssueLoanOperation

    def execute(
        self, debt: ActiveDebt, *, loan_id: int, postponement_date: datetime
    ) -> Transition[ActiveDebt, LoanIssuedEvent]:
        loan, loan_events = self.issue_loan.execute(loan_id=loan_id, postponement_date=postponement_date)
        return Transition(ActiveDebt(id=debt.id, loans=(*debt.loans, loan)), loan_events)
```

When the target depends on data, return a union of transitions, each with its own edge event (see
`ActivateDebtLoanOperation` in [`examples/debt.py`](examples/debt.py)). mypy has no single context to infer the
events from a union, so annotate the `Transition` in a local variable before returning it.

### Queries

`Query[T]` follows the same dataclass and dependency rules, but `execute` returns any value and moves nothing:

```python
from invariants.operations import Query


class CheckDebtOverdueDaysQuery(Query[DebtState]):
    def execute(self, debt: OverdueDebt, *, now: datetime) -> int:
        overdue = next(loan for loan in debt.loans if isinstance(loan, OverdueLoan))
        return (now - overdue.postponement_date).days
```

### Registries

Events and operations register their edges in a default `EdgeRegistry`. Pass your own to isolate graphs,
for example in tests:

```python
from invariants.operations import EdgeRegistry

registry = EdgeRegistry()


class LoanPaidEvent(Event[ActiveLoan, ClosedLoan], registry=registry):
    loan_id: int
```

The full example lives in [`examples/loan.py`](examples/loan.py) and [`examples/debt.py`](examples/debt.py).

## Factories (Testing)

Optional integration with [polyfactory](https://github.com/litestar-org/polyfactory) for generating test data. The key idea: **a factory always produces a valid state** — all business invariants are satisfied automatically.

```bash
pip install invariants[factories]
```

Define factories for concrete states — the model is inferred from the generic argument:

```python
from invariants.factories import StateFactory


class ActiveLoanFactory(StateFactory[ActiveLoan]): ...
class ClosedLoanFactory(StateFactory[ClosedLoan]): ...
class ActiveDebtFactory(StateFactory[ActiveDebt]): ...
```

When you build a nested state, child entities are generated automatically:

```python
debt = ActiveDebtFactory.build()

# loans are auto-populated with valid ActiveLoan | ClosedLoan instances
# ContainsOne(ActiveLoan) is always satisfied — at least one loan is active
assert any(isinstance(loan, ActiveLoan) for loan in debt.loans)
```

### SQLAlchemy Integration

`SQLAlchemyStateFactory` maps Pydantic states to ORM models — `build()` returns ORM instances instead of Pydantic models:

```python
from invariants.factories.sqlalchemy import SQLAlchemyStateFactory


class ActiveLoanORMFactory(SQLAlchemyStateFactory[ActiveLoan, LoanORM]): ...

loan = ActiveLoanORMFactory.build()
assert isinstance(loan, LoanORM)  # ORM instance, not Pydantic model
```

Both `StateFactory` and `SQLAlchemyStateFactory` are thin wrappers over [polyfactory](https://polyfactory.litestar.dev/) — all interfaces (sessions, persistence, batch creation) work the same as in the polyfactory docs.

## XState Visualization

Generate [XState v5](https://stately.ai/docs/xstate) state machine code from your operations. Each edge
becomes a transition named after its event (a loop — after its operation), and the creation edge (`None → B`)
sets the initial state:

```bash
# Print generated JS — paste it into https://sketch.stately.ai
python -m invariants.viz print examples.debt

# Start a local Stately Sketch with one document per state machine
# (clones https://github.com/statelyai/sketch on first run; needs Node.js with pnpm or npx)
python -m invariants.viz serve examples.debt
```

`serve` opens each machine in the browser

![img.png](docs/img.png)
