from datetime import date
from decimal import Decimal
from typing import Never, overload

from examples.calculations import overdue_days, overdue_installments
from examples.debt.events import (
    ActiveDebtClosedEvent,
    ActiveDebtRestructuredEvent,
    DebtBecameOverdueEvent,
    DebtOpenedEvent,
    DebtOverdueCancelledEvent,
    OverdueDebtClosedEvent,
    OverdueDebtRestructuredEvent,
    RestructuredDebtClosedEvent,
    RestructuringCancelledToActiveEvent,
    RestructuringCancelledToOverdueEvent,
)
from examples.debt.states import (
    ActiveDebt,
    ClosedDebt,
    ClosedRestructuredDebt,
    DebtState,
    Loan,
    OverdueDebt,
    RestructuredDebt,
)
from examples.loan.events import (
    ActiveLoanClosedEvent,
    LoanBecameOverdueEvent,
    LoanIssuedEvent,
    LoanOverdueCancelledEvent,
    OverdueLoanClosedEvent,
)
from examples.loan.operations import (
    AccruePenaltyOperation,
    CancelLoanOverdueOperation,
    CloseLoanOperation,
    IssueLoanOperation,
    RecalculateLoanTermsOperation,
    ReceiveLoanPaymentOperation,
    loan_fields,
)
from examples.loan.states import ActiveLoan, ClosedLoan, Installment, OverdueLoan
from examples.payment.events import PaymentReceivedEvent
from examples.payment.states import ReceivedPayment
from examples.restructuring.events import (
    RestructuringAppliedEvent,
    RestructuringClosedEvent,
)
from examples.restructuring.operations import (
    CloseRestructuringOperation,
    OpenRestructuringOperation,
    transferred_payments,
)
from examples.restructuring.states import ActiveRestructuring, RestructuringTerms
from invariants.operations import Operation, Query, Transition


class LoanNotFoundError(LookupError):
    def __init__(self, loan_id: int) -> None:
        super().__init__(f"Loan {loan_id} is not found in the debt")
        self.loan_id = loan_id


class DebtStillOverdueError(ValueError):
    def __init__(self, debt_id: int) -> None:
        super().__init__(f"Debt {debt_id} still has overdue loans")
        self.debt_id = debt_id


class UnknownOriginalLoanError(ValueError):
    def __init__(self, loan_id: int) -> None:
        super().__init__(f"Restructuring terms refer to loan {loan_id}, which is not an open loan of the debt")
        self.loan_id = loan_id


def replace_loan(loans: tuple[Loan, ...], loan: Loan) -> tuple[Loan, ...]:
    """Put the new state of a loan in place of its previous state."""
    if all(item.id != loan.id for item in loans):
        raise LoanNotFoundError(loan.id)
    return tuple(loan if item.id == loan.id else item for item in loans)


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


class ApplyRestructuringOperation(Operation[DebtState]):
    """Apply approved restructuring terms: the restructuring loans replace the original ones.

    It can be applied to an overdue debt, or in advance to an active one.
    """

    open_restructuring: OpenRestructuringOperation

    @overload
    def execute(
        self, debt: ActiveDebt, *, terms: RestructuringTerms, booking_date: date
    ) -> Transition[RestructuredDebt, ActiveDebtRestructuredEvent | RestructuringAppliedEvent | LoanIssuedEvent]: ...
    @overload
    def execute(
        self, debt: OverdueDebt, *, terms: RestructuringTerms, booking_date: date
    ) -> Transition[RestructuredDebt, OverdueDebtRestructuredEvent | RestructuringAppliedEvent | LoanIssuedEvent]: ...
    def execute(self, debt: ActiveDebt | OverdueDebt, *, terms: RestructuringTerms, booking_date: date) -> Transition[
        RestructuredDebt,
        ActiveDebtRestructuredEvent | OverdueDebtRestructuredEvent | RestructuringAppliedEvent | LoanIssuedEvent,
    ]:
        open_loans = {loan.id for loan in debt.loans if not isinstance(loan, ClosedLoan)}
        for loan_terms in terms.loans:
            for installment in loan_terms.schedule:
                if installment.original_loan_id not in open_loans:
                    raise UnknownOriginalLoanError(installment.original_loan_id or 0)

        restructuring, events = self.open_restructuring.execute(terms=terms, booking_date=booking_date)
        restructured = RestructuredDebt(id=debt.id, loans=debt.loans, restructuring=restructuring)
        match debt:
            case ActiveDebt():
                applied = ActiveDebtRestructuredEvent(debt_id=debt.id, restructuring_id=terms.id)
                return Transition(restructured, (applied, *events))
            case OverdueDebt():
                overdue_applied = OverdueDebtRestructuredEvent(debt_id=debt.id, restructuring_id=terms.id)
                return Transition(restructured, (overdue_applied, *events))


class CancelRestructuringOperation(Operation[DebtState]):
    """Cancel a restructuring and roll the debt back to its original loans.

    The application calls it directly (e.g. the client broke other terms), and the daily
    recalculation delegates to it once a restructuring loan would become overdue.
    Payments made to the restructuring loans move to the original loans by the installment
    mapping (they pay the principal before the penalty); then the original loans are
    recalculated on ``booking_date`` by their own schedule, so the penalty is computed as if
    there had been no restructuring.
    """

    recalculate_loan_terms: RecalculateLoanTermsOperation
    accrue_penalty: AccruePenaltyOperation
    cancel_loan_overdue: CancelLoanOverdueOperation

    def execute(self, debt: RestructuredDebt, *, booking_date: date) -> (
        Transition[
            OverdueDebt, RestructuringCancelledToOverdueEvent | LoanBecameOverdueEvent | LoanOverdueCancelledEvent
        ]
        | Transition[ActiveDebt, RestructuringCancelledToActiveEvent | LoanOverdueCancelledEvent]
    ):
        transfers = transferred_payments(debt.restructuring.loans)
        rolled_back = [self._roll_back(loan, transfers.get(loan.id, ()), booking_date) for loan in debt.loans]
        loans = tuple(loan for loan, _ in rolled_back)
        loan_events = tuple(event for _, events in rolled_back for event in events)
        restructuring_id = debt.restructuring.id

        if any(isinstance(loan, OverdueLoan) for loan in loans):
            overdue: Transition[
                OverdueDebt, RestructuringCancelledToOverdueEvent | LoanBecameOverdueEvent | LoanOverdueCancelledEvent
            ] = Transition(
                OverdueDebt(id=debt.id, loans=loans),
                (RestructuringCancelledToOverdueEvent(debt_id=debt.id, restructuring_id=restructuring_id), *loan_events),
            )
            return overdue

        cancelled_events = tuple(event for event in loan_events if isinstance(event, LoanOverdueCancelledEvent))
        active: Transition[ActiveDebt, RestructuringCancelledToActiveEvent | LoanOverdueCancelledEvent] = Transition(
            ActiveDebt(id=debt.id, loans=tuple(loan for loan in loans if not isinstance(loan, OverdueLoan))),
            (RestructuringCancelledToActiveEvent(debt_id=debt.id, restructuring_id=restructuring_id), *cancelled_events),
        )
        return active

    def _roll_back(
        self, loan: Loan, transferred: tuple[ReceivedPayment, ...], booking_date: date
    ) -> tuple[Loan, tuple[LoanBecameOverdueEvent | LoanOverdueCancelledEvent, ...]]:
        payments = (*loan.payments, *transferred)
        match loan:
            case ActiveLoan():
                return self.recalculate_loan_terms.execute(
                    ActiveLoan(**loan_fields(loan, payments=payments)), booking_date=booking_date
                )
            case OverdueLoan():
                overdue, _ = self.accrue_penalty.execute(
                    OverdueLoan(**loan_fields(loan, payments=payments)), booking_date=booking_date
                )
                if overdue_installments(overdue):
                    return overdue, ()
                return self.cancel_loan_overdue.execute(overdue, schedule=overdue.schedule)
            case ClosedLoan():
                return loan, ()


class RecalculateDebtOperation(Operation[DebtState]):
    """Daily recalculation: move the booking date of every open loan.

    Active loans may become overdue (and then the debt does), overdue loans accrue penalty,
    closed loans are left as they are. A restructured debt recalculates its restructuring
    loans; once one of them would become overdue, the restructuring is cancelled.
    """

    recalculate_loan_terms: RecalculateLoanTermsOperation
    accrue_penalty: AccruePenaltyOperation
    cancel_restructuring: CancelRestructuringOperation

    @overload
    def execute(self, debt: ActiveDebt, *, booking_date: date) -> (
        Transition[OverdueDebt, DebtBecameOverdueEvent | LoanBecameOverdueEvent]
        | Transition[ActiveDebt, Never]
    ): ...
    @overload
    def execute(self, debt: OverdueDebt, *, booking_date: date) -> Transition[OverdueDebt, LoanBecameOverdueEvent]: ...
    @overload
    def execute(self, debt: RestructuredDebt, *, booking_date: date) -> (
        Transition[RestructuredDebt, Never]
        | Transition[
            OverdueDebt, RestructuringCancelledToOverdueEvent | LoanBecameOverdueEvent | LoanOverdueCancelledEvent
        ]
        | Transition[ActiveDebt, RestructuringCancelledToActiveEvent | LoanOverdueCancelledEvent]
    ): ...
    def execute(self, debt: ActiveDebt | OverdueDebt | RestructuredDebt, *, booking_date: date) -> (
        Transition[OverdueDebt, DebtBecameOverdueEvent | LoanBecameOverdueEvent]
        | Transition[ActiveDebt, Never]
        | Transition[RestructuredDebt, Never]
        | Transition[
            OverdueDebt, RestructuringCancelledToOverdueEvent | LoanBecameOverdueEvent | LoanOverdueCancelledEvent
        ]
        | Transition[ActiveDebt, RestructuringCancelledToActiveEvent | LoanOverdueCancelledEvent]
    ):
        if isinstance(debt, RestructuredDebt):
            return self._recalculate_restructured(debt, booking_date)

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
                became_overdue: Transition[OverdueDebt, DebtBecameOverdueEvent | LoanBecameOverdueEvent] = Transition(
                    OverdueDebt(id=debt.id, loans=loans),
                    (DebtBecameOverdueEvent(debt_id=debt.id), *loan_events),
                )
                return became_overdue
            case OverdueDebt():
                still_overdue: Transition[OverdueDebt, LoanBecameOverdueEvent] = Transition(
                    OverdueDebt(id=debt.id, loans=loans), loan_events
                )
                return still_overdue

    def _recalculate_restructured(self, debt: RestructuredDebt, booking_date: date) -> (
        Transition[RestructuredDebt, Never]
        | Transition[
            OverdueDebt, RestructuringCancelledToOverdueEvent | LoanBecameOverdueEvent | LoanOverdueCancelledEvent
        ]
        | Transition[ActiveDebt, RestructuringCancelledToActiveEvent | LoanOverdueCancelledEvent]
    ):
        moved = tuple(loan for loan, _ in (self._recalculate(loan, booking_date) for loan in debt.restructuring.loans))
        if any(isinstance(loan, OverdueLoan) for loan in moved):
            # An overdue breaks the restructuring agreement
            return self.cancel_restructuring.execute(debt, booking_date=booking_date)
        restructuring = ActiveRestructuring(
            id=debt.restructuring.id,
            applied_at=debt.restructuring.applied_at,
            loans=tuple(loan for loan in moved if not isinstance(loan, OverdueLoan)),
        )
        unchanged: Transition[RestructuredDebt, Never] = Transition(
            RestructuredDebt(id=debt.id, loans=debt.loans, restructuring=restructuring), ()
        )
        return unchanged

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
        self, debt: RestructuredDebt, *, loan: ActiveLoan, payment_id: int, amount: Decimal, paid_at: date
    ) -> Transition[RestructuredDebt, PaymentReceivedEvent]: ...
    @overload
    def execute(
        self, debt: OverdueDebt, *, loan: ActiveLoan | OverdueLoan, payment_id: int, amount: Decimal, paid_at: date
    ) -> (
        Transition[ActiveDebt, DebtOverdueCancelledEvent | LoanOverdueCancelledEvent | PaymentReceivedEvent]
        | Transition[OverdueDebt, LoanOverdueCancelledEvent | PaymentReceivedEvent]
    ): ...
    def execute(
        self,
        debt: ActiveDebt | OverdueDebt | RestructuredDebt,
        *,
        loan: ActiveLoan | OverdueLoan,
        payment_id: int,
        amount: Decimal,
        paid_at: date,
    ) -> (
        Transition[ActiveDebt, PaymentReceivedEvent]
        | Transition[RestructuredDebt, PaymentReceivedEvent]
        | Transition[ActiveDebt, DebtOverdueCancelledEvent | LoanOverdueCancelledEvent | PaymentReceivedEvent]
        | Transition[OverdueDebt, LoanOverdueCancelledEvent | PaymentReceivedEvent]
    ):
        paid_loan, payment_events = self.receive_loan_payment.execute(
            loan, payment_id=payment_id, amount=amount, paid_at=paid_at
        )

        if isinstance(debt, RestructuredDebt):
            # Payments of a restructured debt go to its restructuring loans
            restructuring = ActiveRestructuring(
                id=debt.restructuring.id,
                applied_at=debt.restructuring.applied_at,
                loans=tuple(
                    item
                    for item in replace_loan(debt.restructuring.loans, paid_loan)
                    if not isinstance(item, OverdueLoan)
                ),
            )
            restructured: Transition[RestructuredDebt, PaymentReceivedEvent] = Transition(
                RestructuredDebt(id=debt.id, loans=debt.loans, restructuring=restructuring), payment_events
            )
            return restructured

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
    """Close a debt: every loan that is not closed yet must be repaid and gets closed.

    A restructured debt is closed on the restructuring terms: its restructuring is closed, and
    the original loans stay as they were when the restructuring was applied.
    """

    close_loan: CloseLoanOperation
    close_restructuring: CloseRestructuringOperation

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
    @overload
    def execute(
        self, debt: RestructuredDebt
    ) -> Transition[
        ClosedRestructuredDebt, RestructuredDebtClosedEvent | RestructuringClosedEvent | ActiveLoanClosedEvent
    ]: ...
    def execute(self, debt: ActiveDebt | OverdueDebt | RestructuredDebt) -> (
        Transition[
            ClosedDebt,
            ActiveDebtClosedEvent | OverdueDebtClosedEvent | ActiveLoanClosedEvent | OverdueLoanClosedEvent,
        ]
        | Transition[
            ClosedRestructuredDebt, RestructuredDebtClosedEvent | RestructuringClosedEvent | ActiveLoanClosedEvent
        ]
    ):
        if isinstance(debt, RestructuredDebt):
            restructuring, events = self.close_restructuring.execute(debt.restructuring)
            closed_restructured = ClosedRestructuredDebt(id=debt.id, loans=debt.loans, restructuring=restructuring)
            on_terms: Transition[
                ClosedRestructuredDebt, RestructuredDebtClosedEvent | RestructuringClosedEvent | ActiveLoanClosedEvent
            ] = Transition(
                closed_restructured,
                (RestructuredDebtClosedEvent(debt_id=debt.id, restructuring_id=restructuring.id), *events),
            )
            return on_terms

        closed = [self._close(loan) for loan in debt.loans]
        loans = tuple(loan for loan, _ in closed)
        loan_events = tuple(event for _, events in closed for event in events)

        closed_debt = ClosedDebt(id=debt.id, loans=loans)
        closed_event = ActiveDebtClosedEvent(debt_id=debt.id) if isinstance(debt, ActiveDebt) else (
            OverdueDebtClosedEvent(debt_id=debt.id)
        )
        closed_transition: Transition[
            ClosedDebt,
            ActiveDebtClosedEvent | OverdueDebtClosedEvent | ActiveLoanClosedEvent | OverdueLoanClosedEvent,
        ] = Transition(closed_debt, (closed_event, *loan_events))
        return closed_transition

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
