from datetime import datetime

import pytest

from examples.debt import (
    ActivateDebtLoanOperation,
    ActiveDebt,
    ActiveDebtClosedEvent,
    AddLoanToDebtOperation,
    CheckDebtOverdueDaysQuery,
    CloseDebtOperation,
    ClosedDebt,
    CreateDebtOperation,
    DebtBecameActiveEvent,
    DebtBecameOverdueEvent,
    DebtCreatedEvent,
    LoanNotFoundError,
    MakeDebtOverdueOperation,
    OverdueDebt,
    OverdueDebtClosedEvent,
)
from examples.loan import (
    ActivateLoanOperation,
    ActiveLoan,
    ActiveLoanClosedEvent,
    CloseLoanOperation,
    ClosedLoan,
    IssueLoanOperation,
    LoanActivatedEvent,
    LoanBecameOverdueEvent,
    LoanIssuedEvent,
    MakeLoanOverdueOperation,
    OverdueLoan,
    OverdueLoanClosedEvent,
)

DATE = datetime(2026, 1, 1)
LATER = datetime(2026, 3, 1)


def active_debt() -> ActiveDebt:
    return ActiveDebt(
        id=1,
        loans=(ActiveLoan(id=1, postponement_date=DATE), ActiveLoan(id=2, postponement_date=DATE)),
    )


def overdue_debt() -> OverdueDebt:
    return OverdueDebt(
        id=1,
        loans=(OverdueLoan(id=1, postponement_date=DATE), ActiveLoan(id=2, postponement_date=DATE)),
    )


class TestLoanOperations:
    def test_issue(self) -> None:
        loan, events = IssueLoanOperation().execute(loan_id=1, postponement_date=DATE)
        assert loan == ActiveLoan(id=1, postponement_date=DATE)
        assert events == (LoanIssuedEvent(loan_id=1),)

    def test_activate(self) -> None:
        loan, events = ActivateLoanOperation().execute(
            OverdueLoan(id=1, postponement_date=DATE), postponement_date=LATER
        )
        assert loan == ActiveLoan(id=1, postponement_date=LATER)
        assert events == (LoanActivatedEvent(loan_id=1),)

    def test_close_active(self) -> None:
        loan, events = CloseLoanOperation().execute(ActiveLoan(id=1, postponement_date=DATE))
        assert loan == ClosedLoan(id=1)
        assert events == (ActiveLoanClosedEvent(loan_id=1),)


class TestDebtOperations:
    def test_create(self) -> None:
        operation = CreateDebtOperation(issue_loan=IssueLoanOperation())
        debt, events = operation.execute(debt_id=1, loan_id=1, postponement_date=DATE)
        assert debt == ActiveDebt(id=1, loans=(ActiveLoan(id=1, postponement_date=DATE),))
        assert events == (DebtCreatedEvent(debt_id=1), LoanIssuedEvent(loan_id=1))

    def test_add_loan_is_loop_with_nested_event(self) -> None:
        operation = AddLoanToDebtOperation(issue_loan=IssueLoanOperation())
        debt, events = operation.execute(active_debt(), loan_id=3, postponement_date=DATE)
        assert [loan.id for loan in debt.loans] == [1, 2, 3]
        assert events == (LoanIssuedEvent(loan_id=3),)

    def test_make_overdue_moves_nested_loan(self) -> None:
        operation = MakeDebtOverdueOperation(make_loan_overdue=MakeLoanOverdueOperation())
        debt, events = operation.execute(active_debt(), loan_id=1)
        assert debt == overdue_debt()
        assert events == (
            DebtBecameOverdueEvent(debt_id=1, overdue_loan_id=1),
            LoanBecameOverdueEvent(loan_id=1),
        )

    def test_make_overdue_unknown_loan(self) -> None:
        operation = MakeDebtOverdueOperation(make_loan_overdue=MakeLoanOverdueOperation())
        with pytest.raises(LoanNotFoundError):
            operation.execute(active_debt(), loan_id=42)

    def test_activate_last_overdue_loan(self) -> None:
        operation = ActivateDebtLoanOperation(activate_loan=ActivateLoanOperation())
        debt, events = operation.execute(overdue_debt(), loan_id=1, postponement_date=LATER)
        assert isinstance(debt, ActiveDebt)
        assert events == (DebtBecameActiveEvent(debt_id=1), LoanActivatedEvent(loan_id=1))

    def test_activate_keeps_debt_overdue(self) -> None:
        debt = OverdueDebt(
            id=1,
            loans=(OverdueLoan(id=1, postponement_date=DATE), OverdueLoan(id=2, postponement_date=DATE)),
        )
        operation = ActivateDebtLoanOperation(activate_loan=ActivateLoanOperation())
        new_debt, events = operation.execute(debt, loan_id=1, postponement_date=LATER)
        assert isinstance(new_debt, OverdueDebt)
        assert events == (LoanActivatedEvent(loan_id=1),)

    def test_activate_unknown_loan(self) -> None:
        operation = ActivateDebtLoanOperation(activate_loan=ActivateLoanOperation())
        with pytest.raises(LoanNotFoundError):
            operation.execute(overdue_debt(), loan_id=42, postponement_date=LATER)

    def test_close_active(self) -> None:
        operation = CloseDebtOperation(close_loan=CloseLoanOperation())
        debt, events = operation.execute(active_debt())
        assert debt == ClosedDebt(id=1, loans=(ClosedLoan(id=1), ClosedLoan(id=2)))
        assert events == (
            ActiveDebtClosedEvent(debt_id=1),
            ActiveLoanClosedEvent(loan_id=1),
            ActiveLoanClosedEvent(loan_id=2),
        )

    def test_close_overdue(self) -> None:
        debt = OverdueDebt(
            id=1,
            loans=(OverdueLoan(id=1, postponement_date=DATE), ClosedLoan(id=2)),
        )
        operation = CloseDebtOperation(close_loan=CloseLoanOperation())
        closed, events = operation.execute(debt)
        assert closed == ClosedDebt(id=1, loans=(ClosedLoan(id=1), ClosedLoan(id=2)))
        assert events == (OverdueDebtClosedEvent(debt_id=1), OverdueLoanClosedEvent(loan_id=1))

    def test_overdue_days_query(self) -> None:
        assert CheckDebtOverdueDaysQuery().execute(overdue_debt(), now=LATER) == 59
