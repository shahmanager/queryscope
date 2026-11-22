import sqlite3
from pathlib import Path

from queryscope.catalog import SchemaCatalog
from queryscope.intents import IntentCatalog
from queryscope.lexicon import Lexicon, tokenize
from queryscope.models import IntentFamily
from queryscope.retrieval import LexicalRetriever

DB = Path(__file__).resolve().parents[1] / "data" / "northwind.sqlite"


def setup() -> LexicalRetriever:
    conn = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
    try:
        catalog = SchemaCatalog.from_connection(conn)
    finally:
        conn.close()
    return LexicalRetriever(Lexicon(catalog), IntentCatalog())


def test_tokenize() -> None:
    assert tokenize("Total revenue by country?") == ("total", "revenue", "by", "country")


def test_lexicon_maps_business_terms() -> None:
    lex = setup().lexicon
    assert "table:customers" in lex.canonicals("clients")
    assert "measure:line_revenue" in lex.canonicals("revenue")


def test_lexical_retriever_ranks_relevant_family() -> None:
    matches = setup().retrieve("how many orders last quarter", k=3)
    assert matches[0].family in (IntentFamily.AGGREGATE, IntentFamily.TREND)
    assert all(0.0 <= m.score <= 1.0 for m in matches)


def test_real_question_beats_nonsense() -> None:
    retriever = setup()
    real = retriever.retrieve("total revenue by country")[0].score
    nonsense = retriever.retrieve("purple bicycle accordion whisper")[0].score
    assert real > nonsense
