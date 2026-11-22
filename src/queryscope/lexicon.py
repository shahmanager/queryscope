"""Business vocabulary. Maps ordinary words to canonical, typed tokens.

Schema-independent grammar stays here. Every reference to a table or column
comes from SchemaProfile, which is discovered from the connected database at
runtime. No table or column name is hardcoded.
"""

from __future__ import annotations

import re
from typing import Iterable

from .catalog import SchemaCatalog
from .schema_profile import SchemaProfile

_TOKEN_RE = re.compile(r"[a-z0-9_]+")

# Grammar only — these tokens mean the same thing for every schema.
GRAMMAR_SYNONYMS: dict[str, tuple[str, ...]] = {
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
    "revenue": ("measure:line_revenue",),
    "sales": ("measure:line_revenue",),
    "turnover": ("measure:line_revenue",),
    "income": ("measure:line_revenue",),
    "quantity": ("measure:line_quantity",),
    "quantities": ("measure:line_quantity",),
    "units": ("measure:line_quantity",),
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
    def __init__(
        self,
        catalog: SchemaCatalog | None = None,
        profile: SchemaProfile | None = None,
    ) -> None:
        self.profile = profile or (SchemaProfile.discover(catalog) if catalog else None)
        self._synonyms = {key: tuple(value) for key, value in GRAMMAR_SYNONYMS.items()}
        self.phrases = dict(PHRASES)
        if self.profile:
            for word, canonicals in self.profile.column_aliases.items():
                self._merge(word, canonicals)
            for word, canonicals in self.profile.table_aliases.items():
                self._merge(word, canonicals)
            if self.profile.time_column:
                self._merge("date", (f"column:{self.profile.time_column.key}",))
        if catalog is not None and self.profile is None:
            for table in catalog.tables:
                self._merge(table, (f"table:{table}",))

    def _merge(self, word: str, canonicals: Iterable[str]) -> None:
        existing = set(self._synonyms.get(word, ()))
        self._synonyms[word] = tuple(sorted(existing | set(canonicals)))

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
