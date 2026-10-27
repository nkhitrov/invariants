from typing import Annotated, Literal

from examples.loan.states import ActiveLoan, ClosedLoan, OverdueLoan
from examples.restructuring.states import ActiveRestructuring, ClosedRestructuring
from invariants.conditions import ContainsOne
from invariants.state import State, Statefull

Loan = ActiveLoan | OverdueLoan | ClosedLoan


class DebtState(State):
    """Debt. It has no money of its own: its state is derived from the states of its loans.

    ``loans`` are the original loans; ``restructuring`` holds the loans that replace them
    while the debt is restructured.
    """

    id: int
    status: Statefull
    loans: Statefull
    restructuring: Statefull


class ActiveDebt(DebtState):
    """Active debt: every loan is active or closed, and at least one is active."""

    status: Literal["active"] = "active"
    loans: Annotated[tuple[ActiveLoan | ClosedLoan, ...], ContainsOne(ActiveLoan)]
    restructuring: None = None


class ClosedDebt(DebtState):
    """Closed debt: every loan is closed."""

    status: Literal["closed"] = "closed"
    loans: tuple[ClosedLoan, ...]
    restructuring: None = None


class OverdueDebt(DebtState):
    """Overdue debt: at least one loan is overdue."""

    status: Literal["overdue"] = "overdue"
    loans: Annotated[
        tuple[OverdueLoan | ActiveLoan | ClosedLoan, ...], ContainsOne(OverdueLoan)
    ]
    restructuring: None = None


class RestructuredDebt(DebtState):
    """Paid by the restructuring loans; ``loans`` is the snapshot of the original loans, kept to roll back."""

    status: Literal["restructured"] = "restructured"
    loans: tuple[OverdueLoan | ActiveLoan | ClosedLoan, ...]
    restructuring: ActiveRestructuring


class ClosedRestructuredDebt(DebtState):
    """Closed on the restructuring terms; ``loans`` is the same snapshot of the original loans."""

    status: Literal["closed_restructured"] = "closed_restructured"
    loans: tuple[OverdueLoan | ActiveLoan | ClosedLoan, ...]
    restructuring: ClosedRestructuring


Debt = ActiveDebt | ClosedDebt | OverdueDebt | RestructuredDebt | ClosedRestructuredDebt
