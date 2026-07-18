import base64
import json
from pathlib import Path

import pytest

from src.ai.multimodal_evidence import build_multimodal_evidence_content
from src.search.evidence_media import (
    EvidenceMediaResolutionError,
    EvidenceMediaResolver,
)
from src.search.iterative.models import EvidenceHistoryItem


def _evidence(
    *,
    content_id: str,
    modality: str,
    content: str,
    summary: str = "",
    asset_path: str | None = None,
) -> EvidenceHistoryItem:
    return EvidenceHistoryItem(
        evidence_id=f"document:{content_id}",
        document_id="document",
        content_id=content_id,
        modality=modality,
        page=12,
        title="Evidence title",
        content=content,
        summary=summary,
        asset_path=asset_path,
        score=0.8,
        retrieved_at_hop=1,
    )


def test_builds_text_and_original_image_with_visual_content_and_summary(
    tmp_path: Path,
) -> None:
    references_root = tmp_path / "references"
    image_path = references_root / "assets" / "document" / "table.png"
    image_path.parent.mkdir(parents=True)
    image_bytes = b"original-table-image"
    image_path.write_bytes(image_bytes)
    text_evidence = _evidence(
        content_id="text_1",
        modality="text",
        content="Original regulation paragraph.",
        summary="TEXT SUMMARY MUST NOT BE SENT",
    )
    table_evidence = _evidence(
        content_id="table_1",
        modality="table",
        content="TABLE OCR CONTENT",
        summary="TABLE SUMMARY CONTENT",
        asset_path="assets/document/table.png",
    )

    parts = build_multimodal_evidence_content(
        context={"task": "collect evidence"},
        evidence_items=[text_evidence, table_evidence],
        resolver=EvidenceMediaResolver(references_root),
    )

    text_parts = "\n".join(
        part["text"] for part in parts if part["type"] == "text"
    )
    assert "Original regulation paragraph." in text_parts
    assert "TEXT SUMMARY MUST NOT BE SENT" not in text_parts
    assert "document:table_1" in text_parts
    assert '"modality": "table"' in text_parts
    assert '"content": "TABLE OCR CONTENT"' in text_parts
    assert '"summary": "TABLE SUMMARY CONTENT"' in text_parts

    image_part = next(part for part in parts if part["type"] == "image_url")
    data_url = image_part["image_url"]["url"]
    prefix, encoded = data_url.split(",", maxsplit=1)
    assert prefix == "data:image/png;base64"
    assert base64.b64decode(encoded) == image_bytes


def test_visual_evidence_missing_original_does_not_fall_back_to_text(
    tmp_path: Path,
) -> None:
    table_evidence = _evidence(
        content_id="table_1",
        modality="table",
        content="OCR fallback is forbidden.",
        asset_path="assets/document/missing.png",
    )

    with pytest.raises(EvidenceMediaResolutionError, match="does not exist"):
        build_multimodal_evidence_content(
            context={},
            evidence_items=[table_evidence],
            resolver=EvidenceMediaResolver(tmp_path / "references"),
        )


def test_context_is_kept_separate_from_evidence() -> None:
    parts = build_multimodal_evidence_content(
        context={"task": "collect evidence", "evidence_history": "forbidden"},
        evidence_items=[],
    )

    assert json.loads(parts[0]["text"])["context"]["task"] == "collect evidence"
