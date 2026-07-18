"""Remove unusable image records from derived search indexes."""

from __future__ import annotations

import argparse
import json
import shutil
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

from src.search.document_catalog import DocumentCatalog, DocumentDescriptor
from src.search.indexes.bm25 import build_bm25_index, read_jsonl
from src.search.indexes.vector import load_vector_index
from src.search.quality import is_low_quality_image_record


def clean_document_images(
    document: DocumentDescriptor,
    *,
    apply: bool,
) -> dict:
    metadata_path = document.index_dir / "image_metadata.jsonl"
    index_path = document.index_dir / "image.faiss"
    records = read_jsonl(metadata_path) if metadata_path.exists() else []
    removed = [record for record in records if is_low_quality_image_record(record)]
    kept = [record for record in records if not is_low_quality_image_record(record)]
    report = {
        "document_id": document.document_id,
        "before_count": len(records),
        "after_count": len(kept),
        "removed_ids": [record["id"] for record in removed],
        "applied": apply,
    }
    if not apply or not removed:
        return report

    vector_index = load_vector_index(document.index_dir, "image")
    backup_dir = document.index_dir / "cleanup_backups" / datetime.now(
        timezone.utc
    ).strftime("%Y%m%dT%H%M%SZ")
    backup_dir.mkdir(parents=True, exist_ok=False)
    for path in (
        metadata_path,
        index_path,
        document.index_dir / "bm25_corpus.json.gz",
        document.index_dir / "bm25_manifest.json",
        document.index_dir / "manifest.json",
    ):
        if path.exists():
            shutil.copy2(path, backup_dir / path.name)

    try:
        import faiss
    except ImportError as exc:
        raise RuntimeError("faiss-cpu is required for image cleanup") from exc

    vectors: list[np.ndarray] = []
    cleaned_records: list[dict] = []
    for new_id, record in enumerate(kept):
        raw_index_id = int(record["faiss_id"]) + vector_index.id_offset
        vectors.append(vector_index.index.reconstruct(raw_index_id))
        cleaned_records.append({**record, "faiss_id": new_id})

    dimension = int(vector_index.index.d)
    if vector_index.metric_type == faiss.METRIC_INNER_PRODUCT:
        base_index = faiss.IndexFlatIP(dimension)
    elif vector_index.metric_type == faiss.METRIC_L2:
        base_index = faiss.IndexFlatL2(dimension)
    else:
        raise ValueError(f"Unsupported FAISS metric: {vector_index.metric_type}")
    cleaned_index = faiss.IndexIDMap2(base_index)
    if vectors:
        matrix = np.asarray(vectors, dtype="float32")
        cleaned_index.add_with_ids(
            matrix,
            np.arange(len(vectors), dtype="int64"),
        )

    metadata_path.write_text(
        "\n".join(
            json.dumps(record, ensure_ascii=False, separators=(",", ":"))
            for record in cleaned_records
        )
        + ("\n" if cleaned_records else ""),
        encoding="utf-8",
    )
    index_path.write_bytes(faiss.serialize_index(cleaned_index).tobytes())

    manifest_path = document.index_dir / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["modalities"]["image"]["count"] = len(cleaned_records)
    manifest.setdefault("maintenance", []).append(
        {
            "action": "remove_low_quality_images",
            "removed_ids": report["removed_ids"],
            "performed_at": datetime.now(timezone.utc).isoformat(),
            "backup_dir": str(backup_dir),
        }
    )
    manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    build_bm25_index(document.index_dir)
    report["backup_dir"] = str(backup_dir)
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Rewrite derived image/metadata/BM25 indexes; default is dry-run.",
    )
    args = parser.parse_args()
    reports = [
        clean_document_images(document, apply=args.apply)
        for document in DocumentCatalog.discover().documents
    ]
    print(json.dumps(reports, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
