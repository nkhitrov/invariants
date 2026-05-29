from __future__ import annotations

from datetime import datetime
from typing import Any

import pytest
from sqlalchemy import JSON, Column, Integer
from sqlalchemy.orm import Mapped, mapped_column

from invariants.mappers import (
    MapperConfigurationError,
    StateMapper,
    field_to_orm,
    field_to_state,
)
from tests.support.orm import Base
from tests.support.states import (
    ActiveDebt,
    ActiveLoan,
    ClosedDebt,
    ClosedLoan,
)


class _JsonDebtORM(Base):
    __tablename__ = "decorator_json_debt"
    id: Mapped[int] = mapped_column(primary_key=True)
    status: Mapped[str]
    loans: Mapped[list[dict[str, Any]]] = mapped_column(JSON)


class TestJsonCollectionDecorators:
    def _build_mapper(self) -> type[StateMapper[ActiveDebt, _JsonDebtORM]]:
        class DebtMapper(StateMapper[ActiveDebt, _JsonDebtORM]):
            @field_to_orm(ActiveDebt.loans)
            def loans_to_orm(value: tuple[ActiveLoan | ClosedLoan, ...]) -> list[dict[str, Any]]:
                result: list[dict[str, Any]] = []
                for loan in value:
                    result.append(loan.model_dump())
                return result

            @field_to_state(_JsonDebtORM.loans)
            def loans_to_state(
                value: list[dict[str, Any]] | None,
            ) -> tuple[ActiveLoan | ClosedLoan, ...]:
                raw = value or []
                out: list[ActiveLoan | ClosedLoan] = []
                for item in raw:
                    if item["status"] == "active":
                        out.append(ActiveLoan.model_validate(item))
                    else:
                        out.append(ClosedLoan.model_validate(item))
                return tuple(out)

        return DebtMapper

    def test_to_orm_writes_serialized_list(self) -> None:
        mapper = self._build_mapper()

        debt = ActiveDebt(
            loans=(
                ActiveLoan(id=1, postponement_date=datetime(2026, 1, 1)),
                ClosedLoan(id=2),
            )
        )

        orm = mapper.to_orm(debt)

        assert isinstance(orm, _JsonDebtORM)
        assert orm.status == "active"
        assert isinstance(orm.loans, list)
        assert len(orm.loans) == 2
        assert orm.loans[0]["status"] == "active"
        assert orm.loans[0]["id"] == 1
        assert orm.loans[1]["status"] == "closed"
        assert orm.loans[1]["id"] == 2

    def test_to_state_discriminates_variants(self) -> None:
        mapper = self._build_mapper()

        orm = _JsonDebtORM(
            id=10,
            status="active",
            loans=[
                {"id": 1, "status": "active", "postponement_date": datetime(2026, 1, 1)},
                {"id": 2, "status": "closed", "postponement_date": None},
            ],
        )

        state = mapper.to_state(orm)

        assert isinstance(state, ActiveDebt)
        assert state.status == "active"
        assert len(state.loans) == 2
        assert isinstance(state.loans[0], ActiveLoan)
        assert isinstance(state.loans[1], ClosedLoan)

    def test_round_trip(self) -> None:
        mapper = self._build_mapper()
        debt = ActiveDebt(
            loans=(
                ActiveLoan(id=7, postponement_date=datetime(2026, 2, 2)),
                ClosedLoan(id=8),
            )
        )

        result = mapper.to_state(mapper.to_orm(debt))

        assert result == debt


class TestClassmethodWrapping:
    def test_classmethod_handler_supported(self) -> None:
        class DebtMapper(StateMapper[ClosedDebt, _JsonDebtORM]):
            @field_to_orm(ClosedDebt.loans)
            @classmethod
            def loans_to_orm(cls, value: tuple[ClosedLoan, ...]) -> list[dict[str, Any]]:
                return [v.model_dump(mode="json") for v in value]

            @field_to_state(_JsonDebtORM.loans)
            @staticmethod
            def loans_to_state(value: list[dict[str, Any]] | None) -> tuple[ClosedLoan, ...]:
                return tuple(ClosedLoan.model_validate(v) for v in (value or []))

        debt = ClosedDebt(loans=(ClosedLoan(id=1), ClosedLoan(id=2)))
        orm = DebtMapper.to_orm(debt)
        assert len(orm.loans) == 2

        round_trip = DebtMapper.to_state(orm)
        assert round_trip == debt


class TestValidation:
    def test_field_to_orm_for_unknown_orm_attribute_raises(self) -> None:
        class _NoPostpORM(Base):
            __tablename__ = "decorator_no_postp_orm"
            id = Column(Integer, primary_key=True)
            status: Mapped[str]

        with pytest.raises(MapperConfigurationError, match="no attribute 'postponement_date'"):
            class _Bad(StateMapper[ActiveLoan, _NoPostpORM]):
                @field_to_orm(ActiveLoan.postponement_date)
                def whatever(value: Any) -> Any:
                    return value

    def test_field_to_state_for_unknown_state_field_raises(self) -> None:
        class _ExtraORM(Base):
            __tablename__ = "decorator_extra_orm"
            id = Column(Integer, primary_key=True)
            status: Mapped[str]
            postponement_date: Mapped[datetime]
            unknown_col: Mapped[str] = mapped_column(default="x")

        with pytest.raises(MapperConfigurationError, match="no field 'unknown_col'"):
            class _Bad(StateMapper[ActiveLoan, _ExtraORM]):
                @field_to_state(_ExtraORM.unknown_col)
                def whatever(value: Any) -> Any:
                    return value

    def test_field_ref_from_unrelated_state_raises(self) -> None:
        with pytest.raises(MapperConfigurationError, match="does not belong"):
            class _Bad(StateMapper[ActiveLoan, _JsonDebtORM]):
                @field_to_orm(ActiveDebt.loans)
                def whatever(value: Any) -> Any:
                    return value

    def test_orm_attr_from_unrelated_orm_raises(self) -> None:
        class _OtherORM(Base):
            __tablename__ = "decorator_other_orm"
            id = Column(Integer, primary_key=True)
            status: Mapped[str]
            postponement_date: Mapped[datetime]

        with pytest.raises(MapperConfigurationError, match="does not belong"):
            class _Bad(StateMapper[ActiveLoan, _JsonDebtORM]):
                @field_to_state(_OtherORM.status)
                def whatever(value: Any) -> Any:
                    return value

    def test_decorator_rejects_non_field_ref_arg(self) -> None:
        with pytest.raises(TypeError, match="State field reference"):
            field_to_orm("loans")

    def test_decorator_rejects_non_instrumented_arg(self) -> None:
        with pytest.raises(TypeError, match="ORM column reference"):
            field_to_state("loans")


class TestInheritance:
    def test_child_overrides_parent_handler(self) -> None:
        class _BaseMapper(StateMapper[ActiveDebt, _JsonDebtORM]):
            @field_to_orm(ActiveDebt.loans)
            def loans_to_orm(value: tuple[ActiveLoan | ClosedLoan, ...]) -> list[dict[str, Any]]:
                return [{"id": v.id, "marker": "parent"} for v in value]

            @field_to_state(_JsonDebtORM.loans)
            def loans_to_state(value: Any) -> tuple[ActiveLoan | ClosedLoan, ...]:
                return ()

        class _ChildMapper(_BaseMapper):
            @field_to_orm(ActiveDebt.loans)
            def loans_to_orm(value: tuple[ActiveLoan | ClosedLoan, ...]) -> list[dict[str, Any]]:
                return [{"id": v.id, "marker": "child"} for v in value]

        debt = ActiveDebt(loans=(ActiveLoan(id=1, postponement_date=datetime(2026, 1, 1)),))

        parent_orm = _BaseMapper.to_orm(debt)
        child_orm = _ChildMapper.to_orm(debt)

        assert parent_orm.loans[0]["marker"] == "parent"
        assert child_orm.loans[0]["marker"] == "child"
