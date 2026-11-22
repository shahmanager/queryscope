"""Plan legality checks. Every rejection is a structured diagnostic."""

from __future__ import annotations

from .catalog import SchemaCatalog
from .models import Agg, ColumnRef, DerivedSource, Diagnostic, QueryPlan

NUMERIC = ("INT", "REAL")


def validate(plan: QueryPlan, catalog: SchemaCatalog) -> tuple[Diagnostic, ...]:
    diagnostics: list[Diagnostic] = []

    if not plan.metrics and not plan.dimensions:
        diagnostics.append(Diagnostic("EMPTY_PLAN", "A plan must select a metric or a dimension"))

    tables: set[str] = set()

    for metric in plan.metrics:
        source = metric.source
        if source is None:
            if metric.agg is not Agg.COUNT:
                diagnostics.append(Diagnostic("BAD_COUNT", "COUNT(*) is the only source-less metric"))
            continue
        if isinstance(source, DerivedSource):
            if not catalog.has_column("order_items.quantity"):
                diagnostics.append(Diagnostic("MISSING_MEASURE", f"Unknown measure {source.value}"))
            tables.add("order_items")
            continue
        if not catalog.has_column(source.key):
            diagnostics.append(Diagnostic("UNKNOWN_COLUMN", f"Unknown column {source.key}"))
            continue
        info = catalog.column(source.key)
        tables.add(source.table)
        if metric.agg in (Agg.SUM, Agg.AVG) and info.affinity not in NUMERIC:
            diagnostics.append(
                Diagnostic("BAD_AGGREGATION", f"{metric.agg.value} is not valid on {source.key} ({info.affinity})")
            )

    for dim in plan.dimensions:
        if not catalog.has_column(dim.key):
            diagnostics.append(Diagnostic("UNKNOWN_COLUMN", f"Unknown column {dim.key}"))
        else:
            tables.add(dim.table)

    for flt in plan.filters:
        if not catalog.has_column(flt.column.key):
            diagnostics.append(Diagnostic("UNKNOWN_COLUMN", f"Unknown column {flt.column.key}"))
            continue
        tables.add(flt.column.table)
        info = catalog.column(flt.column.key)
        values = flt.value if isinstance(flt.value, (tuple, list)) else (flt.value,)
        if info.affinity in NUMERIC:
            for value in values:
                if isinstance(value, str) and not value.lstrip("-").isdigit():
                    diagnostics.append(
                        Diagnostic("BAD_FILTER", f"Non-numeric filter value for {flt.column.key}")
                    )

    if plan.time_range is not None:
        if not catalog.has_column(plan.time_range.column.key):
            diagnostics.append(Diagnostic("UNKNOWN_COLUMN", f"Unknown column {plan.time_range.column.key}"))
        else:
            tables.add(plan.time_range.column.table)
        if plan.time_range.start > plan.time_range.end:
            diagnostics.append(Diagnostic("BAD_RANGE", "Time range start is after end"))

    if plan.limit is not None and not (1 <= plan.limit <= 1000):
        diagnostics.append(Diagnostic("BAD_LIMIT", "Limit must be between 1 and 1000"))

    if plan.time_grain not in (None, "month", "quarter", "year"):
        diagnostics.append(Diagnostic("BAD_GRAIN", f"Unsupported time grain {plan.time_grain}"))

    if len(tables) > 1 and catalog.fk_path(tables) is None:
        diagnostics.append(Diagnostic("NO_JOIN_PATH", f"No foreign-key path joins {sorted(tables)}"))

    return tuple(diagnostics)
