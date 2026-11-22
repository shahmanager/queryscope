import sqlite3
from datetime import datetime
from pathlib import Path

from queryscope.catalog import SchemaCatalog
from queryscope.intents import IntentCatalog
from queryscope.lexicon import Lexicon
from queryscope.models import Agg, ColumnRef, DerivedSource, IntentFamily
from queryscope.planner import build_plan
from queryscope.retrieval import IntentMatch

DB = Path(__file__).resolve().parents[1] / "data" / "northwind.sqlite"
NOW = datetime(2026, 6, 30)


def catalog() -> SchemaCatalog:
    conn = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
    try:
        return SchemaCatalog.from_connection(conn)
    finally:
        conn.close()


def plan_for(question: str, family: IntentFamily, alternatives=()):
    cat = catalog()
    return build_plan(question, family, Lexicon(cat), cat, NOW, alternatives)


def test_revenue_by_country_last_quarter() -> None:
    result = plan_for("total revenue by country last quarter", IntentFamily.TREND)
    assert result.plan is not None
    assert result.plan.metrics[0].agg is Agg.SUM
    assert result.plan.metrics[0].source is DerivedSource.LINE_REVENUE
    assert ColumnRef("customers", "country") in result.plan.dimensions
    assert result.plan.time_range is not None
    assert result.plan.time_range.start == "2026-01-01"
    assert result.plan.time_range.end == "2026-03-31"


def test_top_n_products_by_quantity() -> None:
    result = plan_for("top 5 products by quantity", IntentFamily.TOP_N)
    assert result.plan is not None
    assert result.plan.limit == 5
    assert result.plan.order_by[0].descending
    assert ColumnRef("products", "product_name") in result.plan.dimensions
    assert result.plan.metrics[0].source is DerivedSource.LINE_QUANTITY


def test_tied_families_produce_clarification() -> None:
    alternatives = (
        IntentMatch(IntentFamily.AGGREGATE, 0.6, 1),
        IntentMatch(IntentFamily.TREND, 0.59, 2),
    )
    result = plan_for("what about the thing?", IntentFamily.AGGREGATE, alternatives)
    assert result.plan is None
    assert len(result.interpretations) == 2
