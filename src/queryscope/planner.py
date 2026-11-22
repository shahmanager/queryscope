"""Compose canonical slots into a typed logical plan.

The planner never emits SQL. It decides metrics, dimensions, filters, time
and rank, then leaves legality to validation and rendering to the compiler.
"""

from __future__ import annotations

import calendar
import re
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Iterable

from .catalog import SchemaCatalog
from .lexicon import Lexicon, tokenize
from .models import (
    Agg,
    ColumnRef,
    DerivedSource,
    Diagnostic,
    Filter,
    FilterOp,
    IntentFamily,
    Metric,
    OrderTerm,
    QueryPlan,
    TimeRange,
)
from .retrieval import IntentMatch

AMBIGUITY_EPS = 0.04

COUNTRIES = ("USA", "UK", "Germany", "France", "India", "Canada", "Japan", "Brazil")
CATEGORIES = ("Beverages", "Condiments", "Dairy", "Grains", "Produce", "Meat", "Snacks", "Electronics")
STATUSES = ("Shipped", "Delivered", "Processing", "Cancelled")
SEGMENTS = ("Enterprise", "Mid-Market", "SMB")

PREFERRED_DIMENSION = {
    "customers": "company_name",
    "products": "product_name",
    "categories": "category_name",
    "suppliers": "company_name",
    "employees": "full_name",
    "stores": "store_name",
    "orders": "status",
}

VALUE_COLUMNS = (
    ("customers.country", COUNTRIES),
    ("customers.segment", SEGMENTS),
    ("orders.status", STATUSES),
    ("categories.category_name", CATEGORIES),
    ("stores.country", COUNTRIES),
    ("employees.country", COUNTRIES),
    ("suppliers.country", COUNTRIES),
)

NUMERIC_MEASURE_COLUMNS = {
    "orders.freight", "employees.salary", "products.unit_price",
    "products.units_in_stock", "order_items.quantity", "order_items.unit_price",
    "order_items.discount",
}


@dataclass(frozen=True)
class PlanResult:
    plan: QueryPlan | None
    interpretations: tuple[str, ...] = ()
    diagnostics: tuple[Diagnostic, ...] = ()


def _add_months(value: date, months: int) -> date:
    index = (value.year * 12 + value.month - 1) + months
    return date(index // 12, index % 12 + 1, 1)


def _end_of_month(value: date) -> date:
    return date(value.year, value.month, calendar.monthrange(value.year, value.month)[1])


def _resolve_time(marker: str | None, grain: str | None, now: date) -> TimeRange:
    column = ColumnRef("orders", "order_date")
    today = now.date() if isinstance(now, datetime) else now
    if marker == "last_quarter":
        first_this = _add_months(date(today.year, ((today.month - 1) // 3) * 3 + 1, 1), 0)
        start = _add_months(first_this, -3)
        end = _add_months(start, 3) - timedelta(days=1)
    elif marker == "this_quarter":
        start = date(today.year, ((today.month - 1) // 3) * 3 + 1, 1)
        end = today
    elif marker == "last_month":
        first_this = date(today.year, today.month, 1)
        end = first_this - timedelta(days=1)
        start = date(end.year, end.month, 1)
    elif marker == "this_month":
        start = date(today.year, today.month, 1)
        end = today
    elif marker == "last_year":
        start, end = date(today.year - 1, 1, 1), date(today.year - 1, 12, 31)
    elif marker == "this_year":
        start, end = date(today.year, 1, 1), today
    elif marker == "ytd":
        start, end = date(today.year, 1, 1), today
    else:
        # No explicit relative expression: trailing twelve months, documented default.
        end = today
        start = _add_months(date(today.year, today.month, 1), -12)
    _ = grain  # grain shapes the SELECT expression, not the range
    return TimeRange(column, start.isoformat(), end.isoformat())


def _canonical(tokens: Iterable[str], lexicon: Lexicon, question: str) -> tuple[str, ...]:
    return tuple(dict.fromkeys(
        lexicon.canonical_tokens(tokens) + lexicon.phrase_tokens(question)
    ))


def _time_marker(canonicals: tuple[str, ...]) -> str | None:
    for token in canonicals:
        if token.startswith("time:"):
            return token.split(":", 1)[1]
    return None


def _grain(canonicals: tuple[str, ...]) -> str | None:
    for token in canonicals:
        if token.startswith("grain:"):
            return token.split(":", 1)[1]
    if "time:last_quarter" in canonicals or "time:this_quarter" in canonicals:
        return "quarter"
    if "time:last_month" in canonicals or "time:this_month" in canonicals:
        return "month"
    if "time:last_year" in canonicals or "time:this_year" in canonicals or "time:ytd" in canonicals:
        return "year"
    return None


def _agg(canonicals: tuple[str, ...], family: IntentFamily) -> Agg:
    order = (Agg.SUM, Agg.AVG, Agg.COUNT, Agg.MAX, Agg.MIN)
    found = {agg for agg in order if f"agg:{agg.value.lower()}" in canonicals}
    if found:
        return next(agg for agg in order if agg in found)
    return Agg.COUNT if family is IntentFamily.DISTRIBUTION else Agg.SUM


def _measure(canonicals: tuple[str, ...], agg: Agg, catalog: SchemaCatalog) -> DerivedSource | ColumnRef | None:
    for token in canonicals:
        if token.startswith("measure:"):
            return DerivedSource(token.split(":", 1)[1])
    if agg is Agg.COUNT:
        return None
    for token in canonicals:
        if token.startswith("column:") and token.split(":", 1)[1] in NUMERIC_MEASURE_COLUMNS:
            return ColumnRef(*token.split(":", 1)[1].split("."))
    return DerivedSource.LINE_REVENUE


def _explicit_columns(canonicals: tuple[str, ...], catalog: SchemaCatalog) -> list[ColumnRef]:
    columns: list[ColumnRef] = []
    for token in canonicals:
        if not token.startswith("column:"):
            continue
        key = token.split(":", 1)[1]
        if catalog.has_column(key):
            ref = ColumnRef(*key.split("."))
            if ref not in columns:
                columns.append(ref)
    return columns


def _mentioned_tables(canonicals: tuple[str, ...]) -> list[str]:
    return [
        token.split(":", 1)[1] for token in canonicals
        if token.startswith("table:")
    ]


def _dimensions(
    canonicals: tuple[str, ...], family: IntentFamily, catalog: SchemaCatalog,
    explicit: list[ColumnRef], mentioned: list[str], grain: str | None,
    grouping_tables: tuple[str, ...] = (),
) -> tuple[ColumnRef, ...]:
    dims: list[ColumnRef] = []
    if family is IntentFamily.TREND and grain:
        dims.append(ColumnRef("orders", "order_date"))
    for ref in explicit:
        info = catalog.column(ref.key)
        if info.affinity in ("TEXT", "DATE") and ref not in dims:
            dims.append(ref)
    for table in mentioned:
        if family is IntentFamily.AGGREGATE and table not in grouping_tables:
            continue
        preferred = PREFERRED_DIMENSION.get(table)
        if not preferred or not catalog.has_column(f"{table}.{preferred}"):
            continue
        if any(d.table == table for d in dims):
            continue
        candidate = ColumnRef(table, preferred)
        if candidate not in dims:
            dims.append(candidate)
    if family is IntentFamily.TOP_N and not dims:
        dims.append(ColumnRef("products", "product_name"))
    return tuple(dims)


def _filters(question: str, scope_tables: list[str]) -> tuple[Filter, ...]:
    lower = " " + re.sub(r"[^a-z0-9_]+", " ", question.lower()) + " "
    found: list[Filter] = []
    for key, values in VALUE_COLUMNS:
        table = key.split(".")[0]
        matches = [v for v in values if f" {v.lower()} " in lower]
        if not matches:
            continue
        if table not in scope_tables and "customers" in scope_tables:
            key = "customers.country"
        if any(f.column.key == key for f in found):
            continue
        op = FilterOp.IN if len(matches) > 1 else FilterOp.EQ
        value = tuple(matches) if len(matches) > 1 else matches[0]
        found.append(Filter(ColumnRef(*key.split(".")), op, value))
    if "discontinued" in lower:
        key = "products.discontinued"
        if not any(f.column.key == key for f in found):
            found.append(Filter(ColumnRef("products", "discontinued"), FilterOp.EQ, 1))
    product_match = re.search(r"\bproduct\s+(\d+)\b", lower)
    if product_match:
        found.append(Filter(ColumnRef("products", "product_id"), FilterOp.EQ, int(product_match.group(1))))
    return tuple(found)


def _limit(question: str, canonicals: tuple[str, ...], family: IntentFamily) -> int | None:
    if family is not IntentFamily.TOP_N:
        return None
    numbers = [int(n) for n in re.findall(r"\b\d+\b", question)]
    return min(max(numbers[0], 1), 1000) if numbers else 5


def build_plan(
    question: str,
    family: IntentFamily,
    lexicon: Lexicon,
    catalog: SchemaCatalog,
    now: datetime,
    alternatives: tuple[IntentMatch, ...] = (),
) -> PlanResult:
    """Build a plan, or a clarification request when the intent is ambiguous.

    Relative time is resolved against ``now``. "Last quarter" means the most
    recently *completed* calendar quarter, so with now=2026-06-30 it resolves
    to 2026-01-01..2026-03-31. Unspecified time means trailing 12 months.
    """
    if alternatives:
        tied = [m for m in alternatives if m.score >= alternatives[0].score - AMBIGUITY_EPS]
        distinct = {m.family for m in tied}
        if len(distinct) > 1:
            return PlanResult(
                None,
                interpretations=tuple(sorted(f.value for f in distinct)),
                diagnostics=(Diagnostic("AMBIGUOUS", "Multiple intents fit this question"),),
            )

    canonicals = _canonical(tokenize(question), lexicon, question)
    if family is IntentFamily.OUT_OF_SCOPE:
        return PlanResult(None, diagnostics=(Diagnostic("OUT_OF_SCOPE", "Unsupported request"),))

    grain = _grain(canonicals)
    agg = _agg(canonicals, family)
    marker = _time_marker(canonicals)
    explicit = _explicit_columns(canonicals, catalog)
    mentioned = _mentioned_tables(canonicals)

    wants_time = family is IntentFamily.TREND or marker is not None or grain is not None
    time_range = _resolve_time(marker, grain, now) if wants_time else None

    lowered = f" {question.lower()} "
    after_by = lowered.split(" by ", 1)[1] if " by " in lowered else ""
    by_canonicals = _canonical(tokenize(after_by), lexicon, after_by) if after_by else ()
    grouping_tables = tuple(_mentioned_tables(by_canonicals))
    dims = _dimensions(canonicals, family, catalog, explicit, mentioned, grain, grouping_tables)
    scope = [d.table for d in dims]
    source = _measure(canonicals, agg, catalog)
    if isinstance(source, ColumnRef):
        scope.append(source.table)
    elif source is DerivedSource.LINE_REVENUE or source is DerivedSource.LINE_QUANTITY:
        scope.append("order_items")
    if time_range:
        scope.append(time_range.column.table)
    filters = _filters(question, list(dict.fromkeys(scope)))
    scope.extend(f.column.table for f in filters)

    metrics: tuple[Metric, ...] = ()
    if family not in (IntentFamily.LOOKUP, IntentFamily.JOIN_LOOKUP):
        metrics = (Metric(agg, source, "metric_1"),)

    order_desc = "rank:asc" not in canonicals
    order = (OrderTerm(metric_alias="metric_1", descending=order_desc),) if metrics else ()

    plan = QueryPlan(
        family=family,
        metrics=metrics,
        dimensions=dims,
        filters=filters,
        time_range=time_range,
        time_grain=grain if wants_time else None,
        order_by=order,
        limit=_limit(question, canonicals, family),
    )
    return PlanResult(plan)
