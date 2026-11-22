"""Generate every metric quoted in the README. Run after build_db.py."""

from __future__ import annotations

import hashlib
import json
import sqlite3
import statistics
from collections import Counter
from datetime import datetime
from pathlib import Path

from queryscope.catalog import SchemaCatalog
from queryscope.engine import Engine
from queryscope.models import IntentFamily

ROOT = Path(__file__).resolve().parents[1]
BENCHMARK = ROOT / "benchmarks" / "questions.jsonl"
DB = ROOT / "data" / "northwind.sqlite"
RESULTS_DIR = ROOT / "docs" / "evaluation"
EVAL_NOW = datetime(2026, 6, 30)

CATEGORY_FAMILY = {
    "simple": IntentFamily.LOOKUP,
    "aggregate": IntentFamily.AGGREGATE,
    "trend": IntentFamily.TREND,
    "top_n": IntentFamily.TOP_N,
    "comparison": IntentFamily.COMPARISON,
    "distribution": IntentFamily.DISTRIBUTION,
    "join_lookup": IntentFamily.JOIN_LOOKUP,
    "out_of_scope": IntentFamily.OUT_OF_SCOPE,
}


def load_cases() -> list[dict]:
    return [json.loads(line) for line in BENCHMARK.read_text(encoding="utf-8").splitlines() if line.strip()]


def split(cases: list[dict]) -> tuple[list[dict], list[dict]]:
    calibration, test = [], []
    for case in cases:
        bucket = int(hashlib.sha1(case["id"].encode()).hexdigest()[:8], 16) % 10
        (calibration if bucket < 7 else test).append(case)
    return calibration, test


def gold_rows(case: dict, conn: sqlite3.Connection) -> tuple | None:
    sql = case.get("gold_sql")
    if not sql:
        return None
    return normalize(conn.execute(sql).fetchall())


def normalize(rows) -> tuple:
    def clean(value):
        if isinstance(value, float):
            return round(value, 2)
        return value

    return tuple(sorted(tuple(clean(v) for v in row) for row in rows))


def correct(case: dict, answer, expected_rows) -> bool:
    wanted = case.get("gold_status", "answered")
    if wanted == "answered":
        return answer.status == "answered" and normalize(answer.rows) == expected_rows
    return answer.status == wanted


def score(engine: Engine, cases: list[dict], conn: sqlite3.Connection) -> dict:
    counts = Counter()
    latencies: list[float] = []
    costs: list[float] = []
    for case in cases:
        expected = gold_rows(case, conn)
        answer = engine.ask(case["question"])
        right = correct(case, answer, expected)
        counts["total"] += 1
        counts["correct"] += int(right)
        counts["refused"] += int(answer.status == "refused")
        counts["correct_refusal"] += int(right and answer.status == "refused")
        counts["false_refusal"] += int(answer.status == "refused" and case.get("gold_status", "answered") == "answered")
        counts["covered"] += int(answer.status == "answered")
        counts["clarified"] += int(answer.status == "needs_clarification" and case.get("gold_status") == "needs_clarification")

        family = CATEGORY_FAMILY.get(case["category"])
        if family and answer.family is family:
            counts["intent_right"] += 1
        if family:
            counts["intent_total"] += 1
            matches = engine.retriever.retrieve(case["question"], 3)
            names = [m.family for m in matches]
            counts["r1"] += int(bool(names) and names[0] is family)
            counts["r3"] += int(family in names)

        if case.get("gold_status", "answered") == "answered":
            counts["answerable"] += 1
            counts["exec_right"] += int(right)
        latencies.append(answer.latency_ms)
        costs.append(answer.estimated_cost)

    def rate(num: str, den: str) -> float:
        return round(counts[num] / counts[den], 4) if counts[den] else 0.0

    latencies.sort()
    return {
        "cases": counts["total"],
        "decision_accuracy": rate("correct", "total"),
        "execution_accuracy": rate("exec_right", "answerable"),
        "intent_accuracy": rate("intent_right", "intent_total"),
        "retrieval_recall_at_1": rate("r1", "intent_total"),
        "retrieval_recall_at_3": rate("r3", "intent_total"),
        "refusal_precision": rate("correct_refusal", "refused"),
        "false_refusal_rate": rate("false_refusal", "answerable"),
        "coverage": rate("covered", "total"),
        "clarification_recall": round(
            counts["clarified"] / max(1, sum(1 for c in cases if c.get("gold_status") == "needs_clarification")), 4
        ),
        "latency_p50_ms": round(statistics.median(latencies), 2),
        "latency_p95_ms": round(latencies[min(len(latencies) - 1, int(len(latencies) * 0.95))], 2),
        "mean_estimated_scan_cost": round(statistics.mean(costs), 1),
    }


def tune_threshold(
    calibration: list[dict], conn: sqlite3.Connection, semantic: bool = False
) -> tuple[float, float]:
    best_threshold, best_score = (0.78 if semantic else 0.10), -1.0
    steps = range(50, 100) if semantic else range(10, 91)
    candidate = Engine(now=EVAL_NOW, semantic=semantic)
    for step in steps:
        threshold = step / 100
        candidate.threshold = threshold
        result = score(candidate, calibration, conn)
        if result["decision_accuracy"] >= best_score:
            best_threshold, best_score = threshold, result["decision_accuracy"]
    return best_threshold, best_score


def write_report(payload: dict) -> None:
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    (RESULTS_DIR / "results.json").write_text(json.dumps(payload, indent=2), encoding="utf-8")
    cal, test = payload["calibration"], payload["test"]
    rows = [
        ("Decision accuracy", f"{test['decision_accuracy']:.1%}", f"{cal['decision_accuracy']:.1%}"),
        ("Execution accuracy (answerable)", f"{test['execution_accuracy']:.1%}", f"{cal['execution_accuracy']:.1%}"),
        ("Intent accuracy", f"{test['intent_accuracy']:.1%}", f"{cal['intent_accuracy']:.1%}"),
        ("Retrieval recall@1", f"{test['retrieval_recall_at_1']:.1%}", f"{cal['retrieval_recall_at_1']:.1%}"),
        ("Retrieval recall@3", f"{test['retrieval_recall_at_3']:.1%}", f"{cal['retrieval_recall_at_3']:.1%}"),
        ("Refusal precision", f"{test['refusal_precision']:.1%}", f"{cal['refusal_precision']:.1%}"),
        ("False-refusal rate", f"{test['false_refusal_rate']:.1%}", f"{cal['false_refusal_rate']:.1%}"),
        ("Coverage", f"{test['coverage']:.1%}", f"{cal['coverage']:.1%}"),
        ("Clarification recall", f"{test['clarification_recall']:.1%}", f"{cal['clarification_recall']:.1%}"),
        ("Latency p50 / p95", f"{test['latency_p50_ms']:.1f} / {test['latency_p95_ms']:.1f} ms", "—"),
        ("Mean estimated scan cost", f"{test['mean_estimated_scan_cost']:.0f}", "—"),
    ]
    lines = [
        "# Evaluation results",
        "",
        "> Generated by `python scripts/run_eval.py`. Do not edit by hand.",
        "",
        f"**Benchmark:** {payload['total_cases']} questions · "
        f"{payload['calibration_cases']} calibration / {payload['test_cases']} held-out test. "
        f"The refusal threshold ({payload['threshold']:.2f}) was tuned on calibration only.",
        "",
        "## Held-out test results",
        "",
        "| Metric | Test | Calibration |",
        "|---|---:|---:|",
    ]
    lines.extend(f"| {name} | {test_value} | {cal_value} |" for name, test_value, cal_value in rows)
    sem = payload.get("semantic") or {}
    if "test" in sem:
        lines += [
            "",
            "## Retriever A/B (held-out test)",
            "",
            "| Retriever | Threshold | Execution accuracy | Decision accuracy | Refusal precision | p50 latency |",
            "|---|---:|---:|---:|---:|---:|",
            f"| Lexical (default) | {payload['threshold']:.2f} | {test['execution_accuracy']:.1%} | "
            f"{test['decision_accuracy']:.1%} | {test['refusal_precision']:.1%} | {test['latency_p50_ms']:.1f} ms |",
            f"| Semantic (opt-in, local) | {sem['threshold']:.2f} | {sem['test']['execution_accuracy']:.1%} | "
            f"{sem['test']['decision_accuracy']:.1%} | {sem['test']['refusal_precision']:.1%} | "
            f"{sem['test']['latency_p50_ms']:.1f} ms |",
        ]
    elif "error" in sem:
        lines += ["", "## Retriever A/B", "", "Semantic retriever unavailable in this environment: " + str(sem["error"])]

    lines += [
        "",
        "## Method",
        "",
        "- **Decision accuracy** — correct answer, correct refusal, or correct clarification request.",
        "- **Execution accuracy** — result-set equality with independent gold SQL, order-insensitive, "
        "floats rounded to 2 decimals. Denominator: answerable questions only.",
        "- **Intent accuracy** — retrieved family matches the family expected by the question category.",
        "- **Refusal precision** — correct refusals / all refusals, across every category. "
        "A wrongly refused in-scope question is a false positive.",
        "- **False-refusal rate** — in-scope questions wrongly refused / all in-scope questions.",
        "- **Coverage** — questions where a validated plan was produced.",
        "- **Estimated scan cost** — `EXPLAIN QUERY PLAN` heuristic: 100 per SCAN, 10 per SEARCH, "
        "50 per TEMP node. A comparative signal, not a timing.",
        "- **Clock** — pinned to 2026-06-30 so relative dates never drift.",
        "",
        "## What this does not measure",
        "",
        "Open-domain language understanding, arbitrary schemas, write workloads, or concurrency. "
        "The benchmark is in-domain by design; see the README trade-offs.",
        "",
    ]
    (RESULTS_DIR / "RESULTS.md").write_text("\n".join(lines), encoding="utf-8")


def main() -> None:
    cases = load_cases()
    calibration, test = split(cases)
    assert not (set(c["id"] for c in calibration) & set(c["id"] for c in test))
    conn = sqlite3.connect(f"file:{DB.as_posix()}?mode=ro", uri=True)
    try:
        threshold, cal_score = tune_threshold(calibration, conn, semantic=False)
        engine = Engine(now=EVAL_NOW, threshold=threshold)
        calibration_metrics = score(engine, calibration, conn)
        test_metrics = score(engine, test, conn)

        semantic_result = None
        try:
            sem_threshold, _ = tune_threshold(calibration, conn, semantic=True)
            sem_engine = Engine(now=EVAL_NOW, threshold=sem_threshold, semantic=True)
            semantic_result = {
                "threshold": sem_threshold,
                "calibration": score(sem_engine, calibration, conn),
                "test": score(sem_engine, test, conn),
            }
        except (ImportError, RuntimeError, OSError) as exc:  # optional extra not installed
            semantic_result = {"error": str(exc)}
    finally:
        conn.close()
    payload = {
        "threshold": threshold,
        "semantic": semantic_result,
        "total_cases": len(cases),
        "calibration_cases": len(calibration),
        "test_cases": len(test),
        "calibration": calibration_metrics,
        "test": test_metrics,
        "tuning_score": cal_score,
        "eval_now": EVAL_NOW.date().isoformat(),
        "retriever": "lexical",
    }
    write_report(payload)
    print(json.dumps(payload, indent=2))


if __name__ == "__main__":
    main()
