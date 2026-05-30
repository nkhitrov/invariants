from __future__ import annotations

from collections.abc import Callable, Iterable, Sequence
from typing import Any, ClassVar, Generic, TypeVar, cast

from polyfactory.exceptions import ConfigurationException
from polyfactory.utils.predicates import is_type_var
from pydantic import ValidationError
from typing_extensions import get_args, get_origin, get_original_bases

from invariants.mappers._introspect import (
    get_orm_columns,
    get_orm_relationships,
    get_relationship_element_type,
    unwrap_collection_state_types,
)
from invariants.state import State

R = TypeVar("R", bound=State)
T = TypeVar("T")


class MapperConfigurationError(ConfigurationException):
    """Raised when a Dumper/Loader subclass is misconfigured."""


class MapperRegistryError(LookupError):
    """Raised when a required sub-mapper or field mapping cannot be resolved."""


class MapperRegistry:
    """A self-contained collection of :class:`Dumper` and :class:`Loader` subclasses.

    Mappers are keyed by their ``(state, ORM)`` pair, in two separate tables for the
    two directions. Each base mapper owns one registry, and concrete mappers register
    into the registry of their base. This mirrors SQLAlchemy's ``MetaData``: independent
    registries let unrelated mapper hierarchies coexist without clashing — useful, for
    instance, to isolate mappers between tests.
    """

    def __init__(self) -> None:
        self._dumpers: dict[tuple[type[Any], type[Any]], type["Dumper[Any, Any]"]] = {}
        self._loaders: dict[tuple[type[Any], type[Any]], type["Loader[Any, Any]"]] = {}

    def register_dumper(
        self, state_cls: type[Any], orm_cls: type[Any], mapper: type["Dumper[Any, Any]"]
    ) -> None:
        self._dumpers[(state_cls, orm_cls)] = mapper

    def register_loader(
        self, state_cls: type[Any], orm_cls: type[Any], mapper: type["Loader[Any, Any]"]
    ) -> None:
        self._loaders[(state_cls, orm_cls)] = mapper

    def get_dumper(
        self, state_cls: type[Any], orm_cls: type[Any]
    ) -> type["Dumper[Any, Any]"] | None:
        return self._dumpers.get((state_cls, orm_cls))

    def get_loader(
        self, state_cls: type[Any], orm_cls: type[Any]
    ) -> type["Loader[Any, Any]"] | None:
        return self._loaders.get((state_cls, orm_cls))

    def clear(self) -> None:
        """Remove all registered dumpers and loaders."""
        self._dumpers.clear()
        self._loaders.clear()


_default_registry = MapperRegistry()


class Mapper(Generic[R, T]):
    """Abstract base for directional state<->ORM mappers.

    Subclass :class:`Dumper` (State -> ORM) or :class:`Loader` (ORM -> State), not this
    class directly. Holds the machinery common to both directions: generic-argument
    inference, validation, the registry, and per-field handler collection.
    """

    __registry__: ClassVar[MapperRegistry] = _default_registry
    __state_model__: ClassVar[type[Any]]
    __sql_model__: ClassVar[type[Any]]
    _handlers: ClassVar[dict[str, Callable[[Any], Any]]] = {}
    _handler_marker: ClassVar[str]
    _wrong_marker: ClassVar[str]

    def __init_subclass__(
        cls,
        registry: MapperRegistry | None = None,
        abstract: bool = False,
        **kwargs: Any,
    ) -> None:
        super().__init_subclass__(**kwargs)

        if abstract:
            # A directional base (Dumper/Loader) or a user-declared abstract base.
            if registry is not None:
                cls.__registry__ = registry
            return

        if registry is not None:
            # A user base mapper that owns its own registry; concrete mappers
            # subclassing it will register into this registry.
            cls.__registry__ = registry
            return

        state_cls = getattr(cls, "__state_model__", None) or cls._infer_state_type()
        orm_cls = getattr(cls, "__sql_model__", None) or cls._infer_sql_model_type()

        if state_cls is None or orm_cls is None:
            raise MapperConfigurationError(
                f"{cls.__name__} requires both state and ORM generic arguments"
            )

        if issubclass(state_cls, State) and state_cls.has_statefull_fields():
            raise TypeError(
                f"Cannot create mapper for {state_cls.__name__}: "
                f"state has Statefull fields that must be overridden"
            )

        if orm_cls.__dict__.get("__abstract__", False):
            raise MapperConfigurationError(
                f"'{orm_cls.__name__}' is an abstract model and cannot be used as "
                f"'__sql_model__' on {cls.__name__}"
            )

        cls.__state_model__ = state_cls
        cls.__sql_model__ = orm_cls
        cls._handlers = dict(cls._handlers)
        cls._collect_field_handlers()
        cls._register()

    @classmethod
    def _register(cls) -> None:
        raise NotImplementedError

    @classmethod
    def clear_registry(cls) -> None:
        """Remove all mappers from this mapper's registry."""
        cls.__registry__.clear()

    @classmethod
    def _collect_field_handlers(cls) -> None:
        orm_cols = get_orm_columns(cls.__sql_model__)
        orm_rels = get_orm_relationships(cls.__sql_model__)
        state_fields = cls.__state_model__.model_fields

        for name, val in cls.__dict__.items():
            fn = val.__func__ if isinstance(val, (classmethod, staticmethod)) else val
            if not callable(fn):
                continue
            if getattr(fn, cls._wrong_marker, False):
                raise MapperConfigurationError(
                    f"{cls.__name__}: method '{name}' uses the wrong direction decorator "
                    f"for a {cls.__bases__[0].__name__}"
                )
            if getattr(fn, cls._handler_marker, False):
                bound = (
                    val.__get__(None, cls)
                    if isinstance(val, (classmethod, staticmethod))
                    else fn
                )
                cls._validate_handler_field(name, state_fields, orm_cols, orm_rels)
                cls._handlers[name] = bound

    @classmethod
    def _validate_handler_field(
        cls,
        field: str,
        state_fields: dict[str, Any],
        orm_cols: dict[str, Any],
        orm_rels: dict[str, Any],
    ) -> None:
        if field not in state_fields:
            raise MapperConfigurationError(
                f"{cls.__name__}: State model "
                f"{cls.__state_model__.__name__} has no field '{field}'"
            )
        if field not in orm_cols and field not in orm_rels:
            raise MapperConfigurationError(
                f"{cls.__name__}: ORM model "
                f"{cls.__sql_model__.__name__} has no attribute '{field}'"
            )

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
            if get_origin(b) and issubclass(get_origin(b), Mapper)
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


class Dumper(Mapper[R, T], abstract=True):
    """Converts a State instance into an ORM instance."""

    _handler_marker = "_mapper_dump"
    _wrong_marker = "_mapper_load"

    @classmethod
    def _register(cls) -> None:
        cls.__registry__.register_dumper(cls.__state_model__, cls.__sql_model__, cls)

    @classmethod
    def dump(cls, state: R) -> T:
        cols = get_orm_columns(cls.__sql_model__)
        rels = get_orm_relationships(cls.__sql_model__)
        payload: dict[str, Any] = {}

        for fname in type(state).model_fields:
            value = getattr(state, fname)
            handler = cls._handlers.get(fname)
            if handler is not None:
                payload[fname] = handler(value)
                continue
            if fname in cols:
                payload[fname] = value
            elif fname in rels:
                elem_orm_cls = get_relationship_element_type(rels[fname])
                mapped: list[Any] = []
                for item in value:
                    sub = cls.__registry__.get_dumper(type(item), elem_orm_cls)
                    if sub is None:
                        raise MapperRegistryError(
                            f"No dumper registered for "
                            f"({type(item).__name__}, {elem_orm_cls.__name__})"
                        )
                    mapped.append(sub.dump(item))
                payload[fname] = mapped
            else:
                raise MapperRegistryError(
                    f"State field '{fname}' has no matching column or relationship "
                    f"on ORM model {cls.__sql_model__.__name__}"
                )

        return cast("T", cls.__sql_model__(**payload))


class Loader(Mapper[R, T], abstract=True):
    """Converts an ORM instance into a State instance."""

    _handler_marker = "_mapper_load"
    _wrong_marker = "_mapper_dump"

    @classmethod
    def _register(cls) -> None:
        cls.__registry__.register_loader(cls.__state_model__, cls.__sql_model__, cls)

    @classmethod
    def load(cls, orm: T) -> R:
        cols = get_orm_columns(cls.__sql_model__)
        rels = get_orm_relationships(cls.__sql_model__)
        data: dict[str, Any] = {}

        for fname, finfo in cls.__state_model__.model_fields.items():
            handler = cls._handlers.get(fname)
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
                    _build_state_variant(
                        orm_item, variants, elem_orm_cls, cls.__registry__
                    )
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
    registry: MapperRegistry,
) -> Any:
    last_err: ValidationError | None = None
    for variant in variants:
        sub = registry.get_loader(variant, elem_orm_cls)
        if sub is None:
            continue
        try:
            return sub.load(orm_item)
        except ValidationError as exc:
            last_err = exc
    raise MapperRegistryError(
        f"No matching state variant found for ORM instance of {type(orm_item).__name__} "
        f"among {[v.__name__ for v in variants]}: {last_err}"
    )
