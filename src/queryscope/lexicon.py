"""Business vocabulary. Maps ordinary words to canonical, typed tokens.

This is the only place where free text is interpreted. Its output is a
closed vocabulary, so nothing downstream ever sees raw user text.
"""

from __future__ import annotations

import re
from typing import Iterable

from .catalog import SchemaCatalog

_TOKEN_RE = re.compile(r"[a-z0-9_]+")

BASE_SYNONYMS: dict[str, tuple[str, ...]] = {
    # measures
    "revenue": ("measure:line_revenue",),
    "sales": ("measure:line_revenue",),
    "turnover": ("measure:line_revenue",),
    "income": ("measure:line_revenue",),
    "quantity": ("measure:line_quantity", "column:order_items.quantity"),
    "quantities": ("measure:line_quantity",),
    "units": ("measure:line_quantity",),
    "freight": ("column:orders.freight",),
    "shipping": ("column:orders.freight",),
    "salary": ("column:employees.salary",),
    "pay": ("column:employees.salary",),
    "price": ("column:products.unit_price",),
    "prices": ("column:products.unit_price",),
    # aggregations
    "total": ("agg:sum",),
    "sum": ("agg:sum",),
    "summed": ("agg:sum",),
    "average": ("agg:avg",),
    "avg": ("agg:avg",),
    "mean": ("agg:avg",),
    "count": ("agg:count",),
    "how": ("agg:count",),
    "many": ("agg:count",),
    "much": ("agg:count",),
    "number": ("agg:count",),
    "highest": ("agg:max", "rank:desc"),
    "maximum": ("agg:max", "rank:desc"),
    "lowest": ("agg:min", "rank:asc"),
    "minimum": ("agg:min", "rank:asc"),
    # entities
    "customers": ("table:customers",),
    "customer": ("table:customers",),
    "clients": ("table:customers",),
    "accounts": ("table:customers",),
    "orders": ("table:orders",),
    "order": ("table:orders",),
    "purchases": ("table:orders",),
    "products": ("table:products",),
    "product": ("table:products",),
    "items": ("table:products",),
    "skus": ("table:products",),
    "employees": ("table:employees",),
    "reps": ("table:employees",),
    "salespeople": ("table:employees",),
    "stores": ("table:stores",),
    "branches": ("table:stores",),
    "categories": ("table:categories",),
    "suppliers": ("table:suppliers",),
    "vendors": ("table:suppliers",),
    "country": ("column:customers.country",),
    "countries": ("column:customers.country",),
    "region": ("column:customers.country",),
    "market": ("column:customers.country",),
    "city": ("column:customers.city",),
    "segment": ("column:customers.segment",),
    "category": ("column:categories.category_name",),
    "status": ("column:orders.status",),
    "discontinued": ("column:products.discontinued",),
    "stock": ("column:products.units_in_stock",),
    "inventory": ("column:products.units_in_stock",),
    # ranking / shape
    "top": ("rank:desc", "shape:top_n"),
    "best": ("rank:desc", "shape:top_n"),
    "most": ("rank:desc", "shape:top_n"),
    "bottom": ("rank:asc", "shape:top_n"),
    "worst": ("rank:asc", "shape:top_n"),
    "last": ("rank:desc",),
    "first": ("rank:asc",),
    "list": ("shape:lookup",),
    "show": ("shape:lookup",),
    "which": ("shape:lookup",),
    "compare": ("shape:comparison",),
    "comparison": ("shape:comparison",),
    "versus": ("shape:comparison",),
    "trend": ("shape:trend",),
    "monthly": ("grain:month", "shape:trend"),
    "quarterly": ("grain:quarter", "shape:trend"),
    "yearly": ("grain:year", "shape:trend"),
    "annually": ("grain:year", "shape:trend"),
    "distribution": ("shape:distribution",),
    "breakdown": ("shape:distribution",),
}

PHRASES: dict[str, tuple[str, ...]] = {
    "last quarter": ("time:last_quarter", "shape:trend"),
    "this quarter": ("time:this_quarter", "shape:trend"),
    "last month": ("time:last_month", "shape:trend"),
    "this month": ("time:this_month", "shape:trend"),
    "last year": ("time:last_year", "shape:trend"),
    "this year": ("time:this_year", "shape:trend"),
    "year to date": ("time:ytd", "shape:trend"),
    "ytd": ("time:ytd", "shape:trend"),
    "over time": ("shape:trend",),
    "by month": ("grain:month", "shape:trend"),
    "by quarter": ("grain:quarter", "shape:trend"),
    "by year": ("grain:year", "shape:trend"),
}


def tokenize(text: str) -> tuple[str, ...]:
    """Lowercase and split on non-alphanumerics, keeping word order."""
    return tuple(_TOKEN_RE.findall(text.lower()))


class Lexicon:
    def __init__(self, catalog: SchemaCatalog | None = None) -> None:
        self._synonyms = {key: tuple(value) for key, value in BASE_SYNONYMS.items()}
        self.phrases = dict(PHRASES)
        if catalog is not None:
            counts: dict[str, int] = {}
            for table in catalog.tables:
                for col in catalog.columns_for(table):
                    counts[col.name] = counts.get(col.name, 0) + 1
            for table in catalog.tables:
                self._synonyms[table] = tuple(
                    set(self._synonyms.get(table, ()) + (f"table:{table}",))
                )
                for col in catalog.columns_for(table):
                    if counts[col.name] > 1:
                        continue  # ambiguous bare name; base synonyms decide scope
                    self._synonyms.setdefault(col.name, ())
                    self._synonyms[col.name] = tuple(
                        set(self._synonyms[col.name] + (f"column:{col.key}",))
                    )

    def canonicals(self, token: str) -> tuple[str, ...]:
        return self._synonyms.get(token.lower(), ())

    def canonical_tokens(self, tokens: Iterable[str]) -> tuple[str, ...]:
        out: list[str] = []
        for token in tokens:
            for canonical in self.canonicals(token):
                if canonical not in out:
                    out.append(canonical)
        return tuple(out)

    def phrase_tokens(self, text: str) -> tuple[str, ...]:
        lowered = " " + re.sub(r"[^a-z0-9_]+", " ", text.lower()) + " "
        out: list[str] = []
        for phrase, tokens in self.phrases.items():
            if f" {phrase} " in lowered:
                out.extend(tokens)
        return tuple(out)
