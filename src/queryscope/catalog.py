"""Schema introspection. The compiler knows only what the catalog tells it."""

from __future__ import annotations

import sqlite3
from collections import deque
from dataclasses import dataclass
from typing import Iterable


def _affinity(declared: str) -> str:
    d = declared.upper()
    if "INT" in d:
        return "INT"
    if any(x in d for x in ("REAL", "FLOA", "DOUB", "NUM", "DEC")):
        return "REAL"
    if "DATE" in d or "TIME" in d:
        return "DATE"
    return "TEXT"


@dataclass
class ColumnInfo:
    table: str
    name: str
    affinity: str
    is_pk: bool = False
    is_fk: bool = False

    @property
    def key(self) -> str:
        return f"{self.table}.{self.name}"


class SchemaCatalog:
    def __init__(
        self,
        columns: dict[str, tuple[ColumnInfo, ...]],
        fks: tuple[tuple[str, str, str, str], ...],
        row_counts: dict[str, int],
    ) -> None:
        self._columns = columns
        self._fks = fks
        self.row_counts = row_counts
        self._adjacency: dict[str, set[str]] = {t: set() for t in columns}
        for child, _cc, parent, _pc in fks:
            if child in self._adjacency and parent in self._adjacency:
                self._adjacency[child].add(parent)
                self._adjacency[parent].add(child)

    @classmethod
    def from_connection(cls, conn: sqlite3.Connection) -> "SchemaCatalog":
        names = [
            r[0] for r in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' "
                "AND name NOT LIKE 'sqlite_%' ORDER BY name"
            )
        ]
        columns: dict[str, tuple[ColumnInfo, ...]] = {}
        all_fks: list[tuple[str, str, str, str]] = []
        row_counts: dict[str, int] = {}
        for table in names:
            quoted = '"' + table.replace('"', '""') + '"'
            fk_rows = list(conn.execute(f"PRAGMA foreign_key_list({quoted})"))
            fk_cols = {r[3] for r in fk_rows}
            cols: list[ColumnInfo] = []
            for row in conn.execute(f"PRAGMA table_info({quoted})"):
                _cid, name, declared, _notnull, _default, pk = row
                cols.append(ColumnInfo(table, name, _affinity(declared), bool(pk), name in fk_cols))
            columns[table] = tuple(cols)
            for r in fk_rows:
                all_fks.append((table, r[3], r[2], r[4]))
            row_counts[table] = conn.execute(f"SELECT COUNT(*) FROM {quoted}").fetchone()[0]
        return cls(columns, tuple(all_fks), row_counts)

    @property
    def tables(self) -> tuple[str, ...]:
        return tuple(self._columns)

    def column(self, key: str) -> ColumnInfo:
        table, _, name = key.partition(".")
        for col in self._columns.get(table, ()):
            if col.name == name:
                return col
        raise KeyError(f"Unknown column: {key}")

    def has_column(self, key: str) -> bool:
        try:
            self.column(key)
            return True
        except KeyError:
            return False

    def columns_for(self, table: str) -> tuple[ColumnInfo, ...]:
        return self._columns.get(table, ())

    def fk_path(self, tables: Iterable[str]) -> tuple[str, ...] | None:
        """Shortest path connecting the given tables in the FK graph."""
        wanted = list(dict.fromkeys(t for t in tables if t in self._adjacency))
        if len(wanted) < 2:
            return tuple(wanted)
        path: list[str] = []
        current = wanted[0]
        for target in wanted[1:]:
            segment = self._between(current, target)
            if segment is None:
                return None
            path.extend(segment if not path else segment[1:])
            current = target
        return tuple(path)

    def _between(self, source: str, target: str) -> tuple[str, ...] | None:
        if source == target:
            return (source,)
        queue: deque[tuple[str, list[str]]] = deque([(source, [source])])
        seen = {source}
        while queue:
            node, path = queue.popleft()
            for neighbour in sorted(self._adjacency.get(node, ())):
                if neighbour == target:
                    return tuple(path + [neighbour])
                if neighbour not in seen:
                    seen.add(neighbour)
                    queue.append((neighbour, path + [neighbour]))
        return None
