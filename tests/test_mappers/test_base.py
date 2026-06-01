from __future__ import annotations

from datetime import datetime

import pytest
from sqlalchemy import Column, ForeignKey, Integer
from sqlalchemy.orm import Mapped, mapped_column, relationship

from invariants.mappers import (
    Dumper,
    Loader,
    MapperConfigurationError,
    MapperRegistryError,
    dump,
)
from invariants.state import State
from tests.support.orm import Base
from tests.support.states import (
    ActiveDebt,
    ActiveLoan,
    ClosedDebt,
    ClosedLoan,
    LoanState,
    OverdueDebt,
    OverdueLoan,
)


class _FlatLoanORM(Base):
    __tablename__ = "mapper_flat_loan"
    id = Column(Integer, primary_key=True)
    status: Mapped[str]
    postponement_date: Mapped[datetime]


class _NestedLoanORM(Base):
    __tablename__ = "mapper_nested_loan"
    id = Column(Integer, primary_key=True)
    status: Mapped[str]
    postponement_date: Mapped[datetime]
    debt_id: Mapped[int | None] = mapped_column(
        ForeignKey("mapper_nested_debt.id"), nullable=True
    )


class _NestedDebtORM(Base):
    __tablename__ = "mapper_nested_debt"
    id: Mapped[int] = mapped_column(primary_key=True)
    status: Mapped[str]

    loans: Mapped[list[_NestedLoanORM]] = relationship()


class TestFlatToOrm:
    def test_dump_active_loan(self) -> None:
        class M(Dumper[ActiveLoan, _FlatLoanORM]): ...

        ts = datetime(2026, 1, 1)
        loan = ActiveLoan(id=42, postponement_date=ts)

        orm = M.dump(loan)

        assert isinstance(orm, _FlatLoanORM)
        assert orm.id == 42
        assert orm.status == "active"
        assert orm.postponement_date == ts


class TestFlatToState:
    def test_load_active_loan(self) -> None:
        class M(Loader[ActiveLoan, _FlatLoanORM]): ...

        ts = datetime(2026, 2, 2)
        orm = _FlatLoanORM(id=7, status="active", postponement_date=ts)

        state = M.load(orm)

        assert isinstance(state, ActiveLoan)
        assert state.id == 7
        assert state.status == "active"
        assert state.postponement_date == ts


class TestRoundTrip:
    def test_loan_round_trip(self) -> None:
        class D(Dumper[ActiveLoan, _FlatLoanORM]): ...
        class L(Loader[ActiveLoan, _FlatLoanORM]): ...

        original = ActiveLoan(id=99, postponement_date=datetime(2026, 3, 3))
        result = L.load(D.dump(original))

        assert result == original


class TestNestedToOrm:
    def test_debt_with_mixed_loans(self) -> None:
        class _LoanActive(Dumper[ActiveLoan, _NestedLoanORM]): ...
        class _LoanClosed(Dumper[ClosedLoan, _NestedLoanORM]): ...
        class _DebtActive(Dumper[ActiveDebt, _NestedDebtORM]): ...

        active = ActiveLoan(id=1, postponement_date=datetime(2026, 4, 1))
        closed = ClosedLoan(id=2)
        debt = ActiveDebt(loans=(active, closed))

        orm = _DebtActive.dump(debt)

        assert isinstance(orm, _NestedDebtORM)
        assert orm.status == "active"
        assert isinstance(orm.loans, list)
        assert len(orm.loans) == 2
        assert all(isinstance(loan, _NestedLoanORM) for loan in orm.loans)
        assert {loan.status for loan in orm.loans} == {"active", "closed"}


class TestNestedToStateWithDiscrimination:
    def test_debt_with_mixed_loans(self) -> None:
        class _LoanActive(Loader[ActiveLoan, _NestedLoanORM]): ...
        class _LoanClosed(Loader[ClosedLoan, _NestedLoanORM]): ...
        class _DebtActive(Loader[ActiveDebt, _NestedDebtORM]): ...

        loan_active = _NestedLoanORM(
            id=1, status="active", postponement_date=datetime(2026, 5, 1)
        )
        loan_closed = _NestedLoanORM(
            id=2, status="closed", postponement_date=None
        )
        debt_orm = _NestedDebtORM(id=10, status="active", loans=[loan_active, loan_closed])

        state = _DebtActive.load(debt_orm)

        assert isinstance(state, ActiveDebt)
        assert state.status == "active"
        assert len(state.loans) == 2
        assert isinstance(state.loans[0], ActiveLoan)
        assert isinstance(state.loans[1], ClosedLoan)
        assert state.loans[0].id == 1
        assert state.loans[1].id == 2


class TestStatefullValidation:
    def test_root_state_with_statefull_raises(self) -> None:
        with pytest.raises(TypeError, match="Statefull"):
            class M(Dumper[LoanState, _FlatLoanORM]): ...


class TestAbstractOrm:
    def test_abstract_orm_raises(self) -> None:
        with pytest.raises(MapperConfigurationError, match="abstract"):
            class M(Dumper[ActiveLoan, Base]): ...


class TestMissingGenericArgs:
    def test_no_generic_args_raises(self) -> None:
        with pytest.raises(MapperConfigurationError):
            class M(Dumper): ...  # type: ignore[type-arg]


class TestMissingFieldOnOrm:
    def test_state_field_absent_from_orm_raises(self) -> None:
        class _NoStatusORM(Base):
            __tablename__ = "mapper_no_status"
            id = Column(Integer, primary_key=True)
            postponement_date: Mapped[datetime]

        class M(Dumper[ActiveLoan, _NoStatusORM]): ...

        loan = ActiveLoan(id=1, postponement_date=datetime(2026, 6, 1))

        with pytest.raises(MapperRegistryError, match="status"):
            M.dump(loan)


class TestMissingSubMapper:
    def test_nested_dump_without_sub_mapper_raises(self) -> None:
        class _DebtActive(Dumper[ActiveDebt, _NestedDebtORM]): ...

        loan = ActiveLoan(id=1, postponement_date=datetime(2026, 7, 1))
        debt = ActiveDebt(loans=(loan,))

        with pytest.raises(MapperRegistryError, match="ActiveLoan"):
            _DebtActive.dump(debt)


class TestRegistryOverwrite:
    def test_nested_resolution_uses_last_definition(self) -> None:
        """When two dumpers are defined for the same (State, ORM) pair, nested resolution uses the latest."""

        class _FirstLoan(Dumper[ActiveLoan, _NestedLoanORM]):
            @dump
            def id(value: int) -> int:
                return value * 10

        class _SecondLoan(Dumper[ActiveLoan, _NestedLoanORM]):
            @dump
            def id(value: int) -> int:
                return value * 100

        class _DebtDumper(Dumper[ActiveDebt, _NestedDebtORM]): ...

        debt = ActiveDebt(loans=(ActiveLoan(id=7, postponement_date=datetime(2026, 1, 1)),))

        orm = _DebtDumper.dump(debt)

        assert orm.loans[0].id == 700


class TestNestedRoundTrip:
    def test_debt_round_trip(self) -> None:
        class _LoanActiveDump(Dumper[ActiveLoan, _NestedLoanORM]): ...
        class _LoanClosedDump(Dumper[ClosedLoan, _NestedLoanORM]): ...
        class _DebtClosedDump(Dumper[ClosedDebt, _NestedDebtORM]): ...

        class _LoanActiveLoad(Loader[ActiveLoan, _NestedLoanORM]): ...
        class _LoanClosedLoad(Loader[ClosedLoan, _NestedLoanORM]): ...
        class _DebtClosedLoad(Loader[ClosedDebt, _NestedDebtORM]): ...

        debt = ClosedDebt(loans=(ClosedLoan(id=1), ClosedLoan(id=2)))

        result = _DebtClosedLoad.load(_DebtClosedDump.dump(debt))

        assert result == debt


class TestToStateMissingField:
    def test_state_field_without_orm_attribute_raises(self) -> None:
        class _ToStateNoStatusORM(Base):
            __tablename__ = "to_state_no_status"
            id = Column(Integer, primary_key=True)
            postponement_date: Mapped[datetime]

        class M(Loader[ActiveLoan, _ToStateNoStatusORM]): ...

        orm = _ToStateNoStatusORM(id=1, postponement_date=datetime(2026, 1, 1))

        with pytest.raises(MapperRegistryError, match="status"):
            M.load(orm)


class TestToStateScalarStateWithRelationship:
    def test_scalar_state_field_against_relationship_raises(self) -> None:
        """State has a scalar nested field but the ORM exposes it as a relationship — load cannot resolve variants."""

        class _ChildORM(Base):
            __tablename__ = "to_state_scalar_child"
            id: Mapped[int] = mapped_column(primary_key=True)
            name: Mapped[str]
            parent_id: Mapped[int | None] = mapped_column(
                ForeignKey("to_state_scalar_parent.id"), nullable=True
            )

        class _ParentORM(Base):
            __tablename__ = "to_state_scalar_parent"
            id: Mapped[int] = mapped_column(primary_key=True)
            child: Mapped[_ChildORM] = relationship(uselist=False)

        class _ChildState(State):
            id: int
            name: str

        class _ParentState(State):
            id: int
            child: _ChildState

        class _ChildLoader(Loader[_ChildState, _ChildORM]): ...
        class _ParentLoader(Loader[_ParentState, _ParentORM]): ...

        orm = _ParentORM(id=1, child=_ChildORM(id=2, name="x"))

        with pytest.raises(MapperRegistryError, match="state variants"):
            _ParentLoader.load(orm)


class TestNestedToStateVariantHandling:
    def test_unregistered_variant_is_skipped(self) -> None:
        """OverdueDebt has variants (OverdueLoan|ActiveLoan|ClosedLoan); ActiveLoan loader is not registered.

        For closed ORM items the resolver must skip the missing ActiveLoan loader and try the next one.
        """

        class _OverdueLoader(Loader[OverdueLoan, _NestedLoanORM]): ...
        class _ClosedLoader(Loader[ClosedLoan, _NestedLoanORM]): ...
        class _DebtLoader(Loader[OverdueDebt, _NestedDebtORM]): ...

        orm = _NestedDebtORM(
            id=1,
            status="overdue",
            loans=[
                _NestedLoanORM(id=1, status="overdue", postponement_date=datetime(2026, 1, 1)),
                _NestedLoanORM(id=2, status="closed", postponement_date=None),
            ],
        )

        state = _DebtLoader.load(orm)

        assert isinstance(state, OverdueDebt)
        assert isinstance(state.loans[0], OverdueLoan)
        assert isinstance(state.loans[1], ClosedLoan)

    def test_no_variant_matches_raises(self) -> None:
        """When no registered variant can validate the ORM item, MapperRegistryError surfaces the validation error."""

        class _ClosedLoader(Loader[ClosedLoan, _NestedLoanORM]): ...
        class _DebtLoader(Loader[OverdueDebt, _NestedDebtORM]): ...

        orm = _NestedDebtORM(
            id=1,
            status="overdue",
            loans=[
                _NestedLoanORM(id=1, status="active", postponement_date=datetime(2026, 1, 1)),
            ],
        )

        with pytest.raises(MapperRegistryError, match="No matching state variant"):
            _DebtLoader.load(orm)
