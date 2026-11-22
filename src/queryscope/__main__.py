"""Command line entry point."""

from __future__ import annotations

import argparse
import dataclasses
import json
from pathlib import Path

from .engine import Engine


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="queryscope", description="Ask business questions in plain English.")
    sub = parser.add_subparsers(dest="command", required=True)

    ask = sub.add_parser("ask", help="answer one question")
    ask.add_argument("question", nargs="+", help="question to ask")
    ask.add_argument("--db", type=Path, default=None, help="path to the SQLite warehouse")
    ask.add_argument("--semantic", action="store_true", help="use local semantic retrieval (optional extra)")
    ask.add_argument("--json", action="store_true", help="emit machine-readable JSON")
    ask.add_argument("--explain", action="store_true", help="show compiled SQL and diagnostics")

    demo = sub.add_parser("demo", help="start the local web demo")
    demo.add_argument("--db", type=Path, default=None)
    demo.add_argument("--port", type=int, default=8765)
    demo.add_argument("--semantic", action="store_true")
    return parser


def print_answer(answer, explain: bool = False) -> None:
    badge = {
        "answered": "[OK]",
        "needs_clarification": "[CLARIFY]",
        "refused": "[REFUSED]",
    }[answer.status]
    print(f"{badge} {answer.question}")
    print(f"    intent: {answer.family.value if answer.family else '-'}    confidence: {answer.confidence:.3f}")
    if answer.clarification:
        print(f"    {answer.clarification}")
    for diagnostic in answer.diagnostics:
        print(f"    ! {diagnostic.code}: {diagnostic.message}")
    if explain and answer.sql:
        print("\n    SQL:")
        for line in answer.sql.splitlines():
            print("      " + line)
        print(f"    params: {answer.params}")
    if answer.rows:
        columns = answer.columns
        print("\n    " + " | ".join(columns))
        print("    " + "-" * max(12, sum(len(c) for c in columns) + 3 * len(columns)))
        for row in answer.rows[:20]:
            print("    " + " | ".join(str(value) for value in row))
        if len(answer.rows) > 20:
            print(f"    ... {len(answer.rows) - 20} more rows")
    print(f"\n    {answer.latency_ms:.1f} ms    est. scan cost: {answer.estimated_cost:.0f}")


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    engine = Engine(db_path=args.db, semantic=args.semantic)
    if args.command == "demo":
        from .demo_server import run_demo_server

        run_demo_server(engine, args.port)
        return 0

    answer = engine.ask(" ".join(args.question))
    if args.json:
        print(json.dumps(dataclasses.asdict(answer), default=str, indent=2))
    else:
        print_answer(answer, explain=args.explain)
    return 0 if answer.status == "answered" else 2


if __name__ == "__main__":
    raise SystemExit(main())
