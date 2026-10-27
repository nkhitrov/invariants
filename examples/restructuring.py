"""Debt restructuring: new loans that replace the original ones on agreed terms.

The terms are approved outside the invariants and come in as a value object. Every installment
of a restructuring loan names the original loan it pays off (``Installment.original_loan_id``),
so original and restructuring loans map 1:1 or N:M.
"""

from collections import defaultdict
from datetime import date
from decimal import Decimal
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field

from examples.calculations import ZERO
from examples.loan import (
    ActiveLoan,
    ActiveLoanClosedEvent,
    CloseLoanOperation,
    ClosedLoan,
    Installment,
    IssueLoanOperation,
    LoanIssuedEvent,
)
from examples.payment import ReceivedPayment
from invariants.conditions import ContainsOne
from invariants.operations import Event, Operation, Transition
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


class RestructuringAppliedEvent(Event[None, ActiveRestructuring]):
    restructuring_id: int


class RestructuringClosedEvent(Event[ActiveRestructuring, ClosedRestructuring]):
    restructuring_id: int


class OpenRestructuringOperation(Operation[RestructuringState]):
    """Issue the restructuring loans on the agreed terms."""

    issue_loan: IssueLoanOperation

    def execute(
        self, *, terms: RestructuringTerms, booking_date: date
    ) -> Transition[ActiveRestructuring, RestructuringAppliedEvent | LoanIssuedEvent]:
        issued = [
            self.issue_loan.execute(
                loan_id=loan.loan_id,
                financed_amount=loan.financed_amount,
                booking_date=booking_date,
                schedule=loan.schedule,
            )
            for loan in terms.loans
        ]
        restructuring = ActiveRestructuring(
            id=terms.id, applied_at=booking_date, loans=tuple(loan for loan, _ in issued)
        )
        loan_events = tuple(event for _, events in issued for event in events)
        return Transition(restructuring, (RestructuringAppliedEvent(restructuring_id=terms.id), *loan_events))


class CloseRestructuringOperation(Operation[RestructuringState]):
    """Close a restructuring whose loans are all repaid."""

    close_loan: CloseLoanOperation

    def execute(
        self, restructuring: ActiveRestructuring
    ) -> Transition[ClosedRestructuring, RestructuringClosedEvent | ActiveLoanClosedEvent]:
        closed = [self._close(loan) for loan in restructuring.loans]
        closed_restructuring = ClosedRestructuring(
            id=restructuring.id, applied_at=restructuring.applied_at, loans=tuple(loan for loan, _ in closed)
        )
        loan_events = tuple(event for _, events in closed for event in events)
        return Transition(
            closed_restructuring, (RestructuringClosedEvent(restructuring_id=restructuring.id), *loan_events)
        )

    def _close(self, loan: ActiveLoan | ClosedLoan) -> tuple[ClosedLoan, tuple[ActiveLoanClosedEvent, ...]]:
        match loan:
            case ActiveLoan():
                return self.close_loan.execute(loan)
            case ClosedLoan():
                return loan, ()


def transferred_payments(
    loans: tuple[ActiveLoan | ClosedLoan, ...],
) -> dict[int, tuple[ReceivedPayment, ...]]:
    """Payments of restructuring loans, moved to the original loans by the installment mapping.

    Each payment is split over the installments of its loan in schedule order (a restructuring
    loan is never overdue, so it has no penalty to pay first); every share goes to the original
    loan of its installment, an overpayment to the original loan of the last installment.
    """
    result: dict[int, list[ReceivedPayment]] = defaultdict(list)
    for loan in loans:
        left = [installment.amount for installment in loan.schedule]
        for payment in sorted(loan.payments, key=lambda p: p.paid_at):
            shares: dict[int, Decimal] = defaultdict(lambda: ZERO)
            amount = payment.amount
            for index, installment in enumerate(loan.schedule):
                share = min(amount, left[index])
                left[index] -= share
                amount -= share
                if share:
                    shares[_original_loan_id(installment)] += share
            if amount:
                shares[_original_loan_id(loan.schedule[-1])] += amount
            for original_loan_id, share in shares.items():
                result[original_loan_id].append(
                    ReceivedPayment(
                        id=payment.id, amount=share, paid_at=payment.paid_at, transferred_from_loan_id=loan.id
                    )
                )
    return {loan_id: tuple(payments) for loan_id, payments in result.items()}


def _original_loan_id(installment: Installment) -> int:
    if installment.original_loan_id is None:
        raise ValueError("A restructuring installment must name its original loan")
    return installment.original_loan_id
