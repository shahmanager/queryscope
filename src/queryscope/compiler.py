"""Typed plan -> parameterized SQL.

Identifiers come only from the introspected catalog; literals are always
bound parameters. There is no code path from user text into SQL text.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .catalog import SchemaCatalog
from .models import ColumnRef, DerivedSource, FilterOp, QueryPlan
from .schema_profile import SchemaProfile


@dataclass(frozen=True)
class CompiledSQL:
    sql: str
    params: tuple[Any, ...]


def quote(identifier: str) -> str:
    return '"' + identifier.replace('"', '""') + '"'


def colref_sql(ref: ColumnRef) -> str:
    return f"{quote(ref.table)}.{quote(ref.column)}"


def _grain_sql(grain: str, column_sql: str) -> str:
    if grain == "month":
        return f"strftime('%Y-%m', {column_sql})"
    if grain == "year":
        return f"strftime('%Y', {column_sql})"
    return (
        f"(strftime('%Y', {column_sql}) || '-Q' || "
        f"CAST((CAST(strftime('%m', {column_sql}) AS INTEGER) + 2) / 3 AS TEXT))"
    )


def source_sql(source: DerivedSource | ColumnRef | None, profile: SchemaProfile) -> str:
    if source is None:
        return "*"
    if isinstance(source, DerivedSource):
        if source is DerivedSource.LINE_REVENUE:
            return profile.revenue_expr
        return profile.quantity_expr
    return colref_sql(source)


def _involved_tables(plan: QueryPlan, profile: SchemaProfile) -> list[str]:
    tables: list[str] = []
    for metric in plan.metrics:
        source = metric.source
        if isinstance(source, ColumnRef):
            tables.append(source.table)
        elif isinstance(source, DerivedSource):
            tables.extend(
                profile.revenue_tables if source is DerivedSource.LINE_REVENUE
                else profile.quantity_tables
            )
    tables.extend(d.table for d in plan.dimensions)
    tables.extend(f.column.table for f in plan.filters)
    if plan.time_range is not None:
        tables.append(plan.time_range.column.table)
    return list(dict.fromkeys(tables))


def _join_order(tables: list[str], catalog: SchemaCatalog, profile: SchemaProfile) -> list[str]:
    base = next((t for t in profile.fact_tables if t in tables), tables[0] if tables else "")
    ordered = [base]
    for table in tables:
        if table == base:
            continue
        path = catalog.fk_path((base, table))
        for step in path or (table,):
            if step not in ordered:
                ordered.append(step)
    return ordered


def compile_plan(plan: QueryPlan, catalog: SchemaCatalog, profile: SchemaProfile | None = None) -> CompiledSQL:
    profile = profile or SchemaProfile.discover(catalog)
    tables = _involved_tables(plan, profile)
    if not tables:
        if not plan.metrics:
            raise ValueError("Cannot compile an empty plan")
        tables = [profile.fact_tables[0] if profile.fact_tables else catalog.tables[0]]

    select: list[str] = []
    group_by: list[str] = []
    dimension_exprs: dict[str, str] = {}
    for index, dim in enumerate(plan.dimensions):
        expr = colref_sql(dim)
        is_time_dim = plan.time_range is not None and dim == plan.time_range.column
        if plan.time_grain and is_time_dim:
            expr = _grain_sql(plan.time_grain, expr)
        alias = f"dim_{index}"
        dimension_exprs[dim.key] = quote(alias)
        select.append(f"{expr} AS {quote(alias)}")
        group_by.append(expr)

    for metric in plan.metrics:
        expr = source_sql(metric.source, profile)
        distinct = "DISTINCT " if metric.distinct else ""
        select.append(f"{metric.agg.value}({distinct}{expr}) AS {quote(metric.alias)}")

    if not select:
        raise ValueError("Cannot compile a plan with no selectable expressions")

    ordered = _join_order(tables, catalog, profile)
    joined = [ordered[0]]
    from_clause = f"FROM {quote(ordered[0])}"
    for table in ordered[1:]:
        condition = None
        for child, child_col, parent, parent_col in catalog.foreign_keys:
            if child == table and parent in joined:
                condition = (child, child_col, parent, parent_col)
                break
            if parent == table and child in joined:
                condition = (child, child_col, parent, parent_col)
                break
        if condition is None:
            raise ValueError(f"No join condition for {table}")
        child, child_col, parent, parent_col = condition
        from_clause += (
            f" JOIN {quote(table)} ON {quote(child)}.{quote(child_col)} "
            f"= {quote(parent)}.{quote(parent_col)}"
        )
        joined.append(table)

    params: list[Any] = []
    where: list[str] = []
    if plan.time_range is not None:
        where.append(f"{colref_sql(plan.time_range.column)} BETWEEN ? AND ?")
        params.extend([plan.time_range.start, plan.time_range.end])
    for flt in plan.filters:
        column = colref_sql(flt.column)
        if flt.op is FilterOp.IN:
            values = list(flt.value)
            where.append(f"{column} IN ({', '.join('?' for _ in values)})")
            params.extend(values)
        elif flt.op is FilterOp.BETWEEN:
            where.append(f"{column} BETWEEN ? AND ?")
            params.extend([flt.value, flt.value2])
        else:
            where.append(f"{column} {flt.op.value} ?")
            params.append(flt.value)
    if where:
        from_clause += " WHERE " + " AND ".join(where)

    prefix = "SELECT DISTINCT " if not plan.metrics and plan.dimensions else "SELECT "
    sql = prefix + ", ".join(select) + " " + from_clause
    if group_by and plan.metrics:
        sql += " GROUP BY " + ", ".join(group_by)

    if plan.time_grain and plan.dimensions:
        time_alias = dimension_exprs.get(plan.time_range.column.key) if plan.time_range else None
        if time_alias:
            sql += f" ORDER BY {time_alias} ASC"
    elif plan.order_by:
        terms = []
        for term in plan.order_by:
            name = term.metric_alias or (dimension_exprs.get(term.column.key) if term.column else None)
            if name:
                terms.append(f"{quote(name)} {'DESC' if term.descending else 'ASC'}")
        if terms:
            sql += " ORDER BY " + ", ".join(terms)
    elif plan.dimensions and not plan.metrics:
        sql += f" ORDER BY {quote('dim_0')} ASC"

    if plan.limit is not None:
        sql += " LIMIT ?"
        params.append(plan.limit)

    return CompiledSQL(sql, tuple(params))
