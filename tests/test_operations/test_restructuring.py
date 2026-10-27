"""End-to-end debt restructuring scenarios, through operations only."""

from datetime import date
from decimal import Decimal

import pytest

from examples.calculations import accrued_penalty, allocate_loan, is_repaid
from examples.debt import (
    ActiveDebt,
    ActiveDebtRestructuredEvent,
    ClosedRestructuredDebt,
    OverdueDebt,
    OverdueDebtRestructuredEvent,
    RestructuredDebt,
    RestructuredDebtClosedEvent,
    RestructuringCancelledToActiveEvent,
    RestructuringCancelledToOverdueEvent,
    UnknownOriginalLoanError,
)
from examples.loan import (
    ActiveLoan,
    ActiveLoanClosedEvent,
    ClosedLoan,
    Installment,
    LoanIssuedEvent,
    LoanOverdueCancelledEvent,
    OverdueLoan,
)
from examples.payment import PaymentReceivedEvent, ReceivedPayment
from examples.restructuring import (
    ClosedRestructuring,
    LoanTerms,
    RestructuringAppliedEvent,
    RestructuringClosedEvent,
    RestructuringTerms,
)
from tests.support.wiring import (
    apply_restructuring,
    cancel_restructuring,
    close_debt,
    open_debt,
    receive_debt_payment,
    recalculate_debt,
)

ISSUED = date(2026, 1, 1)
DUE = date(2026, 1, 31)
APPLIED = date(2026, 2, 10)
FINANCED = Decimal(1000)
DAILY_PENALTY = Decimal("0.1")  # 0.01% of 1000


def installment(day: date, amount: int, original_loan_id: int = 1) -> Installment:
    return Installment(postponement_date=day, amount=Decimal(amount), original_loan_id=original_loan_id)


ONE_TO_ONE = RestructuringTerms(
    id=7,
    loans=(
        LoanTerms(
            loan_id=10,
            financed_amount=FINANCED,
            schedule=(installment(date(2026, 3, 10), 500), installment(date(2026, 4, 10), 500)),
        ),
    ),
)


def overdue_debt() -> OverdueDebt:
    debt, _ = open_debt.execute(
        debt_id=1,
        loan_id=1,
        financed_amount=FINANCED,
        booking_date=ISSUED,
        schedule=(Installment(postponement_date=DUE, amount=FINANCED),),
    )
    overdue, _ = recalculate_debt.execute(debt, booking_date=APPLIED)
    assert isinstance(overdue, OverdueDebt)
    return overdue


def restructured(terms: RestructuringTerms = ONE_TO_ONE) -> RestructuredDebt:
    debt, _ = apply_restructuring.execute(overdue_debt(), terms=terms, booking_date=APPLIED)
    return debt


def pay(debt: RestructuredDebt, loan_id: int, payment_id: int, amount: int, day: date) -> RestructuredDebt:
    loan = next(item for item in debt.restructuring.loans if item.id == loan_id)
    assert isinstance(loan, ActiveLoan)
    paid, events = receive_debt_payment.execute(
        debt, loan=loan, payment_id=payment_id, amount=Decimal(amount), paid_at=day
    )
    assert events == (PaymentReceivedEvent(payment_id=payment_id),)
    return paid


def recalculated(debt: RestructuredDebt, day: date) -> RestructuredDebt:
    moved, events = recalculate_debt.execute(debt, booking_date=day)
    assert isinstance(moved, RestructuredDebt)
    assert events == ()
    return moved


class TestApply:
    def test_apply_to_overdue_debt(self) -> None:
        debt, events = apply_restructuring.execute(overdue_debt(), terms=ONE_TO_ONE, booking_date=APPLIED)
        assert isinstance(debt, RestructuredDebt)
        assert isinstance(debt.loans[0], OverdueLoan)  # the snapshot of the original loan
        assert [loan.id for loan in debt.restructuring.loans] == [10]
        assert events == (
            OverdueDebtRestructuredEvent(debt_id=1, restructuring_id=7),
            RestructuringAppliedEvent(restructuring_id=7),
            LoanIssuedEvent(loan_id=10),
        )

    def test_terms_must_refer_to_open_loans(self) -> None:
        terms = RestructuringTerms(
            id=7,
            loans=(LoanTerms(loan_id=10, financed_amount=FINANCED, schedule=(installment(APPLIED, 1000, 99),)),),
        )
        with pytest.raises(UnknownOriginalLoanError):
            apply_restructuring.execute(overdue_debt(), terms=terms, booking_date=APPLIED)


class TestScenarios:
    def test_paid_by_new_schedule_and_closed_on_restructuring_terms(self) -> None:
        debt = restructured()
        debt = pay(debt, 10, 1, 500, date(2026, 3, 10))
        debt = recalculated(debt, date(2026, 3, 20))
        debt = pay(debt, 10, 2, 500, date(2026, 4, 10))
        debt = recalculated(debt, date(2026, 4, 10))
        assert is_repaid(debt.restructuring.loans[0])

        closed, events = close_debt.execute(debt)
        assert isinstance(closed, ClosedRestructuredDebt)
        assert isinstance(closed.restructuring, ClosedRestructuring)
        assert isinstance(closed.restructuring.loans[0], ClosedLoan)
        assert isinstance(closed.loans[0], OverdueLoan)  # the original loans stay as they were
        assert events == (
            RestructuredDebtClosedEvent(debt_id=1, restructuring_id=7),
            RestructuringClosedEvent(restructuring_id=7),
            ActiveLoanClosedEvent(loan_id=10),
        )

    def test_overdue_on_restructuring_cancels_it_in_daily_recalculation(self) -> None:
        debt = pay(restructured(), 10, 1, 300, date(2026, 3, 5))
        debt = recalculated(debt, date(2026, 3, 10))  # the first new installment is due today

        cancelled, events = recalculate_debt.execute(debt, booking_date=date(2026, 3, 11))
        assert isinstance(cancelled, OverdueDebt)
        assert cancelled.restructuring is None
        assert events == (RestructuringCancelledToOverdueEvent(debt_id=1, restructuring_id=7),)

        original = cancelled.loans[0]
        assert isinstance(original, OverdueLoan)
        assert original.booking_date == date(2026, 3, 11)
        assert original.payments == (
            ReceivedPayment(id=1, amount=Decimal(300), paid_at=date(2026, 3, 5), transferred_from_loan_id=10),
        )
        allocation = allocate_loan(original)
        # the transferred payment paid the principal, not the penalty
        assert allocation.installments_paid == (Decimal(300),)
        assert allocation.penalty_paid == 0
        # the penalty is back as if there had been no restructuring: overdue Feb 1 .. Mar 11
        assert accrued_penalty(original) == 39 * DAILY_PENALTY

    def test_manual_cancel_before_original_dates_returns_active_debt(self) -> None:
        debt, _ = open_debt.execute(
            debt_id=1,
            loan_id=1,
            financed_amount=FINANCED,
            booking_date=ISSUED,
            schedule=(Installment(postponement_date=DUE, amount=FINANCED),),
        )
        terms = RestructuringTerms(
            id=8,
            loans=(LoanTerms(loan_id=10, financed_amount=FINANCED, schedule=(installment(date(2026, 3, 31), 1000),)),),
        )
        restructured_debt, applied = apply_restructuring.execute(debt, terms=terms, booking_date=date(2026, 1, 10))
        assert applied[0] == ActiveDebtRestructuredEvent(debt_id=1, restructuring_id=8)

        cancelled, events = cancel_restructuring.execute(restructured_debt, booking_date=date(2026, 1, 20))
        assert isinstance(cancelled, ActiveDebt)
        assert isinstance(cancelled.loans[0], ActiveLoan)
        assert cancelled.loans[0].booking_date == date(2026, 1, 20)
        assert events == (RestructuringCancelledToActiveEvent(debt_id=1, restructuring_id=8),)

    def test_cancel_reactivates_original_loan_repaid_by_transfers(self) -> None:
        debt = pay(restructured(), 10, 1, 1000, date(2026, 2, 10))
        cancelled, events = cancel_restructuring.execute(debt, booking_date=date(2026, 2, 10))
        assert isinstance(cancelled, ActiveDebt)
        assert events == (
            RestructuringCancelledToActiveEvent(debt_id=1, restructuring_id=7),
            LoanOverdueCancelledEvent(loan_id=1),
        )


class TestManyToMany:
    @staticmethod
    def two_loan_debt() -> OverdueDebt:
        first = overdue_debt().loans[0]
        assert isinstance(first, OverdueLoan)
        return OverdueDebt(id=1, loans=(first, first.model_copy(update={"id": 2})))

    TERMS = RestructuringTerms(
        id=9,
        loans=(
            LoanTerms(
                loan_id=10,
                financed_amount=Decimal(600),
                schedule=(installment(date(2026, 3, 10), 300, 1), installment(date(2026, 4, 10), 300, 2)),
            ),
            LoanTerms(loan_id=11, financed_amount=Decimal(700), schedule=(installment(date(2026, 4, 10), 700, 1),)),
            LoanTerms(loan_id=12, financed_amount=Decimal(700), schedule=(installment(date(2026, 5, 10), 700, 2),)),
        ),
    )

    def test_payments_move_to_their_original_loans(self) -> None:
        debt, _ = apply_restructuring.execute(self.two_loan_debt(), terms=self.TERMS, booking_date=APPLIED)
        assert len(debt.restructuring.loans) == 3
        debt = pay(debt, 10, 1, 400, date(2026, 3, 1))  # 300 for loan 1, 100 for loan 2
        debt = pay(debt, 12, 2, 200, date(2026, 3, 2))  # loan 2
        debt = pay(debt, 11, 3, 50, date(2026, 3, 2))  # loan 1

        cancelled, _ = cancel_restructuring.execute(debt, booking_date=date(2026, 3, 3))
        assert isinstance(cancelled, OverdueDebt)
        first, second = cancelled.loans
        assert first.payments == (
            ReceivedPayment(id=1, amount=Decimal(300), paid_at=date(2026, 3, 1), transferred_from_loan_id=10),
            ReceivedPayment(id=3, amount=Decimal(50), paid_at=date(2026, 3, 2), transferred_from_loan_id=11),
        )
        assert second.payments == (
            ReceivedPayment(id=1, amount=Decimal(100), paid_at=date(2026, 3, 1), transferred_from_loan_id=10),
            ReceivedPayment(id=2, amount=Decimal(200), paid_at=date(2026, 3, 2), transferred_from_loan_id=12),
        )

    def test_overpayment_goes_to_original_loan_of_last_installment(self) -> None:
        debt, _ = apply_restructuring.execute(self.two_loan_debt(), terms=self.TERMS, booking_date=APPLIED)
        debt = pay(debt, 11, 1, 750, date(2026, 3, 1))
        cancelled, _ = cancel_restructuring.execute(debt, booking_date=date(2026, 3, 3))
        assert [payment.amount for payment in cancelled.loans[0].payments] == [Decimal(750)]
