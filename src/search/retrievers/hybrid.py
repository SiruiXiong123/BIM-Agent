"""Deterministic BM25 + dense reciprocal-rank fusion."""

from __future__ import annotations

from pathlib import Path

from src.search.config import SearchConfig
from src.search.indexes.bm25 import MODALITIES
from src.search.models import SearchHit
from src.search.quality import is_low_quality_hit
from src.search.retrievers.bm25 import BM25Retriever
from src.search.retrievers.vector import EmbedQuery, VectorRetriever


class HybridRetriever:
    def __init__(
        self,
        document_dir: Path,
        *,
        config: SearchConfig | None = None,
        embed_query: EmbedQuery | None = None,
        enable_dense: bool = True,
    ) -> None:
        self.config = config or SearchConfig()
        self.bm25 = BM25Retriever(document_dir)
        self.vector = VectorRetriever(document_dir, embed_query) if enable_dense else None

    def search(
        self,
        query: str,
        *,
        dense_query: str | None = None,
        top_k: int | None = None,
    ) -> list[SearchHit]:
        final_top_k = top_k or self.config.default_top_k
        selected_dense_query = str(dense_query or query).strip()
        exact_reference_hits = self.bm25.search_exact_references(
            query,
            top_k=final_top_k,
        )
        bm25_hits = self.bm25.search(
            query,
            top_k=self.config.default_candidate_k,
        )
        bm25_hits = [hit for hit in bm25_hits if not is_low_quality_hit(hit)]
        dense_hits: list[SearchHit] = []
        if self.vector is not None:
            per_modality_hits: list[SearchHit] = []
            for modality in MODALITIES:
                try:
                    per_modality_hits.extend(
                        self.vector.search(
                            selected_dense_query,
                            top_k=self.config.default_candidate_k,
                            modality=modality,
                        )
                    )
                except FileNotFoundError:
                    continue
            dense_hits = _global_dense_ranking(
                [hit for hit in per_modality_hits if not is_low_quality_hit(hit)],
                top_k=self.config.default_candidate_k,
            )

        fused = reciprocal_rank_fusion(
            bm25_hits,
            dense_hits,
            config=self.config,
            top_k=len(bm25_hits) + len(dense_hits),
        )
        quality_hits = [hit for hit in fused if not is_low_quality_hit(hit)]
        exact_keys = {
            (hit.document_id, hit.modality, hit.id)
            for hit in exact_reference_hits
        }
        ordered_hits = [
            *exact_reference_hits,
            *(
                hit
                for hit in quality_hits
                if (hit.document_id, hit.modality, hit.id) not in exact_keys
            ),
        ]
        return [
            hit.model_copy(update={"rank": rank})
            for rank, hit in enumerate(ordered_hits[:final_top_k], start=1)
        ]


def _global_dense_ranking(
    hits: list[SearchHit],
    *,
    top_k: int,
) -> list[SearchHit]:
    """Place text, table and image dense hits on one global score ranking."""

    ranked = sorted(hits, key=lambda hit: hit.score, reverse=True)[:top_k]
    return [
        hit.model_copy(update={"rank": rank})
        for rank, hit in enumerate(ranked, start=1)
    ]




def reciprocal_rank_fusion(
    bm25_hits: list[SearchHit],
    dense_hits: list[SearchHit],
    *,
    config: SearchConfig,
    top_k: int,
) -> list[SearchHit]:
    fused: dict[tuple[str, str, str], dict] = {}
    sources = (
        ("bm25", bm25_hits, config.bm25_weight),
        ("dense", dense_hits, config.dense_weight),
    )
    for source, hits, weight in sources:
        for source_rank, hit in enumerate(hits, start=1):
            key = (hit.document_id, hit.modality, hit.id)
            if key not in fused:
                fused[key] = hit.model_dump()
                fused[key]["rrf_score"] = 0.0
                fused[key]["retrievers"] = []
            item = fused[key]
            item["rrf_score"] += weight / (config.rrf_k + source_rank)
            if source not in item["retrievers"]:
                item["retrievers"].append(source)
            if source == "bm25":
                item["bm25_score"] = hit.bm25_score
            else:
                item["dense_score"] = hit.dense_score

    ranked = sorted(fused.values(), key=lambda item: item["rrf_score"], reverse=True)[:top_k]
    return [
        SearchHit.model_validate(
            {**item, "rank": rank, "score": item["rrf_score"]}
        )
        for rank, item in enumerate(ranked, start=1)
    ]
