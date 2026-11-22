"""The single public entry point: ask a question, get a structured answer."""

from __future__ import annotations

import re
import sqlite3
import time
from datetime import datetime, timezone
from pathlib import Path

from .catalog import SchemaCatalog
from .compiler import compile_plan
from .executor import execute
from .intents import IntentCatalog
from .lexicon import Lexicon
from .models import Answer, Diagnostic, IntentFamily
from .planner import build_plan
from .retrieval import LexicalRetriever, Retriever, SemanticRetriever
from .schema_profile import SchemaProfile
from .validation import validate

DEFAULT_DB = Path(__file__).resolve().parents[2] / "data" / "northwind.sqlite"
DEFAULT_THRESHOLDS = {"lexical": 0.10, "semantic": 0.78}

MUTATING = re.compile(
    r"\b(delete|drop|insert|update|alter|truncate|create|grant|revoke|attach|detach|vacuum|pragma)\b",
    re.IGNORECASE,
)
VAGUE = re.compile(
    r"\b(what about|tell me about|overview of|an overview of|trend comparison|not sure|maybe|could you explain)\b",
    re.IGNORECASE,
)


class Engine:
    def __init__(
        self,
        db_path: Path | str | None = None,
        semantic: bool = False,
        now: datetime | None = None,
        threshold: float | None = None,
    ) -> None:
        self.db_path = Path(db_path) if db_path else DEFAULT_DB
        conn = sqlite3.connect(f"file:{self.db_path.as_posix()}?mode=ro", uri=True)
        try:
            self.catalog = SchemaCatalog.from_connection(conn)
            self.profile = SchemaProfile.discover(self.catalog, conn)
        finally:
            conn.close()
        self.lexicon = Lexicon(self.catalog, self.profile)
        self.intents = IntentCatalog()
        self.retriever: Retriever = (
            SemanticRetriever(self.intents) if semantic
            else LexicalRetriever(self.lexicon, self.intents)
        )
        self.now = now or datetime.now(timezone.utc)
        self.threshold = DEFAULT_THRESHOLDS[self.retriever.name] if threshold is None else threshold

    def ask(self, question: str, now: datetime | None = None) -> Answer:
        started = time.perf_counter()
        question = question.strip()
        if not question:
            return Answer(question, "refused", diagnostics=(Diagnostic("EMPTY", "Empty question"),))
        if MUTATING.search(question):
            return Answer(
                question, "refused",
                diagnostics=(Diagnostic("MUTATING", "Write operations are never allowed"),),
            )

        matches = self.retriever.retrieve(question, k=3)
        top = matches[0]

        if top.family is IntentFamily.OUT_OF_SCOPE:
            canonicals = self.lexicon.canonical_tokens(re.sub(r"[^a-z0-9_ ]", " ", question.lower()).split())
            has_business_metric = any(c.startswith(("measure:", "agg:")) for c in canonicals)
            business_opener = re.match(
                r"(what|total|how|show|give|list|top|compare|count|sum|average|revenue|sales)",
                question.lower(),
            )
            if has_business_metric and business_opener:
                matches = tuple(m for m in matches if m.family is not IntentFamily.OUT_OF_SCOPE)
                top = matches[0]

        effective_now = now or self.now

        def finish(answer: Answer) -> Answer:
            return Answer(
                **{**answer.__dict__, "latency_ms": (time.perf_counter() - started) * 1000}
            )

        if VAGUE.search(question) and top.family is not IntentFamily.OUT_OF_SCOPE:
            interpretations = tuple(m.family.value for m in matches[:2])
            return finish(Answer(
                question, "needs_clarification", confidence=top.score, family=top.family,
                interpretations=interpretations,
                clarification="Which of these did you mean? " + " / ".join(interpretations),
                diagnostics=(Diagnostic("VAGUE", "Question does not name a specific analysis"),),
            ))

        if top.family is IntentFamily.OUT_OF_SCOPE or top.score < self.threshold:
            return finish(Answer(
                question, "refused", confidence=top.score, family=top.family,
                diagnostics=(Diagnostic("LOW_CONFIDENCE", "Question is outside the supported scope"),),
            ))

        try:
            result = build_plan(
                question, top.family, self.lexicon, self.catalog,
                effective_now, alternatives=matches, profile=self.profile,
            )
        except (KeyError, ValueError) as exc:
            return finish(Answer(
                question, "refused", confidence=top.score, family=top.family,
                diagnostics=(Diagnostic("PLAN_ERROR", str(exc)),),
            ))

        if result.plan is None:
            if result.interpretations:
                return finish(Answer(
                    question, "needs_clarification", confidence=top.score, family=top.family,
                    interpretations=result.interpretations, diagnostics=result.diagnostics,
                    clarification="Which of these did you mean? " + " / ".join(result.interpretations),
                ))
            return finish(Answer(
                question, "refused", confidence=top.score, family=top.family,
                diagnostics=result.diagnostics,
            ))

        problems = validate(result.plan, self.catalog, self.profile)
        if problems:
            return finish(Answer(
                question, "refused", confidence=top.score, family=top.family,
                diagnostics=problems,
            ))

        try:
            compiled = compile_plan(result.plan, self.catalog, self.profile)
            execution = execute(self.db_path, compiled)
        except (ValueError, sqlite3.Error) as exc:
            return finish(Answer(
                question, "refused", confidence=top.score, family=top.family,
                diagnostics=(Diagnostic("EXECUTION_ERROR", str(exc)),),
            ))

        return finish(Answer(
            question, "answered", sql=compiled.sql, params=compiled.params,
            columns=execution.columns, rows=execution.rows,
            confidence=top.score, family=top.family, diagnostics=result.diagnostics,
            estimated_cost=execution.estimated_cost,
        ))
