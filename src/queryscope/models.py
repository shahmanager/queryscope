"""Typed value objects shared by every layer of the pipeline.

Nothing in this module builds SQL. These are the vocabulary the compiler
uses, which is what makes validation and safety structural rather than
advisory.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any, Literal


class Agg(str, Enum):
    COUNT = "COUNT"
    SUM = "SUM"
    AVG = "AVG"
    MIN = "MIN"
    MAX = "MAX"


class FilterOp(str, Enum):
    EQ = "="
    NE = "!="
    GT = ">"
    GTE = ">="
    LT = "<"
    LTE = "<="
    IN = "IN"
    LIKE = "LIKE"
    BETWEEN = "BETWEEN"


class IntentFamily(str, Enum):
    LOOKUP = "lookup"
    AGGREGATE = "aggregate"
    TREND = "trend"
    TOP_N = "top_n"
    COMPARISON = "comparison"
    DISTRIBUTION = "distribution"
    JOIN_LOOKUP = "join_lookup"
    OUT_OF_SCOPE = "out_of_scope"


class DerivedSource(str, Enum):
    """Named business measures with fixed, auditable SQL expressions."""

    LINE_REVENUE = "line_revenue"
    LINE_QUANTITY = "line_quantity"


@dataclass(frozen=True)
class ColumnRef:
    table: str
    column: str

    @property
    def key(self) -> str:
        return f"{self.table}.{self.column}"


@dataclass(frozen=True)
class Metric:
    agg: Agg
    source: ColumnRef | DerivedSource | None = None  # None -> COUNT(*)
    alias: str = "metric_1"


@dataclass(frozen=True)
class Filter:
    column: ColumnRef
    op: FilterOp
    value: Any
    value2: Any = None


@dataclass(frozen=True)
class TimeRange:
    column: ColumnRef
    start: str
    end: str


@dataclass(frozen=True)
class OrderTerm:
    metric_alias: str | None = None
    column: ColumnRef | None = None
    descending: bool = True


@dataclass(frozen=True)
class QueryPlan:
    family: IntentFamily
    metrics: tuple[Metric, ...] = ()
    dimensions: tuple[ColumnRef, ...] = ()
    filters: tuple[Filter, ...] = ()
    time_range: TimeRange | None = None
    order_by: tuple[OrderTerm, ...] = ()
    limit: int | None = None


@dataclass(frozen=True)
class Diagnostic:
    code: str
    message: str


@dataclass(frozen=True)
class Answer:
    question: str
    status: Literal["answered", "needs_clarification", "refused"]
    sql: str | None = None
    params: tuple[Any, ...] = ()
    columns: tuple[str, ...] = ()
    rows: tuple[tuple[Any, ...], ...] = ()
    confidence: float = 0.0
    family: IntentFamily | None = None
    diagnostics: tuple[Diagnostic, ...] = ()
    clarification: str | None = None
    interpretations: tuple[str, ...] = ()
    latency_ms: float = 0.0
    estimated_cost: float = 0.0
