"""Build and load BM25 indexes from existing multimodal metadata."""

from __future__ import annotations

import gzip
import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable

from rank_bm25 import BM25Okapi

from src.search.tokenization import TOKENIZER_NAME, tokenize_zh_mixed

MODALITIES = ("text", "table", "image")
BM25_CORPUS_FILENAME = "bm25_corpus.json.gz"
BM25_MANIFEST_FILENAME = "bm25_manifest.json"


@dataclass(frozen=True)
class BM25Index:
    model: BM25Okapi
    records: list[dict]
    manifest: dict


def searchable_text(record: dict) -> str:
    """Combine useful semantic fields without duplicating stored metadata."""

    values = (
        record.get("title"),
        record.get("source_title"),
        record.get("metadata"),
        record.get("summary"),
        record.get("content"),
        record.get("table_markdown"),
        record.get("table_cells_text"),
        record.get("original_content"),
    )
    return "\n".join(dict.fromkeys(str(value).strip() for value in values if str(value or "").strip()))


def read_jsonl(path: Path) -> list[dict]:
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def load_metadata_records(document_dir: Path) -> list[dict]:
    records: list[dict] = []
    for modality in MODALITIES:
        path = document_dir / f"{modality}_metadata.jsonl"
        if not path.exists():
            continue
        for record in read_jsonl(path):
            item = dict(record)
            item["modality"] = modality
            item.setdefault("id", f"{modality}_{len(records):06d}")
            if searchable_text(item):
                records.append(item)
    return records


def build_bm25_index(document_dir: Path, *, overwrite: bool = True) -> dict:
    document_dir = Path(document_dir).resolve()
    records = load_metadata_records(document_dir)
    if not records:
        raise ValueError(f"No searchable metadata records found in {document_dir}")

    corpus_path = document_dir / BM25_CORPUS_FILENAME
    manifest_path = document_dir / BM25_MANIFEST_FILENAME
    if not overwrite and (corpus_path.exists() or manifest_path.exists()):
        raise FileExistsError(f"BM25 index already exists in {document_dir}")

    tokenized_corpus = [tokenize_zh_mixed(searchable_text(record)) for record in records]
    payload = {"tokenizer": TOKENIZER_NAME, "records": records, "tokens": tokenized_corpus}
    with gzip.open(corpus_path, "wt", encoding="utf-8") as stream:
        json.dump(payload, stream, ensure_ascii=False, separators=(",", ":"))

    counts = {modality: sum(record["modality"] == modality for record in records) for modality in MODALITIES}
    manifest = {
        "document_id": document_dir.name,
        "index_type": "bm25",
        "tokenizer": TOKENIZER_NAME,
        "record_count": len(records),
        "modality_counts": counts,
        "corpus_path": corpus_path.name,
        "metadata_sources": [f"{modality}_metadata.jsonl" for modality in MODALITIES],
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    return manifest


def load_bm25_index(document_dir: Path) -> BM25Index:
    document_dir = Path(document_dir).resolve()
    manifest = json.loads((document_dir / BM25_MANIFEST_FILENAME).read_text(encoding="utf-8"))
    with gzip.open(document_dir / manifest["corpus_path"], "rt", encoding="utf-8") as stream:
        payload = json.load(stream)
    if payload.get("tokenizer") != TOKENIZER_NAME:
        raise ValueError("BM25 tokenizer version changed; rebuild the index")
    records = payload["records"]
    tokens = payload["tokens"]
    if len(records) != len(tokens) or not records:
        raise ValueError("Invalid BM25 corpus payload")
    return BM25Index(model=BM25Okapi(tokens), records=records, manifest=manifest)


def iter_document_dirs(index_root: Path) -> Iterable[Path]:
    return (path for path in sorted(Path(index_root).iterdir()) if path.is_dir())
