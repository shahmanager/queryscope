"""Read-only, resource-limited execution with a cost estimate."""

from __future__ import annotations

import sqlite3
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .compiler import CompiledSQL


@dataclass(frozen=True)
class ExecutionResult:
    columns: tuple[str, ...]
    rows: tuple[tuple[Any, ...], ...]
    estimated_cost: float
    latency_ms: float


def _uri(path: Path) -> str:
    return f"file:{path.as_posix()}?mode=ro"


def execute(
    db_path: Path,
    compiled: CompiledSQL,
    max_rows: int = 200,
    timeout_ms: int = 1000,
) -> ExecutionResult:
    started = time.perf_counter()
    conn = sqlite3.connect(_uri(db_path), uri=True)
    try:
        conn.execute("PRAGMA query_only=ON")
        deadline = started + timeout_ms / 1000.0

        def _guard() -> int:
            return 1 if time.perf_counter() > deadline else 0

        conn.set_progress_handler(_guard, 10_000)

        sql, params = compiled.sql, compiled.params
        if "LIMIT" not in sql.upper():
            sql += " LIMIT ?"
            params = (*params, max_rows)
        cursor = conn.execute(sql, params)
        columns = tuple(description[0] for description in cursor.description)
        rows = tuple(tuple(row) for row in cursor.fetchmany(max_rows))

        explained = conn.execute(
            "EXPLAIN QUERY PLAN " + compiled.sql, compiled.params
        ).fetchall()
        detail = " ".join(str(row[3]) for row in explained).upper()
        scans, searches, temps = detail.count("SCAN"), detail.count("SEARCH"), detail.count("TEMP")
        estimated_cost = float(scans * 100 + searches * 10 + temps * 50)
        return ExecutionResult(columns, rows, estimated_cost, (time.perf_counter() - started) * 1000)
    finally:
        conn.set_progress_handler(None, 0)
        conn.close()
