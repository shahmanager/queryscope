# Architecture

## The shape of the system

QueryScope is a **compiler with a retrieval front-end**. Retrieval decides *what kind* of question was asked; everything after that is deterministic, typed, and testable. The compiler is the product — retrieval is a swappable input to it.

```mermaid
flowchart LR
    Q[Plain-English question] --> R{Retrieval}
    R -->|lexical, default| L[Synonym-expanded Jaccard]
    R -->|semantic, opt-in| S[Local MiniLM embeddings]
    L --> F[Ranked intent families + confidence]
    S --> F
    F --> P[Planner: compose slots into typed QueryPlan]
    P --> V[Validator: columns, types, joins, limits]
    V --> C[Compiler: parameterized SELECT]
    C --> E[Executor: read-only SQLite, capped, timed]
    E --> A[Answer: rows, SQL, confidence, diagnostics]
    F -.low confidence / vague.-> A
```

## Layers

| Layer | File | Responsibility | Never does |
|---|---|---|---|
| Catalog | `catalog.py` | Introspect tables, columns, types, PK/FK graph, row counts | Hardcode schema knowledge |
| Lexicon | `lexicon.py` | Map business words to a closed canonical vocabulary | Emit SQL |
| Intents | `intents.py` | Define eight composable intent families with example phrasings | Bind to one question each |
| Retrieval | `retrieval.py` | Rank families and normalize scores to `[0,1]` | Decide the final query |
| Planner | `planner.py` | Compose metrics, dimensions, filters, time, rank into a `QueryPlan` | Write SQL text |
| Validation | `validation.py` | Reject illegal plans with structured diagnostics | Execute anything |
| Compiler | `compiler.py` | Render a validated plan to SQL with bound parameters | Accept raw user strings |
| Executor | `executor.py` | Read-only, timeout-, row- and cost-limited execution | Mutate data |
| Engine | `engine.py` | Orchestrate the pipeline and map failures to answer statuses | Hide failures |

## Safety invariants

1. **Identifiers come from the catalog only.** Every table and column name in emitted SQL was read from `PRAGMA table_info`, never from the question.
2. **Every literal is bound.** The compiler appends `?` placeholders and returns a separate params tuple. There is no string-interpolation path for values.
3. **Write access is structurally impossible.** Connections use `file:...?mode=ro` plus `PRAGMA query_only=ON`; a mutating-keyword pre-check refuses write requests before retrieval.
4. **Resources are bounded.** A progress handler aborts long queries, a row cap is always applied, and `LIMIT` is clamped to 1–1000.
5. **Uncertainty is surfaced.** Low confidence, vague phrasing, and score ties become `refused` or `needs_clarification` rather than a guessed query.

## Why the plan is a typed AST

Direct text generation makes validation impossible. A `QueryPlan` makes legality a pure function:

- `SUM` on a TEXT column → `BAD_AGGREGATION`
- a dimension set with no FK path → `NO_JOIN_PATH`
- an unresolvable date range → `BAD_RANGE`

Each failure is a value the caller can inspect, not an exception from SQLite. This is the main engineering decision in the project.

## Retrieval contract

Both scorers implement `retrieve(question, k) -> tuple[IntentMatch, ...]` and return a normalized score in `[0,1]`:

- **Lexical** (default): synonym-expanded Jaccard overlap. Zero dependencies, zero downloads.
- **Semantic** (opt-in): local `all-MiniLM-L6-v2` cosine, mapped by `(cos + 1) / 2`.

Thresholds are per-scorer because the scales differ. The evaluation harness tunes each on a calibration split only and reports on a held-out test split.

## Extension points

| Change | Where |
|---|---|
| New business vocabulary | `lexicon.py` synonym table |
| New question shape | `intents.py` family + `planner.py` composer |
| New derived measure | `compiler.py` `DERIVED_SQL` + `validation.py` |
| New schema | regenerate with `scripts/build_db.py`; catalog and compiler adapt automatically |
| New scorer | implement the `Retriever` protocol |

## Known limits

One fixed schema, eight intent families, no discourse context, no joins chosen by a cost optimizer, and a heuristic scan-cost estimate rather than real query plans. These are deliberate scope choices, documented in the README trade-off table.
