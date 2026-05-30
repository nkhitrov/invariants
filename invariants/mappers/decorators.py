from __future__ import annotations

from typing import Any


def dump(fn: Any) -> Any:
    """Mark a method as the custom transform for a single State field on the way to the ORM.

    Use inside a :class:`Dumper` subclass. The method name must match the State field it
    handles exactly (e.g. ``def loans``). The owning State and ORM models come from the
    enclosing ``Dumper[State, ORM]`` generic arguments, and the field name is validated against
    both at class creation. The decorated function is auto-wrapped in ``@staticmethod`` for
    ergonomics; pass ``@classmethod`` or ``@staticmethod`` explicitly if you need them.

    Usage:
        class DebtDumper(Dumper[ActiveDebt, DebtORM]):
            @dump
            def loans(value: tuple[ActiveLoan | ClosedLoan, ...]) -> list[dict]:
                ...
    """

    return _mark(fn, "_mapper_dump")


def load(fn: Any) -> Any:
    """Mark a method as the custom transform for a single State field on the way from the ORM.

    Use inside a :class:`Loader` subclass. The method name must match the State field it
    handles exactly (e.g. ``def loans``). The owning State and ORM models come from the
    enclosing ``Loader[State, ORM]`` generic arguments, and the field name is validated against
    both at class creation. The decorated function is auto-wrapped in ``@staticmethod`` for
    ergonomics; pass ``@classmethod`` or ``@staticmethod`` explicitly if you need them.

    Usage:
        class DebtLoader(Loader[ActiveDebt, DebtORM]):
            @load
            def loans(value: list[dict] | None) -> tuple[ActiveLoan | ClosedLoan, ...]:
                ...
    """

    return _mark(fn, "_mapper_load")


def _mark(fn: Any, attr: str) -> Any:
    target = fn.__func__ if isinstance(fn, (classmethod, staticmethod)) else fn
    setattr(target, attr, True)
    if isinstance(fn, (classmethod, staticmethod)):
        return fn
    return staticmethod(target)
