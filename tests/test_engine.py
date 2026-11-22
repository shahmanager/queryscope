from datetime import datetime

from queryscope.engine import Engine

NOW = datetime(2026, 6, 30)


def engine() -> Engine:
    return Engine(now=NOW)


def test_simple_count_is_answered() -> None:
    answer = engine().ask("how many orders are there")
    assert answer.status == "answered"
    assert answer.rows and answer.rows[0][0] > 0
    assert "DROP" not in answer.sql.upper()
    assert answer.sql.upper().startswith("SELECT")


def test_nonsense_question_does_not_guess() -> None:
    answer = engine().ask("purple bicycle accordion whisper")
    assert answer.status in ("needs_clarification", "refused")
    assert answer.sql is None


def test_mutating_request_is_always_refused() -> None:
    answer = engine().ask("delete all orders")
    assert answer.status == "refused"
    assert answer.diagnostics[0].code == "MUTATING"


def test_relative_time_is_deterministic() -> None:
    engine_ = engine()
    first = engine_.ask("total revenue by country last quarter")
    second = engine_.ask("total revenue by country last quarter")
    assert first.sql == second.sql
    assert first.params == second.params
    assert first.params[0] == "2026-01-01"
