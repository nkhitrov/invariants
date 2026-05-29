from __future__ import annotations

from collections.abc import Callable
from typing import Any

from sqlalchemy.orm import InstrumentedAttribute

from invariants.mappers._refs import FieldRef


def field_to_orm(field_ref: Any) -> Callable[[Any], Any]:
    """Mark a method as the custom transform from a State field value to an ORM column value.

    The argument must be a class-level State field reference like ActiveDebt.loans.
    The decorated function is auto-wrapped in @staticmethod for ergonomics; pass
    @classmethod or @staticmethod explicitly if you need them.

    Usage:
        @field_to_orm(ActiveDebt.loans)
        def loans_to_orm(value: tuple[ActiveLoan | ClosedLoan, ...]) -> list[dict]:
            ...
    """

    if not isinstance(field_ref, FieldRef):
        raise TypeError(
            f"field_to_orm() requires a State field reference (e.g. ActiveDebt.loans), got {type(field_ref).__name__}"
        )

    def wrap(fn: Any) -> Any:
        target = fn.__func__ if isinstance(fn, (classmethod, staticmethod)) else fn
        setattr(target, "_mapper_field_to_orm", field_ref)
        if isinstance(fn, (classmethod, staticmethod)):
            return fn
        return staticmethod(target)

    return wrap


def field_to_state(orm_attr: Any) -> Callable[[Any], Any]:
    """Mark a method as the custom transform from an ORM column value to a State field value.

    The argument must be a SQLAlchemy column reference like DebtORM.loans.

    Usage:
        @field_to_state(DebtORM.loans)
        def loans_to_state(value: list[dict]) -> tuple[ActiveLoan | ClosedLoan, ...]:
            ...
    """

    if not isinstance(orm_attr, InstrumentedAttribute):
        raise TypeError(
            f"field_to_state() requires an ORM column reference (e.g. DebtORM.loans), got {type(orm_attr).__name__}"
        )

    def wrap(fn: Any) -> Any:
        target = fn.__func__ if isinstance(fn, (classmethod, staticmethod)) else fn
        setattr(target, "_mapper_field_to_state", orm_attr)
        if isinstance(fn, (classmethod, staticmethod)):
            return fn
        return staticmethod(target)

    return wrap

