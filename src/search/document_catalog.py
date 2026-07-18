"""Discover and resolve regulation documents backed by local indexes."""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from pathlib import Path

_PAGE_RANGE_SUFFIX = re.compile(r"\s*\(page\s*\d+\s*-\s*\d+\)\s*$", re.IGNORECASE)
_DASHES = str.maketrans({"—": "-", "–": "-", "−": "-"})


class DocumentCatalogError(ValueError):
    """Base error for document discovery and resolution."""


class DocumentNotFoundError(DocumentCatalogError):
    """Raised when a requested document is not available."""


class AmbiguousDocumentError(DocumentCatalogError):
    """Raised when one alias maps to multiple documents."""


@dataclass(frozen=True)
class DocumentDescriptor:
    document_id: str
    title: str
    index_dir: Path
    aliases: tuple[str, ...]

class DocumentCatalog:
    """Read-only catalog whose document IDs come from index directory names."""

    def __init__(self, index_root: Path, documents: list[DocumentDescriptor]) -> None:
        self.index_root = Path(index_root).resolve()
        if not documents:
            raise DocumentCatalogError(
                f"No indexed documents were found in {self.index_root}"
            )
        self._documents = tuple(sorted(documents, key=lambda item: item.document_id))
        self._by_id = {item.document_id: item for item in self._documents}
        if len(self._by_id) != len(self._documents):
            raise DocumentCatalogError("document IDs must be unique")
        self._by_alias = self._build_alias_index()

    @classmethod
    def discover(cls, index_root: Path | None = None) -> "DocumentCatalog":
        root = Path(index_root or default_index_root()).resolve()
        if not root.is_dir():
            raise DocumentCatalogError(f"Index root does not exist: {root}")

        documents: list[DocumentDescriptor] = []
        for index_dir in sorted(path for path in root.iterdir() if path.is_dir()):
            if not _is_indexed_document(index_dir):
                continue
            document_id = index_dir.name
            title = _PAGE_RANGE_SUFFIX.sub("", document_id).strip() or document_id
            aliases = tuple(dict.fromkeys((document_id, title)))
            documents.append(
                DocumentDescriptor(
                    document_id=document_id,
                    title=title,
                    index_dir=index_dir.resolve(),
                    aliases=aliases,
                )
            )
        return cls(root, documents)

    @property
    def documents(self) -> tuple[DocumentDescriptor, ...]:
        return self._documents

    def available_documents(self) -> list[str]:
        return [item.document_id for item in self._documents]

    def resolve(self, name: str) -> DocumentDescriptor:
        normalized = normalize_document_name(name)
        matches = self._by_alias.get(normalized, ())
        if not matches:
            available = ", ".join(self._by_id)
            raise DocumentNotFoundError(
                f"Unknown document {name!r}. Available documents: {available}"
            )
        if len(matches) > 1:
            ids = ", ".join(item.document_id for item in matches)
            raise AmbiguousDocumentError(
                f"Ambiguous document name {name!r}; matches: {ids}"
            )
        return matches[0]

    def mentioned_documents(self, text: str) -> list[DocumentDescriptor]:
        """Return catalog documents whose full ID or title occurs in text."""

        normalized_text = normalize_document_name(text)
        matches: list[DocumentDescriptor] = []
        for document in self._documents:
            if any(
                normalize_document_name(alias) in normalized_text
                for alias in document.aliases
            ):
                matches.append(document)
        return matches

    def _build_alias_index(self) -> dict[str, tuple[DocumentDescriptor, ...]]:
        mutable: dict[str, list[DocumentDescriptor]] = {}
        for document in self._documents:
            for alias in document.aliases:
                mutable.setdefault(normalize_document_name(alias), []).append(document)
        return {key: tuple(value) for key, value in mutable.items()}


def default_index_root() -> Path:
    return Path(__file__).resolve().parents[2] / "references" / "assets" / "indexes"


def normalize_document_name(value: str) -> str:
    normalized = unicodedata.normalize("NFKC", str(value or "")).translate(_DASHES)
    normalized = normalized.strip()
    if normalized.casefold().endswith(".pdf"):
        normalized = normalized[:-4]
    normalized = re.sub(r"\s+", "", normalized)
    if not normalized:
        raise DocumentNotFoundError("Document name cannot be empty")
    return normalized.casefold()


def _is_indexed_document(index_dir: Path) -> bool:
    if not (index_dir / "manifest.json").is_file():
        return False
    return any((index_dir / f"{modality}_metadata.jsonl").is_file() for modality in ("text", "table", "image"))
