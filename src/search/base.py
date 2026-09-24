from abc import ABC, abstractmethod
from typing import List
from src.models import TextBlock, SearchResult

class BaseRetriever(ABC):
    @abstractmethod
    def index(self, corpus: List[TextBlock]) -> None:
        """Indexes the supplied document corpus."""
        pass

    @abstractmethod
    def search(self, query: str, top_k: int = 5, min_score: float = 0.0) -> List[SearchResult]:
        """Executes a search against the indexed corpus."""
        pass