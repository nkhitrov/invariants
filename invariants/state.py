from __future__ import annotations

from typing import TYPE_CHECKING, Any, Generic, TypeVar

from pydantic import BaseModel, ConfigDict, model_validator
from pydantic._internal._model_construction import ModelMetaclass

if TYPE_CHECKING:
    Statefull = Any
else:
    from pydantic import GetCoreSchemaHandler
    from pydantic_core import CoreSchema, core_schema

    class Statefull:
        """Marker type for fields that must be overridden in child states."""

        @classmethod
        def __get_pydantic_core_schema__(
            cls, source_type: type, handler: GetCoreSchemaHandler
        ) -> CoreSchema:
            return core_schema.any_schema()


def is_root_state(target_cls: type) -> bool:
    return target_cls.__bases__ == (BaseModel,)


def is_root_child(target_cls: type) -> bool:
    for base in target_cls.__bases__:
        if is_root_state(base):
            return True
    return False


def is_base_state(target_cls: type) -> bool:
    for base in target_cls.__bases__:
        if is_root_child(base):
            return True
    return False


class StateMeta(ModelMetaclass):
    def __init__(cls, name: str, bases: tuple[type, ...], namespace: dict[str, Any]) -> None:
        super().__init__(name, bases, namespace)

        if is_base_state(cls):
            cls._validate_only_parent_fields_allowed(bases)
            for base in bases:
                if is_root_child(base):
                    cls._validate_typing_any_override(base)

    def _validate_only_parent_fields_allowed(cls, bases: tuple[type, ...]) -> None:
        parent_fields: set[str] = set()
        for base in bases:
            model_fields = getattr(base, "model_fields", {})
            parent_fields.update(set(model_fields.keys()))

        model_fields_set = set(getattr(cls, "model_fields", {}).keys())
        diff = model_fields_set.difference(parent_fields)
        if diff:
            sorted_diff = sorted(list(diff))
            raise TypeError(
                f"Unknown fields `{'`, `'.join(sorted_diff)}` in state {cls.__name__}. Allowed fields from base state only"
            )

    def _validate_typing_any_override(cls, base: type) -> None:
        invalid_fields = []
        model_fields = getattr(base, "model_fields", {})
        for field_name, field_info in model_fields.items():
            if (
                field_info.annotation is Statefull
                and field_name in cls.model_fields  # type: ignore[attr-defined]
                and cls.model_fields[field_name].annotation is Statefull  # type: ignore[attr-defined]
            ):
                invalid_fields.append(field_name)

        if invalid_fields:
            raise TypeError(
                f"Fields `{'`, `'.join([name for name in invalid_fields])}` with type `Statefull`"
                f" must be overridden with narrowing types for state `{cls.__name__}`"
            )


class State(BaseModel, metaclass=StateMeta):
    model_config = ConfigDict(frozen=True, strict=True)

    @classmethod
    def has_statefull_fields(cls) -> bool:
        for field_info in cls.model_fields.values():
            if field_info.annotation is Statefull:
                return True
        return False

    @model_validator(mode="before")
    def validate_before_init(cls, values: Any) -> Any:
        if cls.has_statefull_fields():
            raise TypeError(
                "State with Statefull fields cannot be allocated. "
                "Override all Statefull fields in a child state."
            )

        return values


T = TypeVar("T")

class StateMachine(Generic[T]):
    """Abstract class for state controllers."""