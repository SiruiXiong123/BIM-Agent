"""Add one explicit cross-document reference to offline search metadata."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from src.search.document_catalog import DocumentCatalog
from src.search.indexes.bm25 import build_bm25_index, read_jsonl


def add_cross_document_reference(
    *,
    source_document: str,
    content_id: str,
    target_document: str,
    target_locator: str,
    catalog: DocumentCatalog | None = None,
) -> Path:
    """Update one exact metadata record and rebuild its derived BM25 corpus."""

    selected_catalog = catalog or DocumentCatalog.discover()
    source = selected_catalog.resolve(source_document)
    target = selected_catalog.resolve(target_document)
    modality = content_id.split("_", maxsplit=1)[0]
    if modality not in {"text", "table", "image"}:
        raise ValueError(f"Unsupported content ID modality: {content_id}")

    metadata_path = source.index_dir / f"{modality}_metadata.jsonl"
    records = read_jsonl(metadata_path)
    matches = [record for record in records if record.get("id") == content_id]
    if len(matches) != 1:
        raise ValueError(
            f"Expected exactly one {content_id!r} record, found {len(matches)}"
        )

    reference = {
        "target_document": target.document_id,
        "target_locator": target_locator.strip(),
    }
    if not reference["target_locator"]:
        raise ValueError("target_locator cannot be empty")
    record = matches[0]
    references = list(record.get("cross_document_references", []))
    if reference not in references:
        references.append(reference)
        record["cross_document_references"] = references
        temporary = metadata_path.with_suffix(metadata_path.suffix + ".tmp")
        temporary.write_text(
            "".join(
                json.dumps(item, ensure_ascii=False, separators=(",", ":")) + "\n"
                for item in records
            ),
            encoding="utf-8",
        )
        temporary.replace(metadata_path)
        build_bm25_index(source.index_dir, overwrite=True)
    return metadata_path


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source_document")
    parser.add_argument("content_id")
    parser.add_argument("target_document")
    parser.add_argument("target_locator")
    args = parser.parse_args()
    path = add_cross_document_reference(
        source_document=args.source_document,
        content_id=args.content_id,
        target_document=args.target_document,
        target_locator=args.target_locator,
    )
    print(path)


if __name__ == "__main__":
    main()
