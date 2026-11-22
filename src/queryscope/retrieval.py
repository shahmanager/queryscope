"""Two interchangeable retrievers with one comparable score contract.

Both score in [0, 1]:
  - lexical: synonym-expanded overlap coefficient
  - semantic: clamped linear map of local cosine similarity

Normalizing at the scorer boundary is what lets a single confidence value
and a single decision policy work across both.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from .intents import IntentCatalog
from .lexicon import Lexicon, tokenize
from .models import IntentFamily


@dataclass(frozen=True)
class IntentMatch:
    family: IntentFamily
    score: float
    rank: int


class Retriever(Protocol):
    name: str

    def retrieve(self, question: str, k: int = 3) -> tuple[IntentMatch, ...]: ...


def _rank(scores: dict[IntentFamily, float], k: int) -> tuple[IntentMatch, ...]:
    ordered = sorted(scores.items(), key=lambda item: (-item[1], item[0].value))
    return tuple(
        IntentMatch(family, round(max(0.0, min(1.0, score)), 4), rank)
        for rank, (family, score) in enumerate(ordered[:k], 1)
    )


class LexicalRetriever:
    name = "lexical"

    def __init__(self, lexicon: Lexicon, catalog: IntentCatalog) -> None:
        self.lexicon = lexicon
        self.catalog = catalog
        self._example_tokens = {
            (family, example): frozenset(lexicon.canonical_tokens(tokenize(example)))
            for family, example in catalog.pairs()
        }

    def _score(self, question: str, example: str) -> float:
        q_tokens = frozenset(
            self.lexicon.canonical_tokens(tokenize(question))
            + self.lexicon.phrase_tokens(question)
        )
        e_tokens = self._example_tokens[(self._family_for(example), example)] | frozenset(
            self.lexicon.phrase_tokens(example)
        )
        if not q_tokens or not e_tokens:
            return 0.0
        return len(q_tokens & e_tokens) / len(q_tokens | e_tokens)

    def _family_for(self, example: str) -> IntentFamily:
        for family in self.catalog.families:
            if example in self.catalog.examples(family):
                return family
        raise KeyError(example)

    def retrieve(self, question: str, k: int = 3) -> tuple[IntentMatch, ...]:
        scores: dict[IntentFamily, float] = {}
        for family in self.catalog.families:
            scores[family] = max(
                (self._score(question, example) for example in self.catalog.examples(family)),
                default=0.0,
            )
        return _rank(scores, k)


class SemanticRetriever:
    """Local embeddings only. No API, no telemetry; opt-in dependency."""

    name = "semantic"
    MODEL = "sentence-transformers/all-MiniLM-L6-v2"

    def __init__(self, catalog: IntentCatalog) -> None:
        self.catalog = catalog
        self._model = None
        self._example_vectors = None
        self._pairs = catalog.pairs()

    def _load(self) -> None:
        if self._model is not None:
            return
        try:
            from sentence_transformers import SentenceTransformer
        except ImportError as exc:  # pragma: no cover - exercised via optional install
            raise RuntimeError(
                "Semantic retrieval requires the optional extra: "
                'pip install -e ".[semantic]"'
            ) from exc
        self._model = SentenceTransformer(self.MODEL)
        self._example_vectors = self._model.encode(
            [example for _family, example in self._pairs], normalize_embeddings=True
        )

    def retrieve(self, question: str, k: int = 3) -> tuple[IntentMatch, ...]:
        self._load()
        import numpy as np  # provided by sentence-transformers

        vector = self._model.encode([question], normalize_embeddings=True)[0]
        similarities = np.asarray(self._example_vectors) @ vector
        scores: dict[IntentFamily, float] = {}
        for index, (family, _example) in enumerate(self._pairs):
            cosine = float(similarities[index])
            normalized = (cosine + 1.0) / 2.0
            scores[family] = max(scores.get(family, 0.0), normalized)
        return _rank(scores, k)
