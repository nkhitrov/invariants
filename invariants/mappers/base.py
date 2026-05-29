from __future__ import annotations

from collections.abc import Callable, Iterable, Sequence
from typing import Any, ClassVar, Generic, TypeVar, cast

from polyfactory.exceptions import ConfigurationException
from polyfactory.utils.predicates import is_type_var
from pydantic import ValidationError
from sqlalchemy.orm import InstrumentedAttribute
from typing_extensions import get_args, get_origin, get_original_bases

from invariants.mappers._introspect import (
    get_orm_columns,
    get_orm_relationships,
    get_relationship_element_type,
    unwrap_collection_state_types,
)
from invariants.mappers._refs import FieldRef
from invariants.state import State

R = TypeVar("R", bound=State)
T = TypeVar("T")


class MapperConfigurationError(ConfigurationException):
    """Raised when a StateMapper subclass is misconfigured."""


class MapperRegistryError(LookupError):
    """Raised when a required sub-mapper or field mapping cannot be resolved."""


_MAPPER_REGISTRY: dict[tuple[type[Any], type[Any]], type["StateMapper[Any, Any]"]] = {}


def reset_mapper_registry() -> None:
    _MAPPER_REGISTRY.clear()


class StateMapper(Generic[R, T]):
    __is_base_mapper__: ClassVar[bool] = True
    __state_model__: ClassVar[type[Any]]
    __sql_model__: ClassVar[type[Any]]
    _to_orm_handlers: ClassVar[dict[str, Callable[[Any], Any]]] = {}
    _to_state_handlers: ClassVar[dict[str, Callable[[Any], Any]]] = {}

    def __init_subclass__(cls, **kwargs: Any) -> None:
        super().__init_subclass__(**kwargs)

        state_cls = getattr(cls, "__state_model__", None) or cls._infer_state_type()
        orm_cls = getattr(cls, "__sql_model__", None) or cls._infer_sql_model_type()

        if state_cls is None or orm_cls is None:
            raise MapperConfigurationError(
                f"StateMapper subclass {cls.__name__} requires both state and ORM generic arguments"
            )

        if issubclass(state_cls, State) and state_cls.has_statefull_fields():
            raise TypeError(
                f"Cannot create mapper for {state_cls.__name__}: "
                f"state has Statefull fields that must be overridden"
            )

        if orm_cls.__dict__.get("__abstract__", False):
            raise MapperConfigurationError(
                f"'{orm_cls.__name__}' is an abstract model and cannot be used as '__sql_model__' on {cls.__name__}"
            )

        cls.__state_model__ = state_cls
        cls.__sql_model__ = orm_cls
        cls._to_orm_handlers = dict(cls._to_orm_handlers)
        cls._to_state_handlers = dict(cls._to_state_handlers)
        cls._collect_field_handlers()
        _MAPPER_REGISTRY[(state_cls, orm_cls)] = cls

    @classmethod
    def _collect_field_handlers(cls) -> None:
        orm_cols = get_orm_columns(cls.__sql_model__)
        orm_rels = get_orm_relationships(cls.__sql_model__)
        state_fields = cls.__state_model__.model_fields

        for val in cls.__dict__.values():
            fn = val.__func__ if isinstance(val, (classmethod, staticmethod)) else val
            if not callable(fn):
                continue
            bound = (
                val.__get__(None, cls)
                if isinstance(val, (classmethod, staticmethod))
                else fn
            )
            field_ref = getattr(fn, "_mapper_field_to_orm", None)
            if isinstance(field_ref, FieldRef):
                if not issubclass(cls.__state_model__, field_ref.state_cls):
                    raise MapperConfigurationError(
                        f"@field_to_orm on {cls.__name__}: field reference "
                        f"{field_ref.state_cls.__name__}.{field_ref.name} does not belong to "
                        f"{cls.__state_model__.__name__}"
                    )
                if field_ref.name not in orm_cols and field_ref.name not in orm_rels:
                    raise MapperConfigurationError(
                        f"@field_to_orm on {cls.__name__}: ORM model "
                        f"{cls.__sql_model__.__name__} has no attribute '{field_ref.name}'"
                    )
                cls._to_orm_handlers[field_ref.name] = bound
            orm_attr = getattr(fn, "_mapper_field_to_state", None)
            if isinstance(orm_attr, InstrumentedAttribute):
                attr_owner = cast("type[Any]", orm_attr.class_)
                if attr_owner is not cls.__sql_model__ and not issubclass(
                    cls.__sql_model__, attr_owner
                ):
                    raise MapperConfigurationError(
                        f"@field_to_state on {cls.__name__}: ORM attribute "
                        f"{attr_owner.__name__}.{orm_attr.key} does not belong to "
                        f"{cls.__sql_model__.__name__}"
                    )
                if orm_attr.key not in state_fields:
                    raise MapperConfigurationError(
                        f"@field_to_state on {cls.__name__}: State model "
                        f"{cls.__state_model__.__name__} has no field '{orm_attr.key}'"
                    )
                cls._to_state_handlers[orm_attr.key] = bound

    @classmethod
    def _infer_state_type(cls) -> type[R] | None:
        return cast("type[R] | None", cls._infer_generic_arg(0))

    @classmethod
    def _infer_sql_model_type(cls) -> type[T] | None:
        return cast("type[T] | None", cls._infer_generic_arg(1))

    @classmethod
    def _infer_generic_arg(cls, index: int) -> Any:
        mapper_bases: Iterable[type[Any]] = (
            b
            for b in get_original_bases(cls)
            if get_origin(b) and issubclass(get_origin(b), StateMapper)
        )
        generic_args: Sequence[Any] = [
            arg
            for base in mapper_bases
            for arg in get_args(base)
            if not is_type_var(arg)
        ]
        if len(generic_args) <= index:
            return None
        return generic_args[index]

    @classmethod
    def to_orm(cls, state: R) -> T:
        cols = get_orm_columns(cls.__sql_model__)
        rels = get_orm_relationships(cls.__sql_model__)
        payload: dict[str, Any] = {}

        for fname in type(state).model_fields:
            value = getattr(state, fname)
            handler = cls._to_orm_handlers.get(fname)
            if handler is not None:
                payload[fname] = handler(value)
                continue
            if fname in cols:
                payload[fname] = value
            elif fname in rels:
                elem_orm_cls = get_relationship_element_type(rels[fname])
                mapped: list[Any] = []
                for item in value:
                    key = (type(item), elem_orm_cls)
                    sub = _MAPPER_REGISTRY.get(key)
                    if sub is None:
                        raise MapperRegistryError(
                            f"No mapper registered for ({type(item).__name__}, {elem_orm_cls.__name__})"
                        )
                    mapped.append(sub.to_orm(item))
                payload[fname] = mapped
            else:
                raise MapperRegistryError(
                    f"State field '{fname}' has no matching column or relationship "
                    f"on ORM model {cls.__sql_model__.__name__}"
                )

        return cast("T", cls.__sql_model__(**payload))

    @classmethod
    def to_state(cls, orm: T) -> R:
        cols = get_orm_columns(cls.__sql_model__)
        rels = get_orm_relationships(cls.__sql_model__)
        data: dict[str, Any] = {}

        for fname, finfo in cls.__state_model__.model_fields.items():
            handler = cls._to_state_handlers.get(fname)
            if handler is not None:
                data[fname] = handler(getattr(orm, fname))
                continue
            if fname in cols:
                data[fname] = getattr(orm, fname)
            elif fname in rels:
                elem_orm_cls = get_relationship_element_type(rels[fname])
                variants = unwrap_collection_state_types(finfo.annotation)
                if not variants:
                    raise MapperRegistryError(
                        f"Cannot resolve state variants for collection field '{fname}' "
                        f"on {cls.__state_model__.__name__}"
                    )
                items = [
                    _build_state_variant(orm_item, variants, elem_orm_cls)
                    for orm_item in (getattr(orm, fname) or [])
                ]
                data[fname] = tuple(items)
            else:
                raise MapperRegistryError(
                    f"State field '{fname}' has no matching column or relationship "
                    f"on ORM model {cls.__sql_model__.__name__}"
                )

        return cast("R", cls.__state_model__.model_validate(data))


def _build_state_variant(
    orm_item: Any,
    variants: tuple[type[Any], ...],
    elem_orm_cls: type[Any],
) -> Any:
    last_err: ValidationError | None = None
    for variant in variants:
        sub = _MAPPER_REGISTRY.get((variant, elem_orm_cls))
        if sub is None:
            continue
        try:
            return sub.to_state(orm_item)
        except ValidationError as exc:
            last_err = exc
    raise MapperRegistryError(
        f"No matching state variant found for ORM instance of {type(orm_item).__name__} "
        f"among {[v.__name__ for v in variants]}: {last_err}"
    )
