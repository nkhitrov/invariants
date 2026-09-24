from __future__ import annotations

from datetime import datetime
from typing import Any

import pytest
from sqlalchemy import JSON, Column, Integer
from sqlalchemy.orm import Mapped, mapped_column

from invariants.mappers import (
    Dumper,
    Loader,
    MapperConfigurationError,
    dump,
    load,
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
    def _build_mappers(
        self,
    ) -> tuple[
        type[Dumper[ActiveDebt, _JsonDebtORM]],
        type[Loader[ActiveDebt, _JsonDebtORM]],
    ]:
        class DebtDumper(Dumper[ActiveDebt, _JsonDebtORM]):
            @dump
            def loans(value: tuple[ActiveLoan | ClosedLoan, ...]) -> list[dict[str, Any]]:
                return [loan.model_dump() for loan in value]

        class DebtLoader(Loader[ActiveDebt, _JsonDebtORM]):
            @load
            def loans(
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

        return DebtDumper, DebtLoader

    def test_dump_writes_serialized_list(self) -> None:
        dumper, _ = self._build_mappers()

        debt = ActiveDebt(
            loans=(
                ActiveLoan(id=1, postponement_date=datetime(2026, 1, 1)),
                ClosedLoan(id=2),
            )
        )

        orm = dumper.dump(debt)

        assert isinstance(orm, _JsonDebtORM)
        assert orm.status == "active"
        assert isinstance(orm.loans, list)
        assert len(orm.loans) == 2
        assert orm.loans[0]["status"] == "active"
        assert orm.loans[0]["id"] == 1
        assert orm.loans[1]["status"] == "closed"
        assert orm.loans[1]["id"] == 2

    def test_load_discriminates_variants(self) -> None:
        _, loader = self._build_mappers()

        orm = _JsonDebtORM(
            id=10,
            status="active",
            loans=[
                {"id": 1, "status": "active", "postponement_date": datetime(2026, 1, 1)},
                {"id": 2, "status": "closed", "postponement_date": None},
            ],
        )

        state = loader.load(orm)

        assert isinstance(state, ActiveDebt)
        assert state.status == "active"
        assert len(state.loans) == 2
        assert isinstance(state.loans[0], ActiveLoan)
        assert isinstance(state.loans[1], ClosedLoan)

    def test_round_trip(self) -> None:
        dumper, loader = self._build_mappers()
        debt = ActiveDebt(
            loans=(
                ActiveLoan(id=7, postponement_date=datetime(2026, 2, 2)),
                ClosedLoan(id=8),
            )
        )

        result = loader.load(dumper.dump(debt))

        assert result == debt


class TestClassmethodWrapping:
    def test_classmethod_handler_supported(self) -> None:
        class DebtDumper(Dumper[ClosedDebt, _JsonDebtORM]):
            @dump
            @classmethod
            def loans(cls, value: tuple[ClosedLoan, ...]) -> list[dict[str, Any]]:
                return [v.model_dump(mode="json") for v in value]

        class DebtLoader(Loader[ClosedDebt, _JsonDebtORM]):
            @load
            @staticmethod
            def loans(value: list[dict[str, Any]] | None) -> tuple[ClosedLoan, ...]:
                return tuple(ClosedLoan.model_validate(v) for v in (value or []))

        debt = ClosedDebt(loans=(ClosedLoan(id=1), ClosedLoan(id=2)))
        orm = DebtDumper.dump(debt)
        assert len(orm.loans) == 2

        round_trip = DebtLoader.load(orm)
        assert round_trip == debt


class TestValidation:
    def test_dump_for_unknown_orm_attribute_raises(self) -> None:
        class _NoPostpORM(Base):
            __tablename__ = "decorator_no_postp_orm"
            id = Column(Integer, primary_key=True)
            status: Mapped[str]

        with pytest.raises(MapperConfigurationError, match="no attribute 'postponement_date'"):
            class _Bad(Dumper[ActiveLoan, _NoPostpORM]):
                @dump
                def postponement_date(value: Any) -> Any:
                    return value

    def test_dump_for_unknown_state_field_raises(self) -> None:
        with pytest.raises(MapperConfigurationError, match="no field 'loans'"):
            class _Bad(Dumper[ActiveLoan, _JsonDebtORM]):
                @dump
                def loans(value: Any) -> Any:
                    return value

    def test_load_for_unknown_state_field_raises(self) -> None:
        class _ExtraORM(Base):
            __tablename__ = "decorator_extra_orm"
            id = Column(Integer, primary_key=True)
            status: Mapped[str]
            postponement_date: Mapped[datetime]
            unknown_col: Mapped[str] = mapped_column(default="x")

        with pytest.raises(MapperConfigurationError, match="no field 'unknown_col'"):
            class _Bad(Loader[ActiveLoan, _ExtraORM]):
                @load
                def unknown_col(value: Any) -> Any:
                    return value

    def test_load_for_unknown_orm_attribute_raises(self) -> None:
        class _ToStateNoPostpORM(Base):
            __tablename__ = "decorator_to_state_no_postp_orm"
            id = Column(Integer, primary_key=True)
            status: Mapped[str]

        with pytest.raises(MapperConfigurationError, match="no attribute 'postponement_date'"):
            class _Bad(Loader[ActiveLoan, _ToStateNoPostpORM]):
                @load
                def postponement_date(value: Any) -> Any:
                    return value

    def test_wrong_direction_decorator_raises(self) -> None:
        with pytest.raises(MapperConfigurationError, match="wrong direction"):
            class _Bad(Dumper[ActiveDebt, _JsonDebtORM]):
                @load
                def loans(value: Any) -> Any:
                    return value


class TestInheritance:
    def test_child_overrides_parent_handler(self) -> None:
        class _BaseDumper(Dumper[ActiveDebt, _JsonDebtORM]):
            @dump
            def loans(value: tuple[ActiveLoan | ClosedLoan, ...]) -> list[dict[str, Any]]:
                return [{"id": v.id, "marker": "parent"} for v in value]

        class _ChildDumper(_BaseDumper):
            @dump
            def loans(value: tuple[ActiveLoan | ClosedLoan, ...]) -> list[dict[str, Any]]:
                return [{"id": v.id, "marker": "child"} for v in value]

        debt = ActiveDebt(loans=(ActiveLoan(id=1, postponement_date=datetime(2026, 1, 1)),))

        parent_orm = _BaseDumper.dump(debt)
        child_orm = _ChildDumper.dump(debt)

        assert parent_orm.loans[0]["marker"] == "parent"
        assert child_orm.loans[0]["marker"] == "child"
