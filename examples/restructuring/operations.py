from collections import defaultdict
from datetime import date
from decimal import Decimal

from examples.calculations import ZERO
from examples.loan.events import ActiveLoanClosedEvent, LoanIssuedEvent
from examples.loan.operations import CloseLoanOperation, IssueLoanOperation
from examples.loan.states import ActiveLoan, ClosedLoan, Installment
from examples.payment.states import ReceivedPayment
from examples.restructuring.events import (
    RestructuringAppliedEvent,
    RestructuringClosedEvent,
)
from examples.restructuring.states import (
    ActiveRestructuring,
    ClosedRestructuring,
    RestructuringState,
    RestructuringTerms,
)
from invariants.operations import Operation, Transition


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
