import re
import numpy as np
from typing import List
from rank_bm25 import BM25Okapi
from src.models import TextBlock, SearchResult
from src.search.base import BaseRetriever

_TOKEN_PATTERN = re.compile(r"\w+")


def tokenize(text: str) -> List[str]:
    """Lowercases and splits on word characters, dropping punctuation."""
    return _TOKEN_PATTERN.findall(text.lower())


class BM25Retriever(BaseRetriever):
    def __init__(self):
        self.corpus: List[TextBlock] = []
        self.model: BM25Okapi = None

    def index(self, corpus: List[TextBlock]) -> None:
        self.corpus = corpus
        tokenized_corpus = [tokenize(doc.text) for doc in self.corpus]
        self.model = BM25Okapi(tokenized_corpus)

    def search(self, query: str, top_k: int = 5, min_score: float = 0.0) -> List[SearchResult]:
        if not self.model or not self.corpus:
            return []

        tokens = tokenize(query)
        if not tokens:
            return []

        scores = self.model.get_scores(tokens)
        ranked_indices = np.argsort(scores)[::-1]

        results: List[SearchResult] = []
        rank_counter = 1

        for idx in ranked_indices:
            score = float(scores[idx])
            # A zero score means no query term appears in the block
            if score <= 0 or score < min_score:
                break

            results.append(
                SearchResult(
                    block=self.corpus[idx],
                    score=score,
                    rank=rank_counter
                )
            )
            rank_counter += 1
            if len(results) >= top_k:
                break

        return results