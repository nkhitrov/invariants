from typing import Any, TypeVar

from pydantic import BaseModel
from polyfactory.factories.pydantic_factory import ModelFactory

from invariants.state import State

T = TypeVar("T", bound=BaseModel)


class StateFactory(ModelFactory[T]):
    __is_base_factory__ = True

    def __init_subclass__(cls, **kwargs: Any) -> None:
        super().__init_subclass__(**kwargs)
        model = getattr(cls, "__model__", None)
        if model and issubclass(model, State) and model.has_statefull_fields():
            raise TypeError(
                f"Cannot create factory for {model.__name__}: "
                f"state has Statefull fields that must be overridden"
            )
