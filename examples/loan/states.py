from datetime import date
from decimal import Decimal
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field

from examples.payment.states import ReceivedPayment
from invariants.state import State, Statefull


class Installment(BaseModel):
    """A scheduled payment: a value object, not a state. After ``postponement_date`` it is overdue."""

    model_config = ConfigDict(frozen=True, strict=True)

    postponement_date: date
    amount: Decimal
    # In a restructuring schedule: the original loan this installment pays off
    original_loan_id: int | None = None


class LoanState(State):
    """Loan. States: active (no overdue installments), overdue, closed (repaid with penalties).

    A loan "with one date" is a schedule of a single installment for the whole amount.
    Paid amounts and penalties are not stored: see ``examples.calculations``.
    """

    id: int
    financed_amount: Decimal
    # The day the loan terms are calculated for
    booking_date: date
    schedule: Annotated[tuple[Installment, ...], Field(min_length=1)]
    payments: tuple[ReceivedPayment, ...] = ()
    status: Statefull


class ActiveLoan(LoanState):
    status: Literal["active"] = "active"


class OverdueLoan(LoanState):
    status: Literal["overdue"] = "overdue"


class ClosedLoan(LoanState):
    """Closed loan. It cannot change state: it stays closed forever."""

    status: Literal["closed"] = "closed"
