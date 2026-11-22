import sqlite3
from pathlib import Path

import pytest

from queryscope.catalog import SchemaCatalog
from queryscope.compiler import compile_plan
from queryscope.models import (
    Agg, ColumnRef, DerivedSource, Filter, FilterOp, IntentFamily, Metric, QueryPlan,
)
from queryscope.validation import validate

DB = Path(__file__).resolve().parents[1] / "data" / "northwind.sqlite"


def catalog() -> SchemaCatalog:
    conn = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
    try:
        return SchemaCatalog.from_connection(conn)
    finally:
        conn.close()


def test_sum_on_text_column_is_rejected() -> None:
    plan = QueryPlan(
        family=IntentFamily.AGGREGATE,
        metrics=(Metric(Agg.SUM, ColumnRef("customers", "company_name")),),
    )
    codes = {d.code for d in validate(plan, catalog())}
    assert "BAD_AGGREGATION" in codes


def test_valid_plan_compiles_with_bound_params() -> None:
    plan = QueryPlan(
        family=IntentFamily.AGGREGATE,
        metrics=(Metric(Agg.SUM, DerivedSource.LINE_REVENUE),),
        dimensions=(ColumnRef("customers", "country"),),
        filters=(Filter(ColumnRef("customers", "country"), FilterOp.EQ, "USA"),),
    )
    compiled = compile_plan(plan, catalog())
    assert "SUM(" in compiled.sql
    assert "?" in compiled.sql
    assert compiled.params == ("USA",)
    assert "JOIN" in compiled.sql


def test_injection_attempt_is_a_bound_parameter() -> None:
    payload = "'; DROP TABLE orders; --"
    plan = QueryPlan(
        family=IntentFamily.LOOKUP,
        dimensions=(ColumnRef("customers", "company_name"),),
        filters=(Filter(ColumnRef("customers", "country"), FilterOp.EQ, payload),),
    )
    compiled = compile_plan(plan, catalog())
    assert payload not in compiled.sql
    assert payload in compiled.params


def test_multi_hop_join_compiles_without_diagnostics() -> None:
    plan = QueryPlan(
        family=IntentFamily.LOOKUP,
        dimensions=(ColumnRef("customers", "company_name"), ColumnRef("suppliers", "company_name")),
    )
    cat = catalog()
    assert validate(plan, cat) == ()
    compiled = compile_plan(plan, cat)
    assert compiled.sql.count("JOIN") >= 3


def test_compiled_sql_executes() -> None:
    plan = QueryPlan(
        family=IntentFamily.AGGREGATE,
        metrics=(Metric(Agg.COUNT, None),),
        filters=(Filter(ColumnRef("orders", "status"), FilterOp.EQ, "Shipped"),),
    )
    compiled = compile_plan(plan, catalog())
    conn = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
    try:
        rows = conn.execute(compiled.sql, compiled.params).fetchall()
    finally:
        conn.close()
    assert rows and rows[0][0] > 0
