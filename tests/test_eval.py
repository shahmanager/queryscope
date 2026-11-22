import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from run_eval import load_cases, split


def test_split_is_deterministic_and_disjoint() -> None:
    cases = load_cases()
    first = split(cases)
    second = split(cases)
    assert [c["id"] for c in first[0]] == [c["id"] for c in second[0]]
    assert not {c["id"] for c in first[0]} & {c["id"] for c in first[1]}
    assert len(first[0]) + len(first[1]) == len(cases)


def test_benchmark_has_all_categories() -> None:
    cases = load_cases()
    categories = {c["category"] for c in cases}
    assert {"simple", "aggregate", "trend", "top_n", "comparison",
            "distribution", "join_lookup", "ambiguous", "out_of_scope"} <= categories
    assert len(cases) >= 60


def test_answerable_cases_have_gold_sql() -> None:
    for case in load_cases():
        if case.get("gold_status", "answered") == "answered":
            assert case.get("gold_sql"), case["id"]
