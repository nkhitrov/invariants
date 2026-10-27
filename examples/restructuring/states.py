from datetime import date
from decimal import Decimal
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field

from examples.loan.states import ActiveLoan, ClosedLoan, Installment
from invariants.conditions import ContainsOne
from invariants.state import State, Statefull


class LoanTerms(BaseModel):
    """Terms of one restructuring loan."""

    model_config = ConfigDict(frozen=True, strict=True)

    loan_id: int
    financed_amount: Decimal
    schedule: Annotated[tuple[Installment, ...], Field(min_length=1)]


class RestructuringTerms(BaseModel):
    """Approved restructuring: the new loans."""

    model_config = ConfigDict(frozen=True, strict=True)

    id: int
    loans: Annotated[tuple[LoanTerms, ...], Field(min_length=1)]


class RestructuringState(State):
    """A restructuring of a debt. It is a nested entity of the debt."""

    id: int
    applied_at: date
    status: Statefull
    loans: Statefull


class ActiveRestructuring(RestructuringState):
    """Being paid by the new schedule. An overdue here breaks the agreement and cancels it."""

    status: Literal["active"] = "active"
    loans: Annotated[tuple[ActiveLoan | ClosedLoan, ...], ContainsOne(ActiveLoan)]


class ClosedRestructuring(RestructuringState):
    """Every restructuring loan is repaid and closed."""

    status: Literal["closed"] = "closed"
    loans: tuple[ClosedLoan, ...]
