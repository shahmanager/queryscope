# QueryScope — Design Document

**Date:** 2026-11-22
**Status:** Proposed — awaiting approval
**Owner:** (project author)

---

## 1. Intent and why

Build a portfolio project for a **solutions / consulting** role that turns plain-English business questions into SQL **without any LLM API fees or paid compute**.

The goal is not to claim state-of-the-art language understanding. It is to demonstrate **production-grade engineering judgement**: a typed compiler pipeline, safety by construction, an honest evaluation harness, and a quantified business case. A consulting recruiter should be able to read the README and see structured problem-solving, cost awareness, and the ability to ship a trustworthy system — not "I called an API."

Success looks like: a recruiter or interviewer can (a) run it locally in one command, (b) see measurable accuracy/latency/cost numbers, (c) trace every design decision to a trade-off, and (d) believe this would survive contact with a real client dataset.

---

## 2. Goals, non-goals, anti-goals

**Goals**
- Answer a bounded but realistic set of business questions over a fixed retail schema.
- Zero API spend; runs fully offline after setup.
- Deterministic, injectable, testable compiler core.
- Make safety structural: read-only, parameterized, resource-limited.
- Measure everything: accuracy, coverage, refusal quality, latency, cost.
- Produce consulting artifacts: ROI calculator, cost comparison, ADR-style trade-off table.

**Non-goals**
- Arbitrary user-supplied schemas (v1 targets one curated schema).
- Free-form creative SQL, DDL/DML, or write-back.
- Beating an LLM on open-domain Spider-style benchmarks.
- A heavy web frontend.

**Anti-goals (what would make this a failure even if it "works")**
- A thin wrapper around string matching presented as "AI."
- Unmeasured accuracy claims.
- Any user text interpolated into SQL.
- Hidden API calls or telemetry.

---

## 3. Constraints

- Python 3.10+, SQLite via stdlib. Available locally: Python 3.10.0, pip 26.2.1.
- No paid API, no paid compute. Embeddings (if used) must be local and optional.
- Default install must work with **zero model downloads**; semantic retrieval is opt-in.
- Project root: `C:\Users\Devam Shah\queryscope` (my call — easy to rename).
- Must run offline on a laptop.

---

## 4. Approaches considered

| # | Approach | What it proves | What it costs | Verdict |
|---|----------|----------------|---------------|---------|
| 1 | Strict classical NLP (rules + grammar → compiler) | Most defensible; every line is yours; zero dependencies | Brittle phrasing coverage; manual synonym upkeep | Strong fallback |
| 2 | Local small seq2seq model (fine-tuned T5 on Spider) | ML depth, higher open-domain accuracy | Heavy build, local compute, opaque, weaker "engineering" story for consulting | Rejected |
| 3 | Retrieval + deterministic compiler hybrid | Best systems story: swappable retrieval, strong compiler, measurable A/B | Needs a curated intent catalog | **Chosen** |

**Choice: 3, layered so the compiler is the backbone and retrieval is a thin, removable front-end.** With no semantic model installed, retrieval falls back to a stdlib lexical scorer, so the system is fully functional with zero downloads. This is the key engineering decision: the impressive part is the typed plan → validated → parameterized SQL pipeline, not the retrieval.

---

## 5. How it will be built (decided parts)

### 5.1 Domain
A fixed **Northwind-style retail/wholesale schema** (`customers`, `orders`, `order_items`, `products`, `categories`, `employees`, `stores`, `suppliers`) with deterministic seed data. Business-relatable, join-rich, and small enough to ship.

### 5.2 Pipeline (the backbone)
1. **Catalog** — introspect SQLite into a typed `SchemaCatalog` (tables, columns, types, PK/FK graph, row counts). No hardcoded schema in the compiler.
2. **Lexicon** — normalize text; map business synonyms → catalog columns (`"revenue"` → `order_items.unit_price * quantity`, `"client"` → `customers.company_name`).
3. **Retrieval** — select a canonical intent + plan skeleton from an `IntentCatalog`.
   - Default: **lexical** scorer (token overlap + synonym expansion), stdlib only.
   - Opt-in: **semantic** scorer via `sentence-transformers/all-MiniLM-L6-v2`, installed with `pip install queryscope[semantic]`. Local, ~90 MB, offline after first download.
   - Interface is a single `retrieve(question) -> list[IntentMatch]`; the two scorers are interchangeable.
4. **Planner** — merge retrieved intent + extracted slots (metrics, dimensions, filters, time ranges, numbers, top-N) into a **typed logical plan AST**. No SQL exists yet.
5. **Validation** — reject unknown columns, illegal aggregations (e.g. `SUM` on text), missing FK join paths, unsafe limits, unresolvable dates. Produces structured diagnostics, not exceptions.
6. **Compiler** — AST → SQL with `?` placeholders and a parameter list. Table/column names come only from the catalog allowlist.
7. **Executor** — read-only connection (`mode=ro` + `PRAGMA query_only=ON`), progress-handler timeout, row cap via `LIMIT`, estimated scan cost from `EXPLAIN QUERY PLAN`.
8. **Engine facade** — one `ask(question) -> Answer` with SQL, params, rows, confidence, diagnostics, latency, estimated cost.

### 5.3 Safety (structural, not advisory)
- Read-only connection; no DDL/DML token can reach SQLite.
- All values bound; no f-strings in SQL construction.
- Identifier allowlist from introspected catalog.
- Timeout + row cap + query cost estimate surfaced in the answer.
- Out-of-scope / low-confidence questions **refuse** with a reason instead of guessing.

### 5.4 Evaluation
- `benchmarks/questions.jsonl`: ~60 labelled questions across `simple`, `join`, `aggregate`, `time`, `top_n`, `ambiguous`, `out_of_scope`.
- Metrics:
  - **Execution accuracy** — result set equals gold SQL result on the same DB.
  - **Plan accuracy** — typed AST equals gold plan.
  - **Retrieval recall@k** — gold intent in top-k (lexical vs semantic A/B).
  - **Refusal precision** — correct refusals on out-of-scope questions.
  - **Latency p50/p95**, **coverage**, **estimated scan cost**.
- `scripts/run_eval.py` writes `docs/evaluation/RESULTS.md` + machine-readable JSON. Numbers are generated, never hand-written.

### 5.5 Business / consulting layer
- `business/roi.py` — configurable model: queries/day, analyst minutes saved, blended hourly cost, LLM price assumption. Outputs annual savings, payback period, cost per query, break-even.
- Cost comparison table: this system ≈ $0/query vs an LLM baseline assumption (configurable, cited as an assumption not a fact).
- README section mapping features → consulting competencies.

### 5.6 Interface
- `python -m queryscope ask "..."` — clean CLI.
- `python -m queryscope demo` — **zero-dependency web UI** using stdlib `http.server` (single polished page, screenshot-friendly). No Flask/Streamlit dependency.

### 5.7 Testing
- pytest unit tests per layer + end-to-end tests over a subset of the benchmark.
- GitHub Actions CI runs the suite on push.
- All gold numbers generated by scripts so docs cannot drift.

### 5.8 Project structure
```
queryscope/
├── README.md                  # recruiter-facing, generated sections
├── pyproject.toml
├── docs/
│   ├── superpowers/specs/...  # this document
│   ├── ARCHITECTURE.md
│   └── evaluation/RESULTS.md  # generated
├── src/queryscope/            # catalog, lexicon, retrieval, intents,
│                              # planner, validation, compiler, executor,
│                              # engine, cli, demo_server
├── data/                      # seed.sql + generated northwind.sqlite
├── benchmarks/questions.jsonl
├── business/roi.py
├── scripts/                   # build_db.py, run_eval.py
├── tests/
└── .github/workflows/ci.yml
```

---

## 6. Trade-offs to document in the README

- Accuracy ceiling vs. zero cost — bounded domain chosen deliberately.
- Lexical default vs. semantic opt-in — no forced download; A/B measured.
- Curated intent catalog vs. learned parser — transparent and auditable.
- Typed AST vs. direct SQL text — more code, but validation and safety become possible.
- Fixed schema vs. arbitrary schemas — depth over breadth.
- CLI + stdlib web UI vs. framework — zero dependency surface.

---

## 6b. Decisions from builder review (my calls)

1. **Comparable confidence + no eval leakage.** Each scorer normalizes its own output to `[0,1]`: lexical uses a synonym-expanded overlap coefficient; semantic uses a clamped, fixed linear map of cosine similarity. `retrieve()` returns one ranked list; `Answer.confidence` is the normalized top score. The refusal threshold is **tuned on a calibration split only**; all headline metrics are reported on a held-out test split. Split is deterministic by hash of question id (70/30).

2. **Composable intent families, not per-question templates.** ~8 intent families (`lookup`, `aggregate`, `trend`, `top_n`, `comparison`, `distribution`, `join_lookup`, `out_of_scope`), each with a generic slot skeleton. The planner composes metric × dimension × filter × time × top-N slots and cross-validates them. This is what keeps the system out of the "thin wrapper" anti-goal.

3. **Ambiguity is a first-class status.** `Answer.status ∈ {answered, needs_clarification, refused}`. Ambiguous questions return `needs_clarification`, a clarifying question, and up to two ranked interpretations — never a guessed query. **Refusal precision** = correct refusals / all refusals, computed across *every* category (so wrongly-refused in-scope questions count as false positives). False-refusal rate is reported alongside.

4. **Injectable clock.** `Engine(..., now=datetime)`; `ask(..., now=None)` defaults to real UTC. Evaluation pins `EVAL_NOW = 2026-06-30`. All relative time expressions resolve to concrete date parameters at plan time, so gold SQL never drifts.

5. **Coverage defined.** Fraction of benchmark questions for which a *valid, validated plan* was produced (not refused, not clarification-needed). Reported separately from retrieval recall and execution accuracy, which measure different things.

---

## 7. Left to the builder (implementation plan phase)

- Exact intent catalog contents and synonym map (data, not architecture).
- Concrete seed-data volumes.
- Number of benchmark questions per category.
- Exact visual styling of the demo page.
- Final naming of CLI flags.

These are data/polish decisions that do not change the architecture.
