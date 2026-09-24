from datetime import datetime

import pytest

from pydantic import ValidationError

from tests.support.states import (
    ActiveLoan,
    ClosedLoan,
    OverdueLoan,
    ActiveDebt,
    ClosedDebt,
    OverdueDebt,
)


class TestStateCollections:
    def test_contains_one(self) -> None:
        active_loan = ActiveLoan(id=1, postponement_date=datetime(2024, 1, 1))
        closed_loan = ClosedLoan(id=2)
        overdue_loan = OverdueLoan(id=3, postponement_date=datetime(2024, 6, 1))

        active_debt = ActiveDebt(
            loans=(
                active_loan,
                closed_loan,
            )
        )
        assert active_debt.loans == (active_loan, closed_loan)

        closed_debt = ClosedDebt(
            loans=(
                closed_loan,
                closed_loan,
            )
        )
        assert closed_debt.loans == (closed_loan, closed_loan)

        overdue_debt = OverdueDebt(
            loans=(
                overdue_loan,
                active_loan,
                closed_loan,
            )
        )
        assert overdue_debt.loans == (overdue_loan, active_loan, closed_loan)

    def test_contains_one_error_empty(self) -> None:
        with pytest.raises(ValidationError) as excinfo:
            OverdueDebt(loans=())

        error = excinfo.value.errors()[0]
        assert error["type"] == "value_error"
        assert "must contains one or more item of type" in error["msg"]
        assert "OverdueLoan" in error["msg"]

    def test_contains_one_error_missing_type(self) -> None:
        loans = (
            ActiveLoan(id=1, postponement_date=datetime(2024, 1, 1)),
            ClosedLoan(id=2),
        )
        with pytest.raises(ValidationError) as excinfo:
            OverdueDebt(loans=loans)

        error = excinfo.value.errors()[0]
        assert error["type"] == "value_error"
        assert "must contains one or more item of type" in error["msg"]
        assert "OverdueLoan" in error["msg"]
