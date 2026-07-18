"""Resolve retrieved table and image evidence to original local assets."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Protocol


class EvidenceWithMedia(Protocol):
    document_id: str
    modality: str
    asset_path: str | None

_SUPPORTED_MEDIA_TYPES = {
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".webp": "image/webp",
}


class EvidenceMediaResolutionError(ValueError):
    """Raised when non-text evidence cannot be mapped to a valid original asset."""


@dataclass(frozen=True, slots=True)
class ResolvedEvidenceMedia:
    """Validated original media associated with one retrieved evidence item."""

    evidence_id: str
    modality: str
    path: Path
    mime_type: str
    size_bytes: int


class EvidenceMediaResolver:
    """Resolve exact asset paths without falling back to OCR or summaries."""

    def __init__(self, references_root: Path | None = None) -> None:
        project_root = Path(__file__).resolve().parents[2]
        configured_root = references_root or project_root / "references"
        self._references_root = configured_root.resolve()

    @property
    def references_root(self) -> Path:
        return self._references_root

    def resolve(self, evidence: EvidenceWithMedia) -> ResolvedEvidenceMedia:
        """Return the validated original file for table or image evidence."""

        evidence_id = self._evidence_id(evidence)
        if evidence.modality not in {"table", "image"}:
            raise EvidenceMediaResolutionError(
                f"evidence {evidence_id!r} is text and has no original media"
            )
        if not evidence.asset_path or not evidence.asset_path.strip():
            raise EvidenceMediaResolutionError(
                f"evidence {evidence_id!r} has no asset_path"
            )

        configured_path = Path(evidence.asset_path)
        candidate = (
            configured_path
            if configured_path.is_absolute()
            else self._references_root / configured_path
        )
        resolved_path = candidate.resolve(strict=False)
        self._ensure_within_references(resolved_path, evidence_id)

        if not resolved_path.is_file():
            raise EvidenceMediaResolutionError(
                f"original media for evidence {evidence_id!r} does not exist: "
                f"{resolved_path}"
            )

        mime_type = _SUPPORTED_MEDIA_TYPES.get(resolved_path.suffix.lower())
        if mime_type is None:
            raise EvidenceMediaResolutionError(
                f"unsupported media type for evidence {evidence_id!r}: "
                f"{resolved_path.suffix or '<none>'}"
            )

        return ResolvedEvidenceMedia(
            evidence_id=evidence_id,
            modality=evidence.modality,
            path=resolved_path,
            mime_type=mime_type,
            size_bytes=resolved_path.stat().st_size,
        )

    def resolve_many(
        self, evidence_items: list[EvidenceWithMedia]
    ) -> list[ResolvedEvidenceMedia]:
        """Resolve all non-text evidence in order; fail if any asset is invalid."""

        return [
            self.resolve(item)
            for item in evidence_items
            if item.modality in {"table", "image"}
        ]

    def _ensure_within_references(self, path: Path, evidence_id: str) -> None:
        try:
            path.relative_to(self._references_root)
        except ValueError as exc:
            raise EvidenceMediaResolutionError(
                f"asset_path for evidence {evidence_id!r} escapes references root: "
                f"{path}"
            ) from exc

    @staticmethod
    def _evidence_id(evidence: EvidenceWithMedia) -> str:
        evidence_id = getattr(evidence, "evidence_id", None)
        if isinstance(evidence_id, str):
            return evidence_id
        content_id = getattr(evidence, "id", None)
        if not isinstance(content_id, str):
            raise EvidenceMediaResolutionError(
                "evidence must provide either evidence_id or id"
            )
        return f"{evidence.document_id}:{content_id}"
