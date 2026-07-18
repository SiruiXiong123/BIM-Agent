"""Load existing FAISS indexes and their traceable metadata."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

import numpy as np


@dataclass(frozen=True)
class VectorIndex:
    index: object
    records_by_id: dict[int, dict]
    metric_type: int
    id_offset: int


def load_vector_index(document_dir: Path, modality: str) -> VectorIndex:
    try:
        import faiss
    except ImportError as exc:
        raise RuntimeError("faiss-cpu is required for vector retrieval") from exc

    document_dir = Path(document_dir).resolve()
    index_path = document_dir / f"{modality}.faiss"
    metadata_path = document_dir / f"{modality}_metadata.jsonl"
    if not index_path.exists() or not metadata_path.exists():
        raise FileNotFoundError(f"Missing {modality} vector index in {document_dir}")

    # faiss.read_index cannot open some Unicode paths on Windows. Reading the
    # bytes in Python keeps path handling Unicode-safe on every platform.
    serialized = np.frombuffer(index_path.read_bytes(), dtype="uint8")
    index = faiss.deserialize_index(serialized)
    records = [
        json.loads(line)
        for line in metadata_path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    if index.ntotal != len(records):
        raise ValueError(
            f"FAISS/metadata count mismatch for {modality}: {index.ntotal} vs {len(records)}"
        )
    index_ids = _index_ids(index, faiss)
    metadata_ids = {int(record["faiss_id"]) for record in records}
    id_offset = _detect_id_offset(index_ids, metadata_ids)
    records_by_id = {
        int(record["faiss_id"]) + id_offset: record
        for record in records
    }
    return VectorIndex(
        index=index,
        records_by_id=records_by_id,
        metric_type=index.metric_type,
        id_offset=id_offset,
    )


def _index_ids(index: object, faiss_module: object) -> set[int]:
    if hasattr(index, "id_map"):
        return {
            int(value)
            for value in faiss_module.vector_to_array(index.id_map).tolist()
        }
    return set(range(int(index.ntotal)))


def _detect_id_offset(index_ids: set[int], metadata_ids: set[int]) -> int:
    """Accept identity or the known one-based FAISS/zero-based metadata layout."""

    if index_ids == metadata_ids:
        return 0
    if index_ids == {metadata_id + 1 for metadata_id in metadata_ids}:
        return 1
    raise ValueError(
        "FAISS IDs do not align with metadata IDs by identity or a +1 offset"
    )
