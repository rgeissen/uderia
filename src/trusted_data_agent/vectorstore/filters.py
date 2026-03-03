"""
Backend-agnostic metadata filter AST.

Callers build filters using FieldFilter / AndFilter / OrFilter. Each backend
translates the AST to its native query format:
  - ChromaDB: nested dict  {"$and": [{"field": {"$eq": v}}, ...]}
  - Teradata:  SQL WHERE clause (implemented in teradata_backend.py)

The ``from_chromadb_where()`` bridge lets existing ChromaDB-format dicts be
passed through during the migration without changing all call sites at once.
"""

from __future__ import annotations
from dataclasses import dataclass
from enum import Enum
from typing import Any, Dict, List, Optional, Union


class FilterOp(Enum):
    EQ = "eq"
    NE = "ne"
    GT = "gt"
    GTE = "gte"
    LT = "lt"
    LTE = "lte"
    IN = "in"
    NOT_IN = "not_in"


@dataclass
class FieldFilter:
    """A single field predicate: ``field op value``."""
    field: str
    op: FilterOp
    value: Any


@dataclass
class AndFilter:
    """Logical AND of two or more sub-filters."""
    conditions: List[MetadataFilter]


@dataclass
class OrFilter:
    """Logical OR of two or more sub-filters."""
    conditions: List[MetadataFilter]


# Type alias – any node in the filter tree
MetadataFilter = Optional[Union[FieldFilter, AndFilter, OrFilter]]


# ── ChromaDB translator ───────────────────────────────────────────────────────

_OP_TO_CHROMA: Dict[FilterOp, str] = {
    FilterOp.EQ: "$eq",
    FilterOp.NE: "$ne",
    FilterOp.GT: "$gt",
    FilterOp.GTE: "$gte",
    FilterOp.LT: "$lt",
    FilterOp.LTE: "$lte",
    FilterOp.IN: "$in",
    FilterOp.NOT_IN: "$nin",
}

_CHROMA_TO_OP: Dict[str, FilterOp] = {v: k for k, v in _OP_TO_CHROMA.items()}


def to_chromadb_where(f: MetadataFilter) -> Optional[Dict]:
    """Translate a MetadataFilter tree into a ChromaDB ``where`` dict."""
    if f is None:
        return None
    if isinstance(f, FieldFilter):
        return {f.field: {_OP_TO_CHROMA[f.op]: f.value}}
    if isinstance(f, AndFilter):
        translated = [to_chromadb_where(c) for c in f.conditions]
        return {"$and": translated}
    if isinstance(f, OrFilter):
        translated = [to_chromadb_where(c) for c in f.conditions]
        return {"$or": translated}
    raise TypeError(f"Unknown filter type: {type(f)}")


def from_chromadb_where(where: Optional[Dict]) -> MetadataFilter:
    """Parse a ChromaDB-format ``where`` dict into a MetadataFilter tree.

    This is the migration bridge: code that currently passes raw ChromaDB
    dicts can call this to convert before invoking backend methods.
    """
    if where is None:
        return None

    if "$and" in where:
        return AndFilter([from_chromadb_where(c) for c in where["$and"]])

    if "$or" in where:
        return OrFilter([from_chromadb_where(c) for c in where["$or"]])

    # Single field: {"field": {"$op": value}}  or  {"field": value}
    for field_name, condition in where.items():
        if isinstance(condition, dict):
            for op_str, value in condition.items():
                op = _CHROMA_TO_OP.get(op_str, FilterOp.EQ)
                return FieldFilter(field_name, op, value)
        else:
            # Shorthand equality: {"field": value}
            return FieldFilter(field_name, FilterOp.EQ, condition)

    return None


# ── Convenience constructors ──────────────────────────────────────────────────

def eq(field: str, value: Any) -> FieldFilter:
    return FieldFilter(field, FilterOp.EQ, value)


def ne(field: str, value: Any) -> FieldFilter:
    return FieldFilter(field, FilterOp.NE, value)


def gt(field: str, value: Any) -> FieldFilter:
    return FieldFilter(field, FilterOp.GT, value)


def gte(field: str, value: Any) -> FieldFilter:
    return FieldFilter(field, FilterOp.GTE, value)


def lt(field: str, value: Any) -> FieldFilter:
    return FieldFilter(field, FilterOp.LT, value)


def lte(field: str, value: Any) -> FieldFilter:
    return FieldFilter(field, FilterOp.LTE, value)


def and_(*conditions: MetadataFilter) -> AndFilter:
    return AndFilter(list(conditions))


def or_(*conditions: MetadataFilter) -> OrFilter:
    return OrFilter(list(conditions))
