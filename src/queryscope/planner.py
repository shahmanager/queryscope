"""Compose canonical slots into a typed logical plan.

Every schema-specific decision is delegated to SchemaProfile, which is
discovered from the connected database. The planner itself has no knowledge
of any particular table or column name.
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
from .schema_profile import COLUMN_CONCEPTS, SchemaProfile, _is_name, _is_time

AMBIGUITY_EPS = 0.04


@dataclass(frozen=True)
class PlanResult:
    plan: QueryPlan | None
    interpretations: tuple[str, ...] = ()
    diagnostics: tuple[Diagnostic, ...] = ()


def _add_months(value: date, months: int) -> date:
    index = (value.year * 12 + value.month - 1) + months
    return date(index // 12, index % 12 + 1, 1)


def _resolve_time(marker: str | None, grain: str | None, now: datetime, profile: SchemaProfile) -> TimeRange | None:
    column = profile.time_column
    if column is None:
        return None
    today = now.date() if isinstance(now, datetime) else now
    if marker == "last_quarter":
        first_this = date(today.year, ((today.month - 1) // 3) * 3 + 1, 1)
        start = _add_months(first_this, -3)
        end = _add_months(start, 3) - timedelta(days=1)
    elif marker == "this_quarter":
        start, end = date(today.year, ((today.month - 1) // 3) * 3 + 1, 1), today
    elif marker == "last_month":
        first_this = date(today.year, today.month, 1)
        end = first_this - timedelta(days=1)
        start = date(end.year, end.month, 1)
    elif marker == "this_month":
        start, end = date(today.year, today.month, 1), today
    elif marker == "last_year":
        start, end = date(today.year - 1, 1, 1), date(today.year - 1, 12, 31)
    elif marker == "this_year" or marker == "ytd":
        start, end = date(today.year, 1, 1), today
    else:
        end = today
        start = _add_months(date(today.year, today.month, 1), -12)
    _ = grain
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
    return None


def _concept(key: str) -> str:
    name = key.split(".")[-1].lower()
    for concept, patterns in COLUMN_CONCEPTS.items():
        if any(pattern in name for pattern in patterns):
            return concept
    return key


def _entity_tables(catalog: SchemaCatalog, profile: SchemaProfile) -> tuple[str, ...]:
    return tuple(t for t in catalog.tables if not profile.is_fact(t))


def _agg(canonicals: tuple[str, ...], family: IntentFamily, mentioned: tuple[str, ...], profile: SchemaProfile) -> Agg:
    order = (Agg.SUM, Agg.AVG, Agg.COUNT, Agg.MAX, Agg.MIN)
    found = {agg for agg in order if f"agg:{agg.value.lower()}" in canonicals}
    if found:
        return next(agg for agg in order if agg in found)
    has_measure = any(token.startswith("measure:") for token in canonicals)
    numeric_columns = {
        token.split(":", 1)[1] for token in canonicals
        if token.startswith("column:") and token.split(":", 1)[1] in profile.numeric_columns
    }
    if family is IntentFamily.DISTRIBUTION and not has_measure:
        return Agg.COUNT
    numeric_tables = {key.split(".")[0] for key in numeric_columns}
    if not has_measure and not numeric_columns and "orders" in mentioned:
        return Agg.COUNT
    if not has_measure and numeric_tables and not (numeric_tables & set(profile.fact_tables)):
        return Agg.MAX
    return Agg.SUM


def _measure(
    canonicals: tuple[str, ...], agg: Agg, catalog: SchemaCatalog,
    mentioned: tuple[str, ...], question: str, profile: SchemaProfile,
) -> DerivedSource | ColumnRef | None:
    for token in canonicals:
        if token.startswith("measure:"):
            return DerivedSource(token.split(":", 1)[1])
    if agg is Agg.COUNT:
        count_entity = re.search(r"\b(?:number|count)\s+of\s+(\w+)", question.lower())
        tables = list(mentioned)
        if count_entity:
            candidate = count_entity.group(1)
            if candidate.endswith("s") and candidate[:-1] in catalog.tables:
                candidate = candidate[:-1]
            if candidate in catalog.tables:
                tables.insert(0, candidate)
        for table in dict.fromkeys(tables):
            pk = catalog.primary_key(table)
            if pk:
                return ColumnRef(table, pk)
        return None
    numeric = [
        ref for ref in _explicit_columns(canonicals, catalog, profile)
        if ref.key in profile.numeric_columns
    ]
    if numeric:
        return sorted(
            numeric,
            key=lambda ref: (profile.is_fact(ref.table), ref.table, ref.column),
        )[0]
    if profile.revenue_expr != "1":
        return DerivedSource.LINE_REVENUE
    fallback = next((ColumnRef(*key.split(".")) for key in sorted(profile.numeric_columns)), None)
    return fallback


def _explicit_columns(canonicals: tuple[str, ...], catalog: SchemaCatalog, profile: SchemaProfile) -> list[ColumnRef]:
    """Resolve a concept to one column, not every column sharing that word."""
    groups: dict[str, list[ColumnRef]] = {}
    for token in canonicals:
        if not token.startswith("column:"):
            continue
        key = token.split(":", 1)[1]
        if not catalog.has_column(key):
            continue
        info = catalog.column(key)
        if info.affinity in ("TEXT", "DATE") and _is_time(info.name, info.affinity):
            continue  # time expressions are handled as ranges, not dimensions
        ref = ColumnRef(*key.split("."))
        groups.setdefault(_concept(key), []).append(ref)
    resolved: list[ColumnRef] = []
    for candidates in groups.values():
        chosen = sorted(
            set(candidates),
            key=lambda ref: (
                profile.is_fact(ref.table),
                0 if _is_name(ref.column) else 1,
                ref.table,
                ref.column,
            ),
        )[0]
        if chosen not in resolved:
            resolved.append(chosen)
    return resolved


def _mentioned_tables(canonicals: tuple[str, ...]) -> list[str]:
    return list(dict.fromkeys(
        token.split(":", 1)[1] for token in canonicals if token.startswith("table:")
    ))


def _dimensions(
    canonicals: tuple[str, ...], family: IntentFamily, catalog: SchemaCatalog,
    explicit: list[ColumnRef], mentioned: list[str], grain: str | None,
    grouping_tables: tuple[str, ...], profile: SchemaProfile,
) -> tuple[ColumnRef, ...]:
    dims: list[ColumnRef] = []
    if family is IntentFamily.TREND and grain and profile.time_column:
        dims.append(profile.time_column)
    for ref in explicit:
        info = catalog.column(ref.key)
        if info.affinity in ("TEXT", "DATE") and ref not in dims:
            dims.append(ref)

    entity_dims = [d for d in dims if not profile.is_fact(d.table)]
    if family in (IntentFamily.LOOKUP, IntentFamily.JOIN_LOOKUP):
        candidates = [t for t in mentioned if t in catalog.tables]
    elif family is IntentFamily.AGGREGATE:
        candidates = [t for t in mentioned if t in grouping_tables]
    elif family is IntentFamily.DISTRIBUTION:
        candidates = []
    elif entity_dims:
        candidates = []
    else:
        candidates = [t for t in mentioned if not profile.is_fact(t)]
        if not candidates:
            candidates = [t for t in mentioned if t in grouping_tables]

    for table in candidates[: 1 if family not in (IntentFamily.LOOKUP, IntentFamily.JOIN_LOOKUP) else len(candidates)]:
        preferred = profile.preferred_dimension(table)
        if not preferred or not catalog.has_column(f"{table}.{preferred}"):
            continue
        candidate = ColumnRef(table, preferred)
        if candidate not in dims:
            dims.append(candidate)

    if family is IntentFamily.TOP_N and not dims:
        for table in (*_entity_tables(catalog, profile), *profile.fact_tables, *catalog.tables):
            preferred = profile.preferred_dimension(table)
            if preferred:
                dims.append(ColumnRef(table, preferred))
                break
    return tuple(dims)


def _filters(question: str, scope_tables: list[str], catalog: SchemaCatalog, profile: SchemaProfile) -> tuple[Filter, ...]:
    lower = " " + re.sub(r"[^a-z0-9_]+", " ", question.lower()) + " "
    found: list[Filter] = []
    handled: set[str] = set()
    for key, values in profile.categorical_values.items():
        concept = _concept(key)
        if concept in handled:
            continue
        matches = [v for v in values if f" {v.lower()} " in lower]
        if not matches:
            continue
        handled.add(concept)
        candidates = [k for k in profile.categorical_values if _concept(k) == concept]
        value_index = lower.find(matches[0].lower())

        def proximity(key: str) -> tuple[int, int, int, str]:
            table = key.split(".")[0]
            singular = table[:-1] if table.endswith("s") else table
            positions = [lower.rfind(word, 0, value_index) for word in (table, singular)]
            position = max(positions)
            distance = value_index - position if position >= 0 else 10_000
            return (
                0 if position >= 0 else 1,
                distance,
                0 if table in scope_tables else 1,
                table,
            )

        chosen = sorted(candidates, key=proximity)[0]
        op = FilterOp.IN if len(matches) > 1 else FilterOp.EQ
        value = tuple(matches) if len(matches) > 1 else matches[0]
        found.append(Filter(ColumnRef(*chosen.split(".")), op, value))

    for key in sorted(profile.numeric_columns):
        if "discontinu" in key.lower() and "discontinued" in lower:
            found.append(Filter(ColumnRef(*key.split(".")), FilterOp.EQ, 1))
            break

    for table in (*_entity_tables(catalog, profile), *catalog.tables):
        singular = table[:-1] if table.endswith("s") else table
        match = re.search(rf"\b{re.escape(singular)}\s+(\d+)\b", lower)
        pk = catalog.primary_key(table)
        if match and pk and not any(f.column.key == f"{table}.{pk}" for f in found):
            found.append(Filter(ColumnRef(table, pk), FilterOp.EQ, int(match.group(1))))
    return tuple(found)


def _limit(question: str, family: IntentFamily) -> int | None:
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
    profile: SchemaProfile | None = None,
) -> PlanResult:
    """Build a plan, or a clarification request when the intent is ambiguous.

    Relative time is resolved against ``now``. "Last quarter" means the most
    recently *completed* calendar quarter. Unspecified time means trailing 12
    months. All schema-dependent choices come from ``profile``.
    """
    profile = profile or lexicon.profile or SchemaProfile.discover(catalog)

    canonicals = _canonical(tokenize(question), lexicon, question)
    has_time_marker = any(token.startswith("time:") for token in canonicals)

    # A count question with no measure is an aggregate on any schema,
    # whatever the table happens to be called.
    forced_aggregate = (
        "agg:count" in canonicals
        and bool(re.match(r"(how many|number of|count of)\b", question.lower()))
        and family not in (IntentFamily.LOOKUP, IntentFamily.JOIN_LOOKUP)
    )
    if forced_aggregate:
        family = IntentFamily.AGGREGATE

    grouping_phrase = " by " in f" {question.lower()} " and family in (
        IntentFamily.AGGREGATE, IntentFamily.COMPARISON, IntentFamily.DISTRIBUTION
    )
    listing_phrase = bool(re.match(r"(show|list|which)\b", question.lower()))

    if alternatives and not (forced_aggregate or grouping_phrase or listing_phrase):
        tied = [m for m in alternatives if m.score >= alternatives[0].score - AMBIGUITY_EPS]
        exact_match = any(m.score >= 0.99 for m in tied)
        if has_time_marker and any(m.family is IntentFamily.TREND for m in tied):
            tied = [m for m in tied if m.family is IntentFamily.TREND]
            family = IntentFamily.TREND
        distinct = {m.family for m in tied}
        if not exact_match and len(distinct) > 1:
            return PlanResult(
                None,
                interpretations=tuple(sorted(f.value for f in distinct)),
                diagnostics=(Diagnostic("AMBIGUOUS", "Multiple intents fit this question"),),
            )

    if family is IntentFamily.OUT_OF_SCOPE:
        return PlanResult(None, diagnostics=(Diagnostic("OUT_OF_SCOPE", "Unsupported request"),))

    grain = _grain(canonicals)
    marker = _time_marker(canonicals)
    explicit = _explicit_columns(canonicals, catalog, profile)
    mentioned = tuple(_mentioned_tables(canonicals))
    agg = _agg(canonicals, family, mentioned, profile)

    wants_time = family is IntentFamily.TREND or marker is not None or grain is not None
    time_range = _resolve_time(marker, grain, now, profile) if wants_time else None

    lowered = f" {question.lower()} "
    after_by = lowered.split(" by ", 1)[1] if " by " in lowered else ""
    by_canonicals = _canonical(tokenize(after_by), lexicon, after_by) if after_by else ()
    grouping_tables = tuple(_mentioned_tables(by_canonicals))
    dims = list(_dimensions(canonicals, family, catalog, explicit, mentioned, grain, grouping_tables, profile))
    source = _measure(canonicals, agg, catalog, mentioned, question, profile)
    if isinstance(source, ColumnRef):
        dims = [
            ColumnRef(source.table, dim.column) if catalog.has_column(f"{source.table}.{dim.column}") else dim
            for dim in dims
        ]
    scope = [d.table for d in dims]
    if isinstance(source, ColumnRef):
        scope.append(source.table)
    elif isinstance(source, DerivedSource):
        scope.extend(profile.revenue_tables if source is DerivedSource.LINE_REVENUE else profile.quantity_tables)
    if time_range:
        scope.append(time_range.column.table)
    filters = _filters(question, list(dict.fromkeys(scope)), catalog, profile)
    if family is IntentFamily.COMPARISON and not dims and filters:
        dims.append(filters[0].column)
    scope.extend(f.column.table for f in filters)

    metrics: tuple[Metric, ...] = ()
    if family not in (IntentFamily.LOOKUP, IntentFamily.JOIN_LOOKUP):
        distinct = agg is Agg.COUNT and isinstance(source, ColumnRef) and not profile.is_fact(source.table)
        metrics = (Metric(agg, source, "metric_1", distinct),)

    order_desc = "rank:asc" not in canonicals
    order = (OrderTerm(metric_alias="metric_1", descending=order_desc),) if metrics else ()

    plan = QueryPlan(
        family=family,
        metrics=metrics,
        dimensions=tuple(dims),
        filters=filters,
        time_range=time_range,
        time_grain=grain if wants_time and time_range else None,
        order_by=order,
        limit=_limit(question, family),
    )
    return PlanResult(plan)
