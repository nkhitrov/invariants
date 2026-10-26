"""End-to-end scenarios of the loan/debt examples, through operations only."""

from datetime import date
from decimal import Decimal

import pytest

from examples.calculations import accrued_penalty, is_repaid, outstanding_amount, overdue_installments, paid_amount
from examples.debt import (
    ActiveDebt,
    ActiveDebtClosedEvent,
    CancelDebtOverdueOperation,
    CheckDebtOverdueDaysQuery,
    CloseDebtOperation,
    ClosedDebt,
    DebtBecameOverdueEvent,
    DebtOpenedEvent,
    DebtOverdueCancelledEvent,
    DebtStillOverdueError,
    LoanNotFoundError,
    OpenDebtOperation,
    OverdueDebt,
    OverdueDebtClosedEvent,
    RecalculateDebtOperation,
    ReceiveDebtPaymentOperation,
)
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
    LoanNotRepaidError,
    LoanOverdueCancelledEvent,
    LoanStillOverdueError,
    OverdueLoan,
    OverdueLoanClosedEvent,
    ReceiveLoanPaymentOperation,
    RecalculateLoanTermsOperation,
)
from examples.payment import PaymentReceivedEvent, ReceivePaymentOperation

ISSUED = date(2026, 1, 1)
FIRST_DUE = date(2026, 1, 31)
SECOND_DUE = date(2026, 2, 28)
FINANCED = Decimal(1000)
# 0.01% of 1000 per overdue day
DAILY_PENALTY = Decimal("0.1")

ONE_DATE = (Installment(postponement_date=FIRST_DUE, amount=FINANCED),)
TWO_INSTALLMENTS = (
    Installment(postponement_date=FIRST_DUE, amount=Decimal(500)),
    Installment(postponement_date=SECOND_DUE, amount=Decimal(500)),
)

open_debt = OpenDebtOperation(issue_loan=IssueLoanOperation())
recalculate_debt = RecalculateDebtOperation(
    recalculate_loan_terms=RecalculateLoanTermsOperation(), accrue_penalty=AccruePenaltyOperation()
)
receive_loan_payment = ReceiveLoanPaymentOperation(receive_payment=ReceivePaymentOperation())
cancel_loan_overdue = CancelLoanOverdueOperation()
cancel_debt_overdue = CancelDebtOverdueOperation(cancel_loan_overdue=cancel_loan_overdue)
receive_debt_payment = ReceiveDebtPaymentOperation(
    receive_loan_payment=receive_loan_payment,
    cancel_loan_overdue=cancel_loan_overdue,
    cancel_debt_overdue=cancel_debt_overdue,
)
close_debt = CloseDebtOperation(close_loan=CloseLoanOperation())


def opened(schedule: tuple[Installment, ...] = TWO_INSTALLMENTS) -> ActiveDebt:
    debt, _ = open_debt.execute(
        debt_id=1, loan_id=1, financed_amount=FINANCED, booking_date=ISSUED, schedule=schedule
    )
    return debt


def overdue_on(day: date, schedule: tuple[Installment, ...] = TWO_INSTALLMENTS) -> OverdueDebt:
    debt, _ = recalculate_debt.execute(opened(schedule), booking_date=day)
    assert isinstance(debt, OverdueDebt)
    return debt


def overdue_loan_of(debt: OverdueDebt) -> OverdueLoan:
    loan = debt.loans[0]
    assert isinstance(loan, OverdueLoan)
    return loan


class TestDebtLifecycle:
    def test_open_debt_with_first_loan(self) -> None:
        debt, events = open_debt.execute(
            debt_id=1, loan_id=1, financed_amount=FINANCED, booking_date=ISSUED, schedule=TWO_INSTALLMENTS
        )
        assert isinstance(debt, ActiveDebt)
        assert isinstance(debt.loans[0], ActiveLoan)
        assert events == (DebtOpenedEvent(debt_id=1), LoanIssuedEvent(loan_id=1))

    def test_recalculation_before_due_date_is_a_silent_loop(self) -> None:
        debt, events = recalculate_debt.execute(opened(), booking_date=FIRST_DUE)
        assert isinstance(debt, ActiveDebt)
        assert debt.loans[0].booking_date == FIRST_DUE
        assert events == ()

    def test_unpaid_installment_makes_loan_and_debt_overdue(self) -> None:
        debt, events = recalculate_debt.execute(opened(), booking_date=date(2026, 2, 1))
        assert isinstance(debt, OverdueDebt)
        assert isinstance(debt.loans[0], OverdueLoan)
        assert events == (DebtBecameOverdueEvent(debt_id=1), LoanBecameOverdueEvent(loan_id=1))
        assert accrued_penalty(debt.loans[0]) == DAILY_PENALTY

    def test_penalty_grows_while_overdue(self) -> None:
        debt = overdue_on(date(2026, 2, 1))
        debt, events = recalculate_debt.execute(debt, booking_date=date(2026, 2, 10))
        assert events == ()
        assert accrued_penalty(debt.loans[0]) == 10 * DAILY_PENALTY
        assert CheckDebtOverdueDaysQuery().execute(debt) == 10

    def test_partial_payment_keeps_overdue(self) -> None:
        debt = overdue_on(date(2026, 2, 10))
        debt_after, events = receive_debt_payment.execute(
            debt, loan=overdue_loan_of(debt), payment_id=1, amount=Decimal(200), paid_at=date(2026, 2, 10)
        )
        assert isinstance(debt_after, OverdueDebt)
        assert events == (PaymentReceivedEvent(payment_id=1),)
        assert paid_amount(debt_after.loans[0]) == Decimal(200)

    def test_paying_overdue_cancels_the_overdue(self) -> None:
        debt = overdue_on(date(2026, 2, 10))
        # the penalty is paid first, then the overdue installment
        amount = 10 * DAILY_PENALTY + Decimal(500)
        debt_after, events = receive_debt_payment.execute(
            debt, loan=overdue_loan_of(debt), payment_id=1, amount=amount, paid_at=date(2026, 2, 10)
        )
        assert isinstance(debt_after, ActiveDebt)
        assert isinstance(debt_after.loans[0], ActiveLoan)
        assert events == (
            PaymentReceivedEvent(payment_id=1),
            DebtOverdueCancelledEvent(debt_id=1),
            LoanOverdueCancelledEvent(loan_id=1),
        )
        assert outstanding_amount(debt_after.loans[0]) == Decimal(500)

    def test_paying_the_rest_closes_the_debt(self) -> None:
        debt = overdue_on(date(2026, 2, 10))
        active, _ = receive_debt_payment.execute(
            debt, loan=overdue_loan_of(debt), payment_id=1, amount=Decimal("501"), paid_at=date(2026, 2, 10)
        )
        assert isinstance(active, ActiveDebt)
        active, recalculated = recalculate_debt.execute(active, booking_date=date(2026, 2, 20))
        assert isinstance(active, ActiveDebt)
        assert recalculated == ()

        loan = active.loans[0]
        assert isinstance(loan, ActiveLoan)
        paid, payment_events = receive_debt_payment.execute(
            active, loan=loan, payment_id=2, amount=Decimal(500), paid_at=date(2026, 2, 20)
        )
        assert payment_events == (PaymentReceivedEvent(payment_id=2),)
        assert is_repaid(paid.loans[0])

        closed, closing_events = close_debt.execute(paid)
        assert isinstance(closed, ClosedDebt)
        assert isinstance(closed.loans[0], ClosedLoan)
        assert closing_events == (ActiveDebtClosedEvent(debt_id=1), ActiveLoanClosedEvent(loan_id=1))

    def test_close_overdue_debt_once_repaid(self) -> None:
        debt = overdue_on(date(2026, 2, 1), ONE_DATE)
        loan = overdue_loan_of(debt)
        paid, _ = receive_loan_payment.execute(
            loan, payment_id=1, amount=FINANCED + DAILY_PENALTY, paid_at=date(2026, 2, 1)
        )
        closed, events = close_debt.execute(OverdueDebt(id=1, loans=(paid,)))
        assert isinstance(closed, ClosedDebt)
        assert events == (OverdueDebtClosedEvent(debt_id=1), OverdueLoanClosedEvent(loan_id=1))

    def test_debt_with_another_overdue_loan_stays_overdue(self) -> None:
        first = overdue_loan_of(overdue_on(date(2026, 2, 1)))
        second = first.model_copy(update={"id": 2})
        debt = OverdueDebt(id=1, loans=(first, second))

        debt_after, events = receive_debt_payment.execute(
            debt, loan=first, payment_id=1, amount=Decimal("500.1"), paid_at=date(2026, 2, 1)
        )
        assert isinstance(debt_after, OverdueDebt)
        assert [type(loan) for loan in debt_after.loans] == [ActiveLoan, OverdueLoan]
        assert events == (PaymentReceivedEvent(payment_id=1), LoanOverdueCancelledEvent(loan_id=1))

    def test_payment_to_active_loan_of_overdue_debt(self) -> None:
        overdue = overdue_loan_of(overdue_on(date(2026, 2, 1)))
        active, _ = cancel_loan_overdue.execute(overdue, schedule=(Installment(postponement_date=SECOND_DUE, amount=FINANCED),))
        debt = OverdueDebt(id=1, loans=(overdue.model_copy(update={"id": 2}), active))

        debt_after, events = receive_debt_payment.execute(
            debt, loan=active, payment_id=1, amount=Decimal(100), paid_at=date(2026, 2, 1)
        )
        assert isinstance(debt_after, OverdueDebt)
        assert events == (PaymentReceivedEvent(payment_id=1),)

    def test_cancel_debt_overdue_requires_no_other_overdue_loans(self) -> None:
        first = overdue_loan_of(overdue_on(date(2026, 2, 1)))
        debt = OverdueDebt(id=1, loans=(first, first.model_copy(update={"id": 2})))
        restructured = (Installment(postponement_date=SECOND_DUE, amount=FINANCED),)
        with pytest.raises(DebtStillOverdueError):
            cancel_debt_overdue.execute(debt, loan=first, schedule=restructured)

    def test_unknown_loan(self) -> None:
        debt = overdue_on(date(2026, 2, 1))
        stranger = overdue_loan_of(debt).model_copy(update={"id": 42})
        with pytest.raises(LoanNotFoundError):
            receive_debt_payment.execute(debt, loan=stranger, payment_id=1, amount=Decimal(1), paid_at=date(2026, 2, 1))


class TestLoanWithSchedule:
    def overdue_loan(self) -> OverdueLoan:
        return overdue_loan_of(overdue_on(date(2026, 2, 5)))

    def test_paying_overdue_installment_reactivates_the_loan(self) -> None:
        loan = self.overdue_loan()
        paid, events = receive_loan_payment.execute(
            loan, payment_id=1, amount=Decimal("500.5"), paid_at=date(2026, 2, 5)
        )
        assert isinstance(paid, OverdueLoan)
        assert events == (PaymentReceivedEvent(payment_id=1),)
        assert overdue_installments(paid) == ()

        active, cancel_events = cancel_loan_overdue.execute(paid, schedule=paid.schedule)
        assert isinstance(active, ActiveLoan)
        assert cancel_events == (LoanOverdueCancelledEvent(loan_id=1),)

    def test_cannot_cancel_with_overdue_installment(self) -> None:
        loan = self.overdue_loan()
        with pytest.raises(LoanStillOverdueError):
            cancel_loan_overdue.execute(loan, schedule=loan.schedule)

    def test_restructuring_cancels_with_new_schedule(self) -> None:
        loan = self.overdue_loan()
        new_schedule = (Installment(postponement_date=date(2026, 3, 31), amount=FINANCED),)
        active, _ = cancel_loan_overdue.execute(loan, schedule=new_schedule)
        assert active.schedule == new_schedule

    def test_cannot_close_unpaid_loan(self) -> None:
        with pytest.raises(LoanNotRepaidError):
            CloseLoanOperation().execute(self.overdue_loan())

    def test_penalty_stops_after_overdue_is_paid(self) -> None:
        loan = self.overdue_loan()  # 5 overdue days
        paid, _ = receive_loan_payment.execute(loan, payment_id=1, amount=Decimal("500.5"), paid_at=date(2026, 2, 5))
        later, _ = AccruePenaltyOperation().execute(paid, booking_date=date(2026, 2, 20))
        assert accrued_penalty(later) == 5 * DAILY_PENALTY

    def test_payment_amount_must_be_positive(self) -> None:
        with pytest.raises(ValueError, match="positive"):
            receive_loan_payment.execute(self.overdue_loan(), payment_id=1, amount=Decimal(0), paid_at=FIRST_DUE)
