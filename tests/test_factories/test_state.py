from __future__ import annotations

from datetime import datetime

import pytest

from invariants.factories import StateFactory
from tests.support.states import LoanState, ActiveLoan


class TestStateFactory:
    def test_factory_validation(self) -> None:
        with pytest.raises(TypeError):
            class InvalidFactory(StateFactory[LoanState]): ...

    def test_factory_build(self) -> None:
        class ActiveLoanFactory(StateFactory[ActiveLoan]): ...

        loan = ActiveLoanFactory.build()
        assert isinstance(loan, ActiveLoan)
        assert loan.status == "active"
        assert isinstance(loan.id, int)
        assert isinstance(loan.postponement_date, datetime)
