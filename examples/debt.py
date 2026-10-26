from datetime import date
from decimal import Decimal
from typing import Annotated, Literal, Never, overload

from examples.calculations import overdue_days, overdue_installments
from examples.loan import (
    AccruePenaltyOperation,
    ActiveLoan,
    ActiveLoanClosedEvent,
    CancelLoanOverdueOperation,
    CloseLoanOperation,
    ClosedLoan,
    Installment,
    IssueLoanOperation,
    LoanBecameOverdueEvent,
    LoanIssuedEvent,
    LoanOverdueCancelledEvent,
    OverdueLoan,
    OverdueLoanClosedEvent,
    ReceiveLoanPaymentOperation,
    RecalculateLoanTermsOperation,
)
from examples.payment import PaymentReceivedEvent
from invariants.conditions import ContainsOne
from invariants.operations import Event, Operation, Query, Transition
from invariants.state import State, Statefull

Loan = ActiveLoan | OverdueLoan | ClosedLoan


class DebtState(State):
    """Debt. It has no money of its own: its state is derived from the states of its loans."""

    id: int
    status: Statefull
    loans: Statefull


class ActiveDebt(DebtState):
    """Active debt: every loan is active or closed, and at least one is active."""

    status: Literal["active"] = "active"
    loans: Annotated[tuple[ActiveLoan | ClosedLoan, ...], ContainsOne(ActiveLoan)]


class ClosedDebt(DebtState):
    """Closed debt: every loan is closed."""

    status: Literal["closed"] = "closed"
    loans: tuple[ClosedLoan, ...]


class OverdueDebt(DebtState):
    """Overdue debt: at least one loan is overdue."""

    status: Literal["overdue"] = "overdue"
    loans: Annotated[
        tuple[OverdueLoan | ActiveLoan | ClosedLoan, ...], ContainsOne(OverdueLoan)
    ]


Debt = ActiveDebt | ClosedDebt | OverdueDebt


class LoanNotFoundError(LookupError):
    def __init__(self, loan_id: int) -> None:
        super().__init__(f"Loan {loan_id} is not found in the debt")
        self.loan_id = loan_id


class DebtStillOverdueError(ValueError):
    def __init__(self, debt_id: int) -> None:
        super().__init__(f"Debt {debt_id} still has overdue loans")
        self.debt_id = debt_id


def replace_loan(loans: tuple[Loan, ...], loan: Loan) -> tuple[Loan, ...]:
    """Put the new state of a loan in place of its previous state."""
    if all(item.id != loan.id for item in loans):
        raise LoanNotFoundError(loan.id)
    return tuple(loan if item.id == loan.id else item for item in loans)


class DebtOpenedEvent(Event[None, ActiveDebt]):
    debt_id: int


class DebtBecameOverdueEvent(Event[ActiveDebt, OverdueDebt]):
    debt_id: int


class DebtOverdueCancelledEvent(Event[OverdueDebt, ActiveDebt]):
    debt_id: int


class ActiveDebtClosedEvent(Event[ActiveDebt, ClosedDebt]):
    debt_id: int


class OverdueDebtClosedEvent(Event[OverdueDebt, ClosedDebt]):
    debt_id: int


class OpenDebtOperation(Operation[DebtState]):
    """Open a debt with its first loan: both start active."""

    issue_loan: IssueLoanOperation

    def execute(
        self,
        *,
        debt_id: int,
        loan_id: int,
        financed_amount: Decimal,
        booking_date: date,
        schedule: tuple[Installment, ...],
    ) -> Transition[ActiveDebt, DebtOpenedEvent | LoanIssuedEvent]:
        loan, loan_events = self.issue_loan.execute(
            loan_id=loan_id, financed_amount=financed_amount, booking_date=booking_date, schedule=schedule
        )
        debt = ActiveDebt(id=debt_id, loans=(loan,))
        return Transition(debt, (DebtOpenedEvent(debt_id=debt_id), *loan_events))


class RecalculateDebtOperation(Operation[DebtState]):
    """Daily recalculation: move the booking date of every open loan.

    Active loans may become overdue (and then the debt does), overdue loans accrue penalty,
    closed loans are left as they are.
    """

    recalculate_loan_terms: RecalculateLoanTermsOperation
    accrue_penalty: AccruePenaltyOperation

    @overload
    def execute(self, debt: ActiveDebt, *, booking_date: date) -> (
        Transition[OverdueDebt, DebtBecameOverdueEvent | LoanBecameOverdueEvent]
        | Transition[ActiveDebt, Never]
    ): ...
    @overload
    def execute(self, debt: OverdueDebt, *, booking_date: date) -> Transition[OverdueDebt, LoanBecameOverdueEvent]: ...
    def execute(self, debt: ActiveDebt | OverdueDebt, *, booking_date: date) -> (
        Transition[OverdueDebt, DebtBecameOverdueEvent | LoanBecameOverdueEvent]
        | Transition[ActiveDebt, Never]
    ):
        moved = [self._recalculate(loan, booking_date) for loan in debt.loans]
        loans = tuple(loan for loan, _ in moved)
        loan_events = tuple(event for _, events in moved for event in events)

        match debt:
            case ActiveDebt() if not loan_events:
                unchanged: Transition[ActiveDebt, Never] = Transition(
                    ActiveDebt(id=debt.id, loans=tuple(loan for loan in loans if not isinstance(loan, OverdueLoan))),
                    (),
                )
                return unchanged
            case ActiveDebt():
                return Transition(
                    OverdueDebt(id=debt.id, loans=loans),
                    (DebtBecameOverdueEvent(debt_id=debt.id), *loan_events),
                )
            case OverdueDebt():
                return Transition(OverdueDebt(id=debt.id, loans=loans), loan_events)

    def _recalculate(self, loan: Loan, booking_date: date) -> tuple[Loan, tuple[LoanBecameOverdueEvent, ...]]:
        match loan:
            case ActiveLoan():
                return self.recalculate_loan_terms.execute(loan, booking_date=booking_date)
            case OverdueLoan():
                return self.accrue_penalty.execute(loan, booking_date=booking_date)
            case ClosedLoan():
                return loan, ()


class CancelDebtOverdueOperation(Operation[DebtState]):
    """Cancel the overdue of the last overdue loan: the owner of ``OverdueDebt → ActiveDebt``."""

    cancel_loan_overdue: CancelLoanOverdueOperation

    def execute(
        self, debt: OverdueDebt, *, loan: OverdueLoan, schedule: tuple[Installment, ...]
    ) -> Transition[ActiveDebt, DebtOverdueCancelledEvent | LoanOverdueCancelledEvent]:
        active_loan, loan_events = self.cancel_loan_overdue.execute(loan, schedule=schedule)
        loans = replace_loan(debt.loans, active_loan)
        if any(isinstance(item, OverdueLoan) for item in loans):
            raise DebtStillOverdueError(debt.id)
        active = ActiveDebt(id=debt.id, loans=tuple(item for item in loans if not isinstance(item, OverdueLoan)))
        return Transition(active, (DebtOverdueCancelledEvent(debt_id=debt.id), *loan_events))


class ReceiveDebtPaymentOperation(Operation[DebtState]):
    """Pay a loan of the debt; paying off the overdue installments cancels the overdue.

    Composition by delegation: the payment comes from ``ReceiveLoanPaymentOperation``, the
    ``OverdueDebt → ActiveDebt`` edge from its owner ``CancelDebtOverdueOperation``.
    """

    receive_loan_payment: ReceiveLoanPaymentOperation
    cancel_loan_overdue: CancelLoanOverdueOperation
    cancel_debt_overdue: CancelDebtOverdueOperation

    @overload
    def execute(
        self, debt: ActiveDebt, *, loan: ActiveLoan, payment_id: int, amount: Decimal, paid_at: date
    ) -> Transition[ActiveDebt, PaymentReceivedEvent]: ...
    @overload
    def execute(
        self, debt: OverdueDebt, *, loan: ActiveLoan | OverdueLoan, payment_id: int, amount: Decimal, paid_at: date
    ) -> (
        Transition[ActiveDebt, DebtOverdueCancelledEvent | LoanOverdueCancelledEvent | PaymentReceivedEvent]
        | Transition[OverdueDebt, LoanOverdueCancelledEvent | PaymentReceivedEvent]
    ): ...
    def execute(
        self,
        debt: ActiveDebt | OverdueDebt,
        *,
        loan: ActiveLoan | OverdueLoan,
        payment_id: int,
        amount: Decimal,
        paid_at: date,
    ) -> (
        Transition[ActiveDebt, PaymentReceivedEvent]
        | Transition[ActiveDebt, DebtOverdueCancelledEvent | LoanOverdueCancelledEvent | PaymentReceivedEvent]
        | Transition[OverdueDebt, LoanOverdueCancelledEvent | PaymentReceivedEvent]
    ):
        paid_loan, payment_events = self.receive_loan_payment.execute(
            loan, payment_id=payment_id, amount=amount, paid_at=paid_at
        )
        loans = replace_loan(debt.loans, paid_loan)

        if isinstance(debt, ActiveDebt):
            active_loans = tuple(item for item in loans if not isinstance(item, OverdueLoan))
            paid: Transition[ActiveDebt, PaymentReceivedEvent] = Transition(
                ActiveDebt(id=debt.id, loans=active_loans), payment_events
            )
            return paid

        with_payment = OverdueDebt(id=debt.id, loans=loans)
        if not isinstance(paid_loan, OverdueLoan) or overdue_installments(paid_loan):
            still_overdue: Transition[OverdueDebt, PaymentReceivedEvent] = Transition(with_payment, payment_events)
            return still_overdue

        other_overdue = any(isinstance(item, OverdueLoan) and item.id != paid_loan.id for item in loans)
        if other_overdue:
            active_loan, loan_events = self.cancel_loan_overdue.execute(paid_loan, schedule=paid_loan.schedule)
            partly: Transition[OverdueDebt, LoanOverdueCancelledEvent | PaymentReceivedEvent] = Transition(
                OverdueDebt(id=debt.id, loans=replace_loan(loans, active_loan)),
                (*payment_events, *loan_events),
            )
            return partly

        active, events = self.cancel_debt_overdue.execute(with_payment, loan=paid_loan, schedule=paid_loan.schedule)
        cancelled: Transition[
            ActiveDebt, DebtOverdueCancelledEvent | LoanOverdueCancelledEvent | PaymentReceivedEvent
        ] = Transition(active, (*payment_events, *events))
        return cancelled


class CloseDebtOperation(Operation[DebtState]):
    """Close a debt: every loan that is not closed yet must be repaid and gets closed."""

    close_loan: CloseLoanOperation

    @overload
    def execute(
        self, debt: ActiveDebt
    ) -> Transition[ClosedDebt, ActiveDebtClosedEvent | ActiveLoanClosedEvent]: ...
    @overload
    def execute(
        self, debt: OverdueDebt
    ) -> Transition[
        ClosedDebt, OverdueDebtClosedEvent | ActiveLoanClosedEvent | OverdueLoanClosedEvent
    ]: ...
    def execute(self, debt: ActiveDebt | OverdueDebt) -> Transition[
        ClosedDebt,
        ActiveDebtClosedEvent | OverdueDebtClosedEvent | ActiveLoanClosedEvent | OverdueLoanClosedEvent,
    ]:
        closed = [self._close(loan) for loan in debt.loans]
        loans = tuple(loan for loan, _ in closed)
        loan_events = tuple(event for _, events in closed for event in events)

        closed_debt = ClosedDebt(id=debt.id, loans=loans)
        match debt:
            case ActiveDebt():
                return Transition(closed_debt, (ActiveDebtClosedEvent(debt_id=debt.id), *loan_events))
            case OverdueDebt():
                return Transition(closed_debt, (OverdueDebtClosedEvent(debt_id=debt.id), *loan_events))

    def _close(
        self, loan: Loan
    ) -> tuple[ClosedLoan, tuple[ActiveLoanClosedEvent, ...] | tuple[OverdueLoanClosedEvent, ...]]:
        match loan:
            case ActiveLoan() | OverdueLoan():
                return self.close_loan.execute(loan)
            case ClosedLoan():
                return loan, ()


class CheckDebtOverdueDaysQuery(Query[DebtState]):
    """Overdue days of the debt: the longest overdue among its loans."""

    def execute(self, debt: OverdueDebt) -> int:
        return max(overdue_days(loan) for loan in debt.loans if isinstance(loan, OverdueLoan))
