from __future__ import annotations

from typing import TypeVar, Generic, ClassVar, Any, cast

from collections.abc import Iterable, Sequence
from typing import (
    TYPE_CHECKING,
)

from typing_extensions import get_args, get_origin, get_original_bases

from polyfactory.exceptions import ConfigurationException, ParameterException
from polyfactory.utils.predicates import (
    is_type_var,
)


from pydantic import BaseModel
from polyfactory import SyncPersistenceProtocol, AsyncPersistenceProtocol
from polyfactory.factories.base import BaseFactory
from polyfactory.factories.sqlalchemy_factory import _SessionMaker, SQLASyncPersistence, SQLAASyncPersistence
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session

from invariants.factories.state import StateFactory

if TYPE_CHECKING:
    from polyfactory.persistence import AsyncPersistenceProtocol, SyncPersistenceProtocol

R = TypeVar("R", bound=BaseModel)
T = TypeVar("T")
U = TypeVar("U")

class SQLAlchemyStateFactory(Generic[R, T], StateFactory[R]):
    __is_base_factory__ = True
    __set_as_default_factory_for_type__ = True

    __sql_model__: ClassVar[type[Any]]
    __session__: ClassVar[Session | _SessionMaker[Session] | None] = None
    __async_session__: ClassVar[AsyncSession | _SessionMaker[AsyncSession] | None] = (
        None
    )

    @classmethod
    def build(cls, *_: Any, **kwargs: Any) -> T:  # type: ignore[override]
        processed = cls.process_kwargs(**kwargs)
        for key, value in processed.items():
            if isinstance(value, tuple):
                processed[key] = list(value)
        return cast("T", cls.__sql_model__(**processed))

    @classmethod
    def create_sync(cls, *args: Any, **kwargs: Any) -> T:  # type: ignore[override]
        return super().create_sync(*args, **kwargs)  # type: ignore[return-value]

    @classmethod
    def batch(cls, size: int, **kwargs: Any) -> list[T]:  # type: ignore[override]
        return super().batch(size, **kwargs)  # type: ignore[return-value]

    @classmethod
    def create_batch_sync(cls, size: int, **kwargs: Any) -> list[T]:  # type: ignore[override]
        return super().create_batch_sync(size, **kwargs)  # type: ignore[return-value]

    @classmethod
    async def create_async(cls, *args: Any, **kwargs: Any) -> T:  # type: ignore[override]
        return await super().create_async(*args, **kwargs)  # type: ignore[return-value]

    @classmethod
    async def create_batch_async(cls, size: int, **kwargs: Any) -> list[T]:  # type: ignore[override]
        return await super().create_batch_async(size, **kwargs)  # type: ignore[return-value]

    @classmethod
    def _init_model(cls) -> None:
        super()._init_model()

        sql_model: type[T] | None = getattr(cls, "__sql_model__", None) or cls._infer_sql_model_type()
        if not sql_model:
            msg = f"required configuration attribute '__sql_model__' is not set on {cls.__name__}"
            raise ConfigurationException(
                msg,
            )

        if sql_model.__dict__.get("__abstract__", False):
            msg = f"'{sql_model.__name__}' is an abstract model and cannot be used as '__sql_model__' on {cls.__name__}"
            raise ConfigurationException(msg)

        cls.__sql_model__ = sql_model

    @classmethod
    def _infer_model_type(cls) -> type[R] | None:
        factory_bases: Iterable[type[SQLAlchemyStateFactory[R, Any]]] = (
            b
            for b in get_original_bases(cls)
            if get_origin(b) and issubclass(get_origin(b), SQLAlchemyStateFactory)
        )
        generic_args: Sequence[type[T]] = [
            arg
            for factory_base in factory_bases
            for arg in get_args(factory_base)
            if not is_type_var(arg)
        ]
        if not generic_args:
            return None

        return generic_args[0]  # type: ignore[return-value]

    @classmethod
    def _infer_sql_model_type(cls) -> type[T] | None:
        factory_bases: Iterable[type[SQLAlchemyStateFactory[Any, T]]] = (
            b
            for b in get_original_bases(cls)
            if get_origin(b) and issubclass(get_origin(b), SQLAlchemyStateFactory)
        )
        generic_args: Sequence[type[T]] = [
            arg
            for factory_base in factory_bases
            for arg in get_args(factory_base)
            if not is_type_var(arg)
        ]
        if not generic_args:
            return None

        return generic_args[1]

    @classmethod
    def _get_or_create_factory(cls, model: type[U]) -> type["SQLAlchemyStateFactory[Any, U]"]:
        """Get a factory from registered factories or generate a factory dynamically.

        :param model: A model type.
        :returns: A Factory sub-class.

        """
        if factory := BaseFactory._factory_type_mapping.get(model):
            if getattr(factory, "__sql_model__", None) is not None:
                return factory  # type: ignore[return-value]

        msg = f"no factory for model type {model.__name__} with declared `__sql_model__`"  # pragma: no cover
        raise ParameterException(msg)  # pragma: no cover



    @classmethod
    def _get_sync_persistence(cls) -> SyncPersistenceProtocol[T]:  # type: ignore[override]
        if cls.__session__ is not None:
            return (
                SQLASyncPersistence(cls.__session__())
                if callable(cls.__session__)
                else SQLASyncPersistence(cls.__session__)
            )
        return super()._get_sync_persistence()  # type: ignore[return-value]

    @classmethod
    def _get_async_persistence(cls) -> AsyncPersistenceProtocol[T]:  # type: ignore[override]
        if cls.__async_session__ is not None:
            return (
                SQLAASyncPersistence(cls.__async_session__())
                if callable(cls.__async_session__)
                else SQLAASyncPersistence(cls.__async_session__)
            )
        return super()._get_async_persistence()  # type: ignore[return-value]
