"""Semantic retrieval over existing FAISS indexes."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Callable

import numpy as np
from dotenv import load_dotenv

from src.search.indexes.bm25 import MODALITIES
from src.search.indexes.vector import load_vector_index
from src.search.models import SearchHit

EmbedQuery = Callable[[str], list[float]]


def openai_embedder() -> EmbedQuery:
    from openai import OpenAI

    load_dotenv()
    model = os.getenv("embedding_model_name")
    if not model:
        raise ValueError("embedding_model_name is missing from the environment")
    client = OpenAI(base_url=os.getenv("base_url"), api_key=os.getenv("api_key"))

    def embed(query: str) -> list[float]:
        response = client.embeddings.create(model=model, input=query)
        return response.data[0].embedding

    return embed


class VectorRetriever:
    def __init__(self, document_dir: Path, embed_query: EmbedQuery | None = None) -> None:
        self.document_dir = Path(document_dir).resolve()
        self.document_id = self.document_dir.name
        self.embed_query = embed_query or openai_embedder()

    def search(self, query: str, *, top_k: int = 10, modality: str) -> list[SearchHit]:
        query = str(query or "").strip()
        if not query:
            raise ValueError("query cannot be empty")
        if modality not in MODALITIES:
            raise ValueError(f"Unsupported modality: {modality}")
        vector_index = load_vector_index(self.document_dir, modality)
        if not vector_index.records_by_id:
            return []

        query_vector = np.asarray([self.embed_query(query)], dtype="float32")
        if query_vector.shape[1] != vector_index.index.d:
            raise ValueError(
                f"Embedding dimension mismatch: {query_vector.shape[1]} vs {vector_index.index.d}"
            )
        scores, ids = vector_index.index.search(query_vector, min(top_k, vector_index.index.ntotal))

        hits: list[SearchHit] = []
        for rank, (score, faiss_id) in enumerate(zip(scores[0], ids[0]), start=1):
            if int(faiss_id) < 0 or int(faiss_id) not in vector_index.records_by_id:
                continue
            record = vector_index.records_by_id[int(faiss_id)]
            hits.append(
                SearchHit.model_validate(
                    {
                        **record,
                        "document_id": self.document_id,
                        "rank": rank,
                        "score": float(score),
                        "dense_score": float(score),
                        "retrievers": ["dense"],
                    }
                )
            )
        return hits
