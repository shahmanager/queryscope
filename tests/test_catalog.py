import sqlite3
from pathlib import Path

from queryscope.catalog import SchemaCatalog

DB = Path(__file__).resolve().parents[1] / "data" / "northwind.sqlite"


def catalog() -> SchemaCatalog:
    conn = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
    try:
        return SchemaCatalog.from_connection(conn)
    finally:
        conn.close()


def test_introspects_all_tables() -> None:
    cat = catalog()
    assert len(cat.tables) == 8
    assert "order_items" in cat.tables


def test_pk_and_fk_flags() -> None:
    cat = catalog()
    assert cat.column("orders.order_id").is_pk
    assert cat.column("orders.customer_id").is_fk
    assert not cat.column("orders.freight").is_pk


def test_fk_path_between_related_tables() -> None:
    cat = catalog()
    path = cat.fk_path(("customers", "orders"))
    assert path is not None
    assert set(path) == {"customers", "orders"}


def test_fk_path_through_intermediate_table() -> None:
    cat = catalog()
    path = cat.fk_path(("customers", "products"))
    assert path is not None
    assert "orders" in path or "order_items" in path


def test_row_counts_populated() -> None:
    cat = catalog()
    assert cat.row_counts["orders"] == 300
    assert cat.row_counts["order_items"] > 300
