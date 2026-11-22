"""Composable intent families.

A family describes a *shape* of question and the slots it accepts. It is not
one template per question — the planner composes metrics, dimensions,
filters, time and rank slots into a plan.
"""

from __future__ import annotations

from dataclasses import dataclass

from .models import IntentFamily

EXAMPLES: dict[IntentFamily, tuple[str, ...]] = {
    IntentFamily.LOOKUP: (
        "show customers in Germany",
        "list products in the Beverages category",
        "which stores are in Canada",
        "show employees and their countries",
        "list all discontinued products",
        "show orders with status Shipped",
    ),
    IntentFamily.AGGREGATE: (
        "total revenue by country",
        "how many orders are there",
        "average salary of employees",
        "sum of quantity by product",
        "how many customers per segment",
        "total freight by store",
        "average unit price by category",
    ),
    IntentFamily.TREND: (
        "revenue over time by month",
        "total revenue last quarter",
        "monthly orders this year",
        "revenue trend by quarter",
        "how many orders last month by country",
        "average order value year to date",
    ),
    IntentFamily.TOP_N: (
        "top 5 products by revenue",
        "top 10 customers by number of orders",
        "best 3 stores by revenue",
        "top 5 employees by salary",
        "products with highest unit price top 8",
        "bottom 5 products by quantity",
    ),
    IntentFamily.COMPARISON: (
        "compare revenue in USA and UK",
        "revenue by country",
        "compare number of orders between stores",
        "sales by category and country",
        "compare salaries by country",
    ),
    IntentFamily.DISTRIBUTION: (
        "distribution of customers by segment",
        "breakdown of orders by status",
        "how many products by category",
        "count of employees per country",
        "distribution of revenue by category",
    ),
    IntentFamily.JOIN_LOOKUP: (
        "which customers ordered product 7",
        "show orders and the products in them",
        "employees who work in stores in the USA",
        "products supplied by vendors in Germany",
        "orders placed by clients in France",
    ),
    IntentFamily.OUT_OF_SCOPE: (
        "delete all orders",
        "drop the customers table",
        "update product prices",
        "what is the weather today",
        "write a poem about sales",
        "send an email to customers",
    ),
}

DESCRIPTIONS: dict[IntentFamily, str] = {
    IntentFamily.LOOKUP: "Return rows with selected attributes and optional filters.",
    IntentFamily.AGGREGATE: "Compute one or more aggregates, optionally grouped.",
    IntentFamily.TREND: "Aggregate over a resolved time range at a chosen grain.",
    IntentFamily.TOP_N: "Rank a metric and keep the top N rows.",
    IntentFamily.COMPARISON: "Group a metric by a dimension to compare segments.",
    IntentFamily.DISTRIBUTION: "Count or aggregate rows across a categorical dimension.",
    IntentFamily.JOIN_LOOKUP: "Return attributes spanning multiple related tables.",
    IntentFamily.OUT_OF_SCOPE: "Request cannot be safely expressed by this system.",
}


@dataclass(frozen=True)
class IntentSkeleton:
    family: IntentFamily
    description: str
    examples: tuple[str, ...]

    @property
    def allows_metric(self) -> bool:
        return self.family not in (IntentFamily.LOOKUP, IntentFamily.JOIN_LOOKUP, IntentFamily.OUT_OF_SCOPE)

    @property
    def allows_grouping(self) -> bool:
        return self.family in (
            IntentFamily.AGGREGATE, IntentFamily.TREND, IntentFamily.TOP_N,
            IntentFamily.COMPARISON, IntentFamily.DISTRIBUTION,
        )

    @property
    def requires_time(self) -> bool:
        return self.family is IntentFamily.TREND

    @property
    def allows_limit(self) -> bool:
        return self.family in (IntentFamily.TOP_N, IntentFamily.LOOKUP, IntentFamily.JOIN_LOOKUP)


class IntentCatalog:
    def __init__(self) -> None:
        self._skeletons = {
            family: IntentSkeleton(family, DESCRIPTIONS[family], examples)
            for family, examples in EXAMPLES.items()
        }

    @property
    def families(self) -> tuple[IntentFamily, ...]:
        return tuple(self._skeletons)

    def skeleton(self, family: IntentFamily) -> IntentSkeleton:
        return self._skeletons[family]

    def examples(self, family: IntentFamily) -> tuple[str, ...]:
        return self._skeletons[family].examples

    def pairs(self) -> tuple[tuple[IntentFamily, str], ...]:
        return tuple(
            (family, example)
            for family in self.families
            for example in self.examples(family)
        )
