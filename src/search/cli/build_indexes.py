"""Build BM25 indexes beside the existing multimodal FAISS indexes."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from src.search.indexes.bm25 import build_bm25_index, iter_document_dirs


def default_index_root() -> Path:
    return Path(__file__).resolve().parents[3] / "references" / "assets" / "indexes"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--index-root", type=Path, default=default_index_root())
    parser.add_argument("--document-id", action="append", default=[])
    parser.add_argument("--no-overwrite", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    index_root = args.index_root.resolve()
    document_dirs = (
        [index_root / document_id for document_id in args.document_id]
        if args.document_id
        else list(iter_document_dirs(index_root))
    )
    manifests = [
        build_bm25_index(document_dir, overwrite=not args.no_overwrite)
        for document_dir in document_dirs
    ]
    print(json.dumps(manifests, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
