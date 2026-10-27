"""Introspection of state hierarchies shared by operations and visualization."""

from __future__ import annotations

import types
import typing
from collections import defaultdict
from dataclasses import dataclass
from typing import Any, Union, get_args, get_origin

from typing_extensions import get_original_bases

from invariants.state import State, StateMachine


def get_root_state(machine_cls: type) -> type[State] | None:
    """Extract the generic parameter T from StateMachine[T]."""
    for base in get_original_bases(machine_cls):
        origin = get_origin(base)
        if origin is not None and issubclass(origin, StateMachine):
            args = get_args(base)
            if args and len(args) == 1 and isinstance(args[0], type) and issubclass(args[0], State):
                return args[0]
    return None


def get_concrete_states(root_state: type[State]) -> list[type[State]]:
    """Get all concrete (non-Statefull) descendants of a root state."""
    result: list[type[State]] = []

    def walk(cls: type[State]) -> None:
        if cls is not root_state and not cls.has_statefull_fields():
            result.append(cls)
        for sub in cls.__subclasses__():
            walk(sub)

    walk(root_state)
    return result


def _is_state_subclass(t: Any) -> bool:
    return isinstance(t, type) and issubclass(t, State)


def unwrap_state_types(annotation: Any) -> set[type[State]]:
    """Recursively unwrap a type annotation to find all State subclasses."""
    if _is_state_subclass(annotation):
        return {annotation}

    origin = get_origin(annotation)

    # Annotated[X, ...] → unwrap X
    if origin is typing.Annotated:
        args = get_args(annotation)
        if args:
            return unwrap_state_types(args[0])

    # Union / X | Y → unwrap each
    if origin is Union or origin is types.UnionType:
        result: set[type[State]] = set()
        for arg in get_args(annotation):
            result |= unwrap_state_types(arg)
        return result

    # tuple[X, ...] → unwrap X
    if origin is tuple:
        args = get_args(annotation)
        if args:
            result = set()
            for arg in args:
                if arg is not Ellipsis:
                    result |= unwrap_state_types(arg)
            return result

    return set()


def find_state_root(state_types: set[type[State]]) -> type[State] | None:
    """Find the common root State for a set of concrete states."""
    if not state_types:
        return None

    def _get_root(cls: type) -> type[State] | None:
        for klass in cls.__mro__:
            if klass is State or klass is object:
                continue  # pragma: no cover
            if issubclass(klass, State) and State in klass.__bases__:
                return klass
        return None  # pragma: no cover

    roots = {_get_root(t) for t in state_types}
    roots.discard(None)
    if len(roots) == 1:
        return roots.pop()
    return None


def is_concrete_state(t: Any) -> bool:
    """A state that can be instantiated: a non-root State without Statefull fields."""
    return (
        _is_state_subclass(t)
        and not t.has_statefull_fields()
        and find_state_root({t}) not in (None, t)
    )


@dataclass
class NestingRelation:
    parent_root: type[State]
    child_root: type[State]
    field_name: str
    allowed_children: dict[type[State], set[type[State]]]


def detect_nesting(
    parent_root: type[State],
    child_roots: set[type[State]],
) -> list[NestingRelation]:
    """Detect nesting relationships between parent and child state hierarchies."""
    concrete_parents = get_concrete_states(parent_root)
    # field_name → {parent_concrete → set of child states}
    field_groups: dict[str, dict[type[State], set[type[State]]]] = defaultdict(
        lambda: defaultdict(set)
    )

    for parent_cls in concrete_parents:
        hints = typing.get_type_hints(parent_cls, include_extras=True)
        for field_name, annotation in hints.items():
            state_types = unwrap_state_types(annotation)
            if state_types:
                root = find_state_root(state_types)
                if root is not None and root in child_roots and root is not parent_root:
                    field_groups[field_name][parent_cls] = state_types

    result: list[NestingRelation] = []
    for field_name, parent_map in field_groups.items():
        if not parent_map:  # pragma: no cover
            continue
        # All should share the same child root
        all_types = set()
        for types_set in parent_map.values():
            all_types |= types_set
        child_root = find_state_root(all_types)
        if child_root is None:  # pragma: no cover
            continue
        result.append(NestingRelation(
            parent_root=parent_root,
            child_root=child_root,
            field_name=field_name,
            allowed_children=dict(parent_map),
        ))

    return result


def get_nested_roots(root_state: type[State]) -> set[type[State]]:
    """Roots of all hierarchies nested (directly or transitively) in ``root_state``'s fields."""
    result: set[type[State]] = set()
    pending = [root_state]
    while pending:
        parent = pending.pop()
        candidates: set[type[State]] = set()
        for concrete in get_concrete_states(parent):
            for annotation in typing.get_type_hints(concrete, include_extras=True).values():
                child_root = find_state_root(unwrap_state_types(annotation))
                if child_root is not None:
                    candidates.add(child_root)
        for nesting in detect_nesting(parent, candidates):
            if nesting.child_root is not root_state and nesting.child_root not in result:
                result.add(nesting.child_root)
                pending.append(nesting.child_root)
    return result
