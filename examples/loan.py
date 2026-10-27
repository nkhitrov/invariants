from datetime import date
from decimal import Decimal
from typing import Annotated, Any, Literal, Never, overload

from pydantic import BaseModel, ConfigDict, Field

from examples.calculations import is_repaid, overdue_installments
from examples.payment import PaymentReceivedEvent, ReceivedPayment, ReceivePaymentOperation
from invariants.operations import Event, Operation, Transition
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


class LoanIssuedEvent(Event[None, ActiveLoan]):
    loan_id: int


class LoanBecameOverdueEvent(Event[ActiveLoan, OverdueLoan]):
    loan_id: int


class LoanOverdueCancelledEvent(Event[OverdueLoan, ActiveLoan]):
    loan_id: int


class ActiveLoanClosedEvent(Event[ActiveLoan, ClosedLoan]):
    loan_id: int


class OverdueLoanClosedEvent(Event[OverdueLoan, ClosedLoan]):
    loan_id: int


class LoanStillOverdueError(ValueError):
    def __init__(self, loan_id: int) -> None:
        super().__init__(f"Loan {loan_id} still has overdue installments")
        self.loan_id = loan_id


class LoanNotRepaidError(ValueError):
    def __init__(self, loan_id: int) -> None:
        super().__init__(f"Loan {loan_id} is not repaid with penalties")
        self.loan_id = loan_id


def loan_fields(loan: LoanState, **changes: Any) -> dict[str, Any]:
    """Fields of a loan for building its next state (the status comes from the target class)."""
    return {name: getattr(loan, name) for name in LoanState.model_fields if name != "status"} | changes


class IssueLoanOperation(Operation[LoanState]):
    """Issue a loan: the loan starts active."""

    def execute(
        self,
        *,
        loan_id: int,
        financed_amount: Decimal,
        booking_date: date,
        schedule: tuple[Installment, ...],
    ) -> Transition[ActiveLoan, LoanIssuedEvent]:
        loan = ActiveLoan(
            id=loan_id, financed_amount=financed_amount, booking_date=booking_date, schedule=schedule
        )
        return Transition(loan, (LoanIssuedEvent(loan_id=loan_id),))


class RecalculateLoanTermsOperation(Operation[LoanState]):
    """Move the booking date of an active loan; it becomes overdue once an installment is overdue."""

    def execute(self, loan: ActiveLoan, *, booking_date: date) -> (
        Transition[OverdueLoan, LoanBecameOverdueEvent] | Transition[ActiveLoan, Never]
    ):
        moved = ActiveLoan(**loan_fields(loan, booking_date=booking_date))
        if not overdue_installments(moved):
            # A loop: only the booking date moved, the business state did not change
            unchanged: Transition[ActiveLoan, Never] = Transition(moved, ())
            return unchanged
        overdue = OverdueLoan(**loan_fields(moved))
        return Transition(overdue, (LoanBecameOverdueEvent(loan_id=loan.id),))


class AccruePenaltyOperation(Operation[LoanState]):
    """Move the booking date of an overdue loan; the penalty grows, computed on the fly."""

    def execute(self, loan: OverdueLoan, *, booking_date: date) -> Transition[OverdueLoan, Never]:
        return Transition(OverdueLoan(**loan_fields(loan, booking_date=booking_date)), ())


class ReceiveLoanPaymentOperation(Operation[LoanState]):
    """Add a payment to a loan. A payment alone never changes the loan's business state."""

    receive_payment: ReceivePaymentOperation

    @overload
    def execute(
        self, loan: ActiveLoan, *, payment_id: int, amount: Decimal, paid_at: date
    ) -> Transition[ActiveLoan, PaymentReceivedEvent]: ...
    @overload
    def execute(
        self, loan: OverdueLoan, *, payment_id: int, amount: Decimal, paid_at: date
    ) -> Transition[OverdueLoan, PaymentReceivedEvent]: ...
    def execute(
        self, loan: ActiveLoan | OverdueLoan, *, payment_id: int, amount: Decimal, paid_at: date
    ) -> Transition[ActiveLoan, PaymentReceivedEvent] | Transition[OverdueLoan, PaymentReceivedEvent]:
        payment, events = self.receive_payment.execute(payment_id=payment_id, amount=amount, paid_at=paid_at)
        fields = loan_fields(loan, payments=(*loan.payments, payment))
        match loan:
            case ActiveLoan():
                active: Transition[ActiveLoan, PaymentReceivedEvent] = Transition(ActiveLoan(**fields), events)
                return active
            case OverdueLoan():
                overdue: Transition[OverdueLoan, PaymentReceivedEvent] = Transition(OverdueLoan(**fields), events)
                return overdue


class CancelLoanOverdueOperation(Operation[LoanState]):
    """Cancel the overdue: the only owner of ``OverdueLoan → ActiveLoan``.

    ``schedule`` is the current schedule when the overdue installment was paid, or a new one
    agreed by the parties on restructuring (an application use case outside the invariants).
    """

    def execute(
        self, loan: OverdueLoan, *, schedule: tuple[Installment, ...]
    ) -> Transition[ActiveLoan, LoanOverdueCancelledEvent]:
        if overdue_installments(loan, schedule):
            raise LoanStillOverdueError(loan.id)
        active = ActiveLoan(**loan_fields(loan, schedule=schedule))
        return Transition(active, (LoanOverdueCancelledEvent(loan_id=loan.id),))


class CloseLoanOperation(Operation[LoanState]):
    """Close a repaid loan: each source state has its own edge and its own event."""

    @overload
    def execute(self, loan: ActiveLoan) -> Transition[ClosedLoan, ActiveLoanClosedEvent]: ...
    @overload
    def execute(self, loan: OverdueLoan) -> Transition[ClosedLoan, OverdueLoanClosedEvent]: ...
    def execute(
        self, loan: ActiveLoan | OverdueLoan
    ) -> Transition[ClosedLoan, ActiveLoanClosedEvent | OverdueLoanClosedEvent]:
        if not is_repaid(loan):
            raise LoanNotRepaidError(loan.id)
        closed = ClosedLoan(**loan_fields(loan))
        match loan:
            case ActiveLoan():
                return Transition(closed, (ActiveLoanClosedEvent(loan_id=loan.id),))
            case OverdueLoan():
                return Transition(closed, (OverdueLoanClosedEvent(loan_id=loan.id),))
