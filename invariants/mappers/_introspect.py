from __future__ import annotations

import types
from typing import Any, Union, get_args, get_origin

from sqlalchemy import inspect as sa_inspect
from sqlalchemy.orm import ColumnProperty, RelationshipProperty


def get_orm_columns(orm_cls: type[Any]) -> dict[str, ColumnProperty[Any]]:
    return {ca.key: ca for ca in sa_inspect(orm_cls).mapper.column_attrs}


def get_orm_relationships(orm_cls: type[Any]) -> dict[str, RelationshipProperty[Any]]:
    return {r.key: r for r in sa_inspect(orm_cls).mapper.relationships}


def get_relationship_element_type(rel: RelationshipProperty[Any]) -> type[Any]:
    return rel.mapper.class_


def _is_union(origin: Any) -> bool:
    return origin is Union or origin is types.UnionType


def unwrap_collection_state_types(annotation: Any) -> tuple[type[Any], ...]:
    origin = get_origin(annotation)
    if origin in (tuple, list, set, frozenset):
        args = [a for a in get_args(annotation) if a is not Ellipsis]
        inner = args[0]
        if _is_union(get_origin(inner)):
            return tuple(a for a in get_args(inner) if a is not type(None))
        return (inner,)
    return ()
