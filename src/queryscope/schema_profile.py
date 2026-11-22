"""Runtime schema discovery — the replacement for hardcoded table/column knowledge.

Everything here is derived from SQLite introspection and (optionally) a sample
of the data. No table or column name is assumed. The profile answers the
questions the planner and compiler used to answer with literals:

  - which table is the fact table?
  - which column is the date dimension?
  - which column is the human-readable label of each table?
  - which columns can be filtered by their observed values?
  - which numeric columns are measures?
  - how is a "revenue" measure computed from this schema?
"""

from __future__ import annotations

import re
import sqlite3
from dataclasses import dataclass, field
from typing import Mapping

from .catalog import SchemaCatalog
from .models import ColumnRef

NAME_HINTS = ("name", "title", "label", "description")
TIME_HINTS = ("date", "time", "year", "month", "period", "on", "at", "when")

COLUMN_CONCEPTS: dict[str, tuple[str, ...]] = {
    "revenue": ("revenue", "sales", "amount", "total", "turnover", "income", "charge"),
    "quantity": ("quantity", "qty", "units", "volume"),
    "price": ("price", "rate", "cost"),
    "salary": ("salary", "pay", "wage", "compensation"),
    "freight": ("freight", "shipping"),
    "discount": ("discount",),
    "profit": ("profit", "margin"),
    "stock": ("stock", "inventory"),
    "discontinued": ("discontinued", "retired"),
    "country": ("country", "nation"),
    "region": ("region", "market", "territory"),
    "city": ("city", "town"),
    "segment": ("segment", "tier"),
    "category": ("category", "cat", "group"),
    "status": ("status", "state"),
    "department": ("department", "dept"),
    "patient": ("patient", "subject"),
    "provider": ("provider", "doctor", "physician", "clinician"),
}

TABLE_SYNONYMS: dict[str, tuple[str, ...]] = {
    "customers": ("customer", "client", "account"),
    "orders": ("order", "purchase", "transaction"),
    "products": ("product", "item", "sku"),
    "employees": ("employee", "rep", "provider"),
    "stores": ("store", "branch", "location"),
    "categories": ("category", "cat", "group"),
    "suppliers": ("supplier", "vendor"),
    "clients": ("customer", "client", "account"),
    "account": ("customer", "client", "account"),
    "purchases": ("order", "purchase", "transaction"),
    "transactions": ("order", "purchase", "transaction"),
    "items": ("product", "item", "sku"),
    "skus": ("product", "item", "sku"),
    "branches": ("store", "branch", "location", "facility"),
    "vendors": ("supplier", "vendor"),
    "reps": ("employee", "rep", "provider"),
    "salespeople": ("employee", "rep", "provider"),
    "admissions": ("admission", "encounter", "visit"),
    "diagnoses": ("diagnosis", "diagnoses", "condition"),
    "procedures": ("procedure", "service", "treatment"),
}

TABLE_WORDS = tuple(sorted({w for patterns in TABLE_SYNONYMS.values() for w in patterns}))


def _quote(value: str) -> str:
    return '"' + value.replace('"', '""') + '"'


def _is_name(column_name: str) -> bool:
    return any(hint in column_name.lower() for hint in NAME_HINTS)


def _is_time(column_name: str, affinity: str) -> bool:
    if affinity == "DATE":
        return True
    lowered = column_name.lower()
    if any(hint in lowered for hint in ("date", "time")):
        return True
    tokens = set(re.split(r"[^a-z0-9]+", lowered))
    return bool(tokens & set(TIME_HINTS))


@dataclass(frozen=True)
class SchemaProfile:
    fact_tables: tuple[str, ...]
    time_column: ColumnRef | None
    dimensions: Mapping[str, str]
    numeric_columns: frozenset[str]
    categorical_values: Mapping[str, tuple[str, ...]]
    revenue_expr: str
    revenue_tables: tuple[str, ...]
    quantity_expr: str
    quantity_tables: tuple[str, ...]
    column_aliases: Mapping[str, tuple[str, ...]]
    table_aliases: Mapping[str, tuple[str, ...]]

    def preferred_dimension(self, table: str) -> str | None:
        return self.dimensions.get(table)

    def is_fact(self, table: str) -> bool:
        return table in self.fact_tables

    @classmethod
    def discover(cls, catalog: SchemaCatalog, conn: sqlite3.Connection | None = None) -> "SchemaProfile":
        tables = catalog.tables
        outbound = {t: 0 for t in tables}
        inbound = {t: 0 for t in tables}
        for child, _cc, parent, _pc in catalog.foreign_keys:
            outbound[child] = outbound.get(child, 0) + 1
            inbound[parent] = inbound.get(parent, 0) + 1
        import math

        def fact_score(table: str) -> float:
            rows = catalog.row_counts.get(table, 0)
            return (outbound[table] + 1) * math.log1p(rows) + outbound[table] * 0.1

        fact_tables = tuple(sorted(tables, key=fact_score, reverse=True)[:2])

        time_candidates = [
            col for table in tables for col in catalog.columns_for(table)
            if _is_time(col.name, col.affinity)
        ]
        time_column = None
        if time_candidates:
            best = max(
                time_candidates,
                key=lambda c: (
                    c.table in fact_tables,
                    c.affinity == "DATE",
                    catalog.row_counts.get(c.table, 0),
                ),
            )
            time_column = ColumnRef(best.table, best.name)

        dimensions: dict[str, str] = {}
        for table in tables:
            candidates = [
                c for c in catalog.columns_for(table)
                if c.affinity == "TEXT" and not c.is_pk and not c.is_fk
                and not _is_time(c.name, c.affinity)
                and not (time_column and ColumnRef(table, c.name) == time_column)
            ]
            named = [c for c in candidates if _is_name(c.name)]
            if named:
                dimensions[table] = named[0].name
            elif candidates:
                dimensions[table] = candidates[0].name

        numeric_columns = frozenset(
            col.key for table in tables for col in catalog.columns_for(table)
            if col.affinity in ("INT", "REAL") and not col.is_pk and not col.is_fk
        )

        categorical_values: dict[str, tuple[str, ...]] = {}
        if conn is not None:
            for table in tables:
                for col in catalog.columns_for(table):
                    if col.affinity != "TEXT" or col.is_pk or _is_name(col.name):
                        continue
                    if time_column and ColumnRef(table, col.name) == time_column:
                        continue
                    try:
                        rows = conn.execute(
                            f"SELECT DISTINCT {_quote(col.name)} FROM {_quote(table)} "
                            f"WHERE {_quote(col.name)} IS NOT NULL LIMIT 41"
                        ).fetchall()
                    except sqlite3.Error:
                        continue
                    values = tuple(sorted(str(r[0]) for r in rows if len(str(r[0])) <= 60))
                    if 1 <= len(values) <= 40:
                        categorical_values[col.key] = values

        def find_numeric(concepts: tuple[str, ...]) -> ColumnRef | None:
            for table in (*fact_tables, *tables):
                for col in catalog.columns_for(table):
                    if col.key not in numeric_columns:
                        continue
                    if any(pattern in col.name.lower() for pattern in concepts):
                        return ColumnRef(table, col.name)
            return None

        revenue_col = find_numeric(COLUMN_CONCEPTS["revenue"])
        if revenue_col:
            revenue_expr = f'{_quote(revenue_col.table)}.{_quote(revenue_col.column)}'
            revenue_tables = (revenue_col.table,)
        else:
            qty = find_numeric(COLUMN_CONCEPTS["quantity"])
            price = find_numeric(COLUMN_CONCEPTS["price"])
            discount = find_numeric(COLUMN_CONCEPTS["discount"])
            if qty and price and qty.table == price.table:
                expr = f'{_quote(qty.table)}.{_quote(qty.column)} * {_quote(price.table)}.{_quote(price.column)}'
                if discount and discount.table == qty.table:
                    expr += f' * (1 - {_quote(discount.table)}.{_quote(discount.column)})'
                revenue_expr = f"({expr})"
                revenue_tables = (qty.table,)
            else:
                revenue_expr, revenue_tables = "1", ()

        quantity_col = find_numeric(COLUMN_CONCEPTS["quantity"])
        if quantity_col:
            quantity_expr = f'{_quote(quantity_col.table)}.{_quote(quantity_col.column)}'
            quantity_tables = (quantity_col.table,)
        else:
            quantity_expr, quantity_tables = "1", ()

        column_aliases: dict[str, set[str]] = {}
        for table in tables:
            for col in catalog.columns_for(table):
                key = col.key
                name = col.name.lower()
                words = {name, name.replace("_", "")}
                words.update(part for part in name.split("_") if len(part) > 2)
                if name.endswith("_id"):
                    words.add(name[:-3])
                for concept, patterns in COLUMN_CONCEPTS.items():
                    if any(pattern in name for pattern in patterns):
                        words.add(concept)
                        if concept == "revenue":
                            words.add("sales")
                            words.add("turnover")
                        if concept == "quantity":
                            words.add("units")
                for word in words:
                    column_aliases.setdefault(word, set()).add(f"column:{key}")
                if _is_name(name):
                    column_aliases.setdefault(name.replace("_id", ""), set()).add(f"column:{key}")

        table_aliases: dict[str, set[str]] = {}

        def add_table_alias(word: str, table: str) -> None:
            table_aliases.setdefault(word, set()).add(f"table:{table}")

        def plural_forms(word: str) -> set[str]:
            forms = {word, word + "s", word + "es"}
            if word.endswith("y"):
                forms.add(word[:-1] + "ies")
            return forms

        for table in tables:
            lower = table.lower()
            add_table_alias(table, table)
            if lower.endswith("s"):
                add_table_alias(lower[:-1], table)
            # Concept aliases only when the whole table name is the concept,
            # never for compound names like order_items or product_reviews.
            for word in TABLE_WORDS:
                if lower in plural_forms(word):
                    add_table_alias(word, table)
                    add_table_alias(word + "s", table)
            for word, patterns in TABLE_SYNONYMS.items():
                if any(lower in plural_forms(pattern) for pattern in patterns):
                    add_table_alias(word, table)
                    if word.endswith("s"):
                        add_table_alias(word[:-1], table)

        return cls(
            fact_tables=fact_tables,
            time_column=time_column,
            dimensions=dimensions,
            numeric_columns=numeric_columns,
            categorical_values=categorical_values,
            revenue_expr=revenue_expr,
            revenue_tables=revenue_tables,
            quantity_expr=quantity_expr,
            quantity_tables=quantity_tables,
            column_aliases={k: tuple(sorted(v)) for k, v in column_aliases.items()},
            table_aliases={k: tuple(sorted(v)) for k, v in table_aliases.items()},
        )
