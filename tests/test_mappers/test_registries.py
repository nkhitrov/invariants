from __future__ import annotations

from datetime import datetime
from typing import TypeVar

import pytest
from sqlalchemy import Column, ForeignKey, Integer
from sqlalchemy.orm import Mapped, mapped_column, relationship

from invariants.mappers import (
    MapperRegistry,
    MapperRegistryError,
    StateMapper,
)
from invariants.state import State
from tests.support.orm import Base
from tests.support.states import ActiveDebt, ActiveLoan, ClosedLoan

# A base mapper must stay generic so that concrete mappers can parametrize it,
# mirroring how a generic base is declared elsewhere.
_R = TypeVar("_R", bound=State)
_T = TypeVar("_T")


class _RegLoanORM(Base):
    __tablename__ = "reg_loan"
    id = Column(Integer, primary_key=True)
    status: Mapped[str]
    postponement_date: Mapped[datetime]
    debt_id: Mapped[int | None] = mapped_column(
        ForeignKey("reg_debt.id"), nullable=True
    )


class _RegDebtORM(Base):
    __tablename__ = "reg_debt"
    id: Mapped[int] = mapped_column(primary_key=True)
    status: Mapped[str]

    loans: Mapped[list[_RegLoanORM]] = relationship()


class TestIndependentRegistries:
    def test_base_mappers_own_separate_registries(self) -> None:
        registry_a = MapperRegistry()
        registry_b = MapperRegistry()

        class BaseA(StateMapper[_R, _T], registry=registry_a): ...
        class BaseB(StateMapper[_R, _T], registry=registry_b): ...

        class LoanA(BaseA[ActiveLoan, _RegLoanORM]): ...
        class LoanB(BaseB[ActiveLoan, _RegLoanORM]): ...

        # Each base mapper registered its concrete mapper into its own registry.
        assert registry_a.get(ActiveLoan, _RegLoanORM) is LoanA
        assert registry_b.get(ActiveLoan, _RegLoanORM) is LoanB

        # The registries are unrelated: neither leaks into the other.
        assert registry_a.get(ActiveLoan, _RegLoanORM) is not LoanB
        assert registry_b.get(ActiveLoan, _RegLoanORM) is not LoanA

        # ...and nothing leaked into the default registry.
        assert StateMapper.__registry__.get(ActiveLoan, _RegLoanORM) is None

    def test_base_mappers_share_registry_via_attribute(self) -> None:
        registry_a = MapperRegistry()
        registry_b = MapperRegistry()

        class BaseA(StateMapper[_R, _T], registry=registry_a): ...
        class BaseB(StateMapper[_R, _T], registry=registry_b): ...

        class LoanA(BaseA[ActiveLoan, _RegLoanORM]): ...
        class LoanB(BaseB[ActiveLoan, _RegLoanORM]): ...

        # Concrete mappers expose the registry they belong to.
        assert LoanA.__registry__ is registry_a
        assert LoanB.__registry__ is registry_b

    def test_nested_resolution_is_scoped_to_own_registry(self) -> None:
        """A debt mapper resolves sub-mappers only within its own registry."""
        registry_a = MapperRegistry()
        registry_b = MapperRegistry()

        class BaseA(StateMapper[_R, _T], registry=registry_a): ...
        class BaseB(StateMapper[_R, _T], registry=registry_b): ...

        # The loan mapper lives in registry B, the debt mapper in registry A.
        class _LoanB(BaseB[ActiveLoan, _RegLoanORM]): ...
        class _DebtA(BaseA[ActiveDebt, _RegDebtORM]): ...

        debt = ActiveDebt(
            loans=(ActiveLoan(id=1, postponement_date=datetime(2026, 1, 1)),)
        )

        # _DebtA cannot see the loan mapper registered in registry B.
        with pytest.raises(MapperRegistryError, match="ActiveLoan"):
            _DebtA.to_orm(debt)

    def test_nested_round_trip_within_a_single_registry(self) -> None:
        registry = MapperRegistry()

        class MyBase(StateMapper[_R, _T], registry=registry): ...

        class _LoanActive(MyBase[ActiveLoan, _RegLoanORM]): ...
        class _LoanClosed(MyBase[ClosedLoan, _RegLoanORM]): ...
        class _Debt(MyBase[ActiveDebt, _RegDebtORM]): ...

        debt = ActiveDebt(
            loans=(
                ActiveLoan(id=1, postponement_date=datetime(2026, 4, 1)),
                ClosedLoan(id=2),
            )
        )

        result = _Debt.to_state(_Debt.to_orm(debt))

        assert result == debt


class TestClearRegistry:
    def test_clear_is_scoped_to_the_owning_registry(self) -> None:
        registry_a = MapperRegistry()
        registry_b = MapperRegistry()

        class BaseA(StateMapper[_R, _T], registry=registry_a): ...
        class BaseB(StateMapper[_R, _T], registry=registry_b): ...

        class LoanA(BaseA[ActiveLoan, _RegLoanORM]): ...
        class LoanB(BaseB[ActiveLoan, _RegLoanORM]): ...

        BaseA.clear_registry()

        assert registry_a.get(ActiveLoan, _RegLoanORM) is None
        # Clearing one base mapper's registry leaves the others untouched.
        assert registry_b.get(ActiveLoan, _RegLoanORM) is LoanB
