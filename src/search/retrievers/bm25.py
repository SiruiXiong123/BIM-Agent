"""Query a persisted multimodal BM25 index."""

from __future__ import annotations

from pathlib import Path

from src.search.indexes.bm25 import (
    MODALITIES,
    load_bm25_index,
    searchable_text,
)
from src.search.models import SearchHit
from src.search.references import (
    extract_reference_locators,
    reference_match_priority,
)
from src.search.tokenization import tokenize_zh_mixed


class BM25Retriever:
    def __init__(self, document_dir: Path) -> None:
        self.document_dir = Path(document_dir).resolve()
        self.document_id = self.document_dir.name
        self._index = load_bm25_index(self.document_dir)

    def search(
        self,
        query: str,
        *,
        top_k: int = 10,
        modality: str | None = None,
    ) -> list[SearchHit]:
        query = str(query or "").strip()
        if not query:
            raise ValueError("query cannot be empty")
        if top_k <= 0:
            raise ValueError("top_k must be greater than zero")
        if modality is not None and modality not in MODALITIES:
            raise ValueError(f"Unsupported modality: {modality}")

        scores = self._index.model.get_scores(tokenize_zh_mixed(query))
        candidates = [
            (position, float(score))
            for position, score in enumerate(scores)
            if float(score) > 0
            and (modality is None or self._index.records[position]["modality"] == modality)
        ]
        candidates.sort(key=lambda item: item[1], reverse=True)

        hits: list[SearchHit] = []
        for rank, (position, score) in enumerate(candidates[:top_k], start=1):
            record = self._index.records[position]
            hits.append(
                SearchHit.model_validate(
                    {
                        **record,
                        "document_id": self.document_id,
                        "rank": rank,
                        "score": score,
                        "bm25_score": score,
                        "retrievers": ["bm25"],
                    }
                )
            )
        return hits

    def search_exact_references(
        self,
        query: str,
        *,
        top_k: int = 10,
    ) -> list[SearchHit]:
        """Resolve explicit regulation references before semantic ranking."""

        locators = extract_reference_locators(query)
        if not locators:
            return []
        matches: list[tuple[int, dict]] = []
        for record in self._index.records:
            haystack = "\n".join((
                searchable_text(record),
                str(record.get("asset_path") or ""),
            ))
            priorities = tuple(
                priority
                for locator in locators
                if (
                    priority := reference_match_priority(
                        locator,
                        haystack,
                        modality=str(record.get("modality") or "text"),
                    )
                )
                is not None
            )
            if priorities:
                matches.append((min(priorities), record))
        matches.sort(
            key=lambda item: (
                item[0],
                str(item[1].get("id") or ""),
            )
        )
        return [
            SearchHit.model_validate({
                **record,
                "document_id": self.document_id,
                "rank": rank,
                "score": 1.0,
                "bm25_score": 1.0,
                "retrievers": ["bm25"],
            })
            for rank, (_, record) in enumerate(matches[:top_k], start=1)
        ]
