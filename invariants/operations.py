"""Operations over state hierarchies: edges of the state graph, their events and results.

* :class:`Event` ``[From, To]`` names exactly one edge of the graph; ``From = None`` is the
  null state (creation). An edge has at most one event.
* :class:`Transition` ``[S, E]`` is the result of an operation: the new state plus the events
  of its edge and of nested aggregates.
* :class:`Operation` ``[T]`` implements edges of the hierarchy rooted at ``T``: one ``execute``
  signature (or ``@overload``) per edge, and every edge belongs to one operation.
* :class:`Query` ``[T]`` reads states without moving them.

Operations and queries are frozen, keyword-only, slotted dataclasses whose fields are their
dependencies (other operations and queries only).
"""

from __future__ import annotations

import dataclasses
import functools
import inspect
import types
import typing
from collections.abc import Callable
from typing import Any, ClassVar, Generic, NamedTuple, TypeVar, Union, cast, get_args, get_origin

from pydantic import BaseModel, ConfigDict
from typing_extensions import dataclass_transform

from invariants.hierarchy import find_state_root, get_nested_roots, get_root_state, is_concrete_state
from invariants.state import State, StateMachine

FromT = TypeVar("FromT")
ToT = TypeVar("ToT")
T = TypeVar("T")
S = TypeVar("S", covariant=True)
E = TypeVar("E", bound="Event[Any, Any]", covariant=True)

Edge = tuple[type[State] | None, type[State]]


class TransitionError(TypeError):
    """Raised when ``execute`` returns something its signature does not declare."""


class EdgeRegistry:
    """Owners of the state graph edges: the event and the operation of each ``(From, To)``.

    Events and operations register into the registry of their base class (the default one,
    or one passed as ``registry=`` in the class definition). Like
    :class:`~invariants.mappers.base.MapperRegistry`, independent registries let unrelated
    graphs coexist — for instance, to isolate edges between tests.
    """

    def __init__(self) -> None:
        self._events: dict[Edge, type[Event[Any, Any]]] = {}
        self._operations: dict[Edge, type[Operation[Any]]] = {}

    def register_event(self, edge: Edge, event: type[Event[Any, Any]]) -> None:
        existing = self._events.get(edge)
        if existing is not None:
            raise TypeError(
                f"Edge {_edge_name(edge)} is already taken by event {existing.__name__}; "
                f"cannot register {event.__name__}"
            )
        self._events[edge] = event

    def register_operation(self, edge: Edge, operation: type[Operation[Any]]) -> None:
        existing = self._operations.get(edge)
        if existing is not None:
            raise TypeError(
                f"Edge {_edge_name(edge)} is already implemented by operation "
                f"{existing.__name__}; cannot register {operation.__name__}"
            )
        self._operations[edge] = operation

    def get_event(self, edge: Edge) -> type[Event[Any, Any]] | None:
        return self._events.get(edge)

    def get_operation(self, edge: Edge) -> type[Operation[Any]] | None:
        return self._operations.get(edge)

    def clear(self) -> None:
        """Remove all registered events and operations."""
        self._events.clear()
        self._operations.clear()


_default_registry = EdgeRegistry()


def _edge_name(edge: Edge) -> str:
    source, target = edge
    return f"{'None' if source is None else source.__name__} → {target.__name__}"


class Event(BaseModel, Generic[FromT, ToT]):
    """The event of the edge ``FromT → ToT`` of a state graph (``FromT = None``: creation).

    The payload is exactly the fields declared by the subclass; ``FromT``/``ToT`` are class
    metadata, not fields.
    """

    model_config = ConfigDict(frozen=True, strict=True)

    __registry__: ClassVar[EdgeRegistry] = _default_registry

    def __init_subclass__(cls, registry: EdgeRegistry | None = None, **kwargs: Any) -> None:
        super().__init_subclass__(**kwargs)
        if registry is not None:
            cls.__registry__ = registry

    @classmethod
    def __pydantic_init_subclass__(cls, **kwargs: Any) -> None:
        super().__pydantic_init_subclass__(**kwargs)
        metadata = cls.__pydantic_generic_metadata__
        if metadata["origin"] is not None or metadata["parameters"]:
            # ``Event[A, B]`` itself, or a still generic user base
            return

        if not cls.__name__.endswith("Event"):
            raise TypeError(f"Event class name must end with `Event`: {cls.__name__}")

        source, target = get_event_edge(cls)
        if source is not None and not is_concrete_state(source):
            raise TypeError(
                f"{cls.__name__}: source of an event must be a concrete state or None, got {source!r}"
            )
        if not is_concrete_state(target):
            raise TypeError(f"{cls.__name__}: target of an event must be a concrete state, got {target!r}")
        if source is not None and find_state_root({source, target}) is None:
            raise TypeError(
                f"{cls.__name__}: {source.__name__} and {target.__name__} belong to different state hierarchies"
            )
        if source is target:
            raise TypeError(
                f"{cls.__name__}: loop {_edge_name((source, target))} has no event of its own; "
                f"a loop emits only the events of nested aggregates"
            )
        cls.__registry__.register_event((source, target), cls)


def _event_arguments(cls: type) -> tuple[Any, ...] | None:
    """``Event``'s generic arguments of ``cls``, substituted through generic user bases."""
    for klass in cls.__mro__:
        metadata = getattr(klass, "__pydantic_generic_metadata__", None) or {}
        origin = metadata.get("origin")
        if origin is None or not issubclass(origin, Event):
            continue
        if origin is Event:
            return tuple(metadata["args"])
        inner = _event_arguments(origin)
        if inner is None:  # pragma: no cover
            return None
        substitution = dict(zip(origin.__pydantic_generic_metadata__["parameters"], metadata["args"]))
        return tuple(substitution.get(arg, arg) if isinstance(arg, TypeVar) else arg for arg in inner)
    return None  # pragma: no cover


def get_event_edge(event_cls: type[Event[Any, Any]]) -> Edge:
    """Return the ``(From, To)`` edge an event class is declared for (``From = None``: creation)."""
    arguments = _event_arguments(event_cls)
    if arguments is None or any(isinstance(arg, TypeVar) for arg in arguments):
        raise TypeError(f"{event_cls.__name__} must subclass Event[From, To] with concrete states")
    source, target = arguments
    return (None if source in (None, type(None)) else source), target


class Transition(NamedTuple, Generic[S, E]):
    """The result of an operation: the new state and the events that led to it."""

    state: S
    events: tuple[E, ...]


@dataclasses.dataclass(frozen=True)
class OperationEdge:
    """One edge implemented by an operation's ``execute`` signature.

    ``event`` is the edge event (``None`` for a loop); ``events`` are all events the
    signature declares, the edge event and the events of nested aggregates.
    """

    source: type[State] | None
    target: type[State]
    event: type[Event[Any, Any]] | None
    events: tuple[type[Event[Any, Any]], ...]


def _unpack_union(annotation: Any) -> list[Any]:
    origin = get_origin(annotation)
    if origin is Union or origin is types.UnionType:
        return list(get_args(annotation))
    return [annotation]


def _name(t: Any) -> str:
    return getattr(t, "__name__", repr(t))


def _parse_signature(
    cls: type, fn: Callable[..., Any], root: type[State], nested_roots: set[type[State]]
) -> list[OperationEdge]:
    where = f"{cls.__name__}.execute"
    hints = typing.get_type_hints(fn)
    params = list(inspect.signature(fn).parameters.values())[1:]  # skip self

    positional = [p for p in params if p.kind in (p.POSITIONAL_ONLY, p.POSITIONAL_OR_KEYWORD)]
    if len(positional) > 1 or any(p.kind is p.VAR_POSITIONAL for p in params):
        raise TypeError(f"{where}: only the source state may be positional, other arguments must be keyword-only")

    source: type[State] | None = None
    if positional:
        annotation = hints.get(positional[0].name)
        if not (is_concrete_state(annotation) and find_state_root({cast(type[State], annotation)}) is root):
            raise TypeError(
                f"{where}: the first argument must be a single concrete state of {root.__name__}, "
                f"got {_name(annotation)} (use @overload for several source states)"
            )
        source = annotation

    returns = hints.get("return")
    branches = _unpack_union(returns)
    if not all(get_origin(b) is Transition for b in branches):
        raise TypeError(f"{where}: must return Transition[State, Events] or a union of them, got {returns!r}")

    edges: list[OperationEdge] = []
    for branch in branches:
        target, events_annotation = get_args(branch)
        if not (is_concrete_state(target) and find_state_root({target}) is root):
            raise TypeError(f"{where}: target {_name(target)} is not a concrete state of {root.__name__}")
        edge_name = _edge_name((source, target))

        events = _unpack_union(events_annotation)
        root_events: list[type[Event[Any, Any]]] = []
        for event in events:
            if not (isinstance(event, type) and issubclass(event, Event)):
                raise TypeError(f"{where}: {_name(event)} is not an Event")
            event_root = find_state_root({get_event_edge(event)[1]})
            if event_root is root:
                root_events.append(event)
            elif event_root not in nested_roots:
                raise TypeError(
                    f"{where}: {event.__name__} belongs to a hierarchy not nested in {root.__name__}"
                )

        edge_event: type[Event[Any, Any]] | None = None
        if source is target:
            # Without root events a loop declares only nested events, and at least one of them
            if root_events:
                raise TypeError(
                    f"{where}: loop {edge_name} must not emit events of {root.__name__}, "
                    f"got {', '.join(e.__name__ for e in root_events)}"
                )
        else:
            if not root_events:
                raise TypeError(f"{where}: edge {edge_name} has no event")
            if len(root_events) > 1:
                raise TypeError(
                    f"{where}: edge {edge_name} must emit one event of {root.__name__}, "
                    f"got {', '.join(e.__name__ for e in root_events)}"
                )
            edge_event = root_events[0]
            if get_event_edge(edge_event) != (source, target):
                raise TypeError(
                    f"{where}: {edge_event.__name__} is the event of "
                    f"{_edge_name(get_event_edge(edge_event))}, not of {edge_name}"
                )

        edges.append(OperationEdge(source=source, target=target, event=edge_event, events=tuple(events)))
    return edges


def get_operation_edges(cls: type) -> list[OperationEdge]:
    """Parse the edges implemented by ``cls.execute`` (each ``@overload`` is a signature).

    Raises :class:`TypeError` if a signature breaks the rules of operations.
    """
    root = get_root_state(cls)
    if root is None or State not in root.__bases__:
        raise TypeError(f"{cls.__name__} must be parametrized with a root state: Operation[RootState]")
    execute = cls.__dict__.get("execute")
    if execute is None:
        raise TypeError(f"{cls.__name__} must define execute()")

    nested_roots = get_nested_roots(root)
    edges: list[OperationEdge] = []
    seen: set[Edge] = set()
    for signature in typing.get_overloads(execute) or [execute]:
        for edge in _parse_signature(cls, signature, root, nested_roots):
            if (edge.source, edge.target) in seen:
                raise TypeError(
                    f"{cls.__name__}.execute: edge {_edge_name((edge.source, edge.target))} is declared twice"
                )
            seen.add((edge.source, edge.target))
            edges.append(edge)
    return edges


def _validate_dependencies(cls: type) -> None:
    hints = typing.get_type_hints(cls)
    for field in dataclasses.fields(cast(Any, cls)):
        annotation = hints[field.name]
        if not (isinstance(annotation, type) and issubclass(annotation, (Operation, Query))):
            raise TypeError(
                f"{cls.__name__}.{field.name}: dependencies must be operations or queries, "
                f"got {_name(annotation)}; pass other data as execute() arguments"
            )


def _check_transition(cls: type, edges: list[OperationEdge], state: Any, result: Any) -> None:
    source = None if state is None else type(state)
    if not isinstance(result, Transition):
        raise TransitionError(f"{cls.__name__}.execute must return Transition, got {type(result).__name__}")
    edge = next((e for e in edges if e.source is source and e.target is type(result.state)), None)
    if edge is None:
        raise TransitionError(
            f"{cls.__name__}.execute: edge {_name(source)} → {type(result.state).__name__} is not declared"
        )
    if not isinstance(result.events, tuple):
        raise TransitionError(f"{cls.__name__}.execute: events must be a tuple")
    for event in result.events:
        if not isinstance(event, edge.events):
            raise TransitionError(
                f"{cls.__name__}.execute: {type(event).__name__} is not declared for edge "
                f"{_edge_name((edge.source, edge.target))}"
            )
    if edge.event is not None:
        count = sum(type(event) is edge.event for event in result.events)
        if count != 1:
            raise TransitionError(
                f"{cls.__name__}.execute: edge {_edge_name((edge.source, edge.target))} must emit "
                f"{edge.event.__name__} exactly once, got {count}"
            )
    elif not result.events:
        raise TransitionError(
            f"{cls.__name__}.execute: loop {_edge_name((edge.source, edge.target))} must emit "
            f"at least one event of a nested aggregate"
        )


def _guard_execute(cls: type, edges: list[OperationEdge]) -> None:
    """Wrap ``execute`` with runtime checks of the returned transition (annotations are kept)."""
    impl = cls.__dict__["execute"]
    params = list(inspect.signature(impl).parameters.values())[1:]
    state_param = next(
        (p.name for p in params if p.kind in (p.POSITIONAL_ONLY, p.POSITIONAL_OR_KEYWORD)), None
    )

    @functools.wraps(impl)
    def execute(self: Any, *args: Any, **kwargs: Any) -> Any:
        result = impl(self, *args, **kwargs)
        state = args[0] if args else (kwargs.get(state_param) if state_param else None)
        _check_transition(cls, edges, state, result)
        return result

    setattr(cls, "execute", execute)


def validate_operation(cls: type) -> None:
    """Validate an operation or query class (see the module docstring) and register its edges."""
    _validate_dependencies(cls)
    if not issubclass(cls, Operation):
        return

    if not cls.__name__.endswith("Operation"):
        raise TypeError(f"Operation class name must end with `Operation`: {cls.__name__}")

    edges = get_operation_edges(cls)
    registry = cls.__registry__
    for edge in edges:
        owner = registry.get_operation((edge.source, edge.target))
        if owner is not None:
            raise TypeError(
                f"{cls.__name__}: edge {_edge_name((edge.source, edge.target))} is already "
                f"implemented by operation {owner.__name__}"
            )
    for edge in edges:
        registry.register_operation((edge.source, edge.target), cls)
    _guard_execute(cls, edges)


@dataclass_transform(kw_only_default=True, frozen_default=True)
class OperationMeta(type):
    """Turns every operation/query class into a frozen, keyword-only, slotted dataclass."""

    def __new__(
        mcs, name: str, bases: tuple[type, ...], namespace: dict[str, Any], **kwargs: Any
    ) -> OperationMeta:
        cls = super().__new__(mcs, name, bases, namespace, **kwargs)
        # Operation/Query themselves, or the slotted copy that dataclass() creates below
        if "__dataclass_fields__" in namespace or not any(isinstance(b, OperationMeta) for b in bases):
            return cls
        # dataclass(slots=True) returns a new class, hence a metaclass and not __init_subclass__
        cls = cast(OperationMeta, dataclasses.dataclass(frozen=True, kw_only=True, slots=True)(cast(Any, cls)))
        validate_operation(cls)
        return cls


class Operation(StateMachine[T], metaclass=OperationMeta):
    """Moves states of the hierarchy rooted at ``T`` along the edges declared by ``execute``."""

    __slots__ = ()
    __registry__: ClassVar[EdgeRegistry] = _default_registry

    def __init_subclass__(cls, registry: EdgeRegistry | None = None, **kwargs: Any) -> None:
        super().__init_subclass__(**kwargs)
        if registry is not None:
            cls.__registry__ = registry


class Query(StateMachine[T], metaclass=OperationMeta):
    """Reads states of the hierarchy rooted at ``T`` without moving them."""

    __slots__ = ()
