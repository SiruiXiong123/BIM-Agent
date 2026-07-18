"""Build grounded multimodal messages from retrieved regulation evidence."""

from __future__ import annotations

import base64
import json
from collections.abc import Sequence
from typing import Any, Protocol

from src.search.evidence_media import EvidenceMediaResolver


MultimodalContentPart = dict[str, Any]


class PromptEvidence(Protocol):
    evidence_id: str
    document_id: str
    modality: str
    page: int | None
    title: str | None
    content: str
    summary: str
    cross_document_references: Sequence[Any]
    asset_path: str | None


def build_multimodal_evidence_content(
    *,
    context: dict[str, Any],
    evidence_items: Sequence[PromptEvidence],
    resolver: EvidenceMediaResolver | None = None,
) -> list[MultimodalContentPart]:
    """Serialize text evidence and grounded visual evidence for a VLM."""

    media_resolver = resolver or EvidenceMediaResolver()
    content: list[MultimodalContentPart] = [
        {
            "type": "text",
            "text": json.dumps(
                {"context": context},
                ensure_ascii=False,
                indent=2,
            ),
        }
    ]

    for evidence in evidence_items:
        if evidence.modality == "text":
            content.append({
                "type": "text",
                "text": json.dumps(
                    {"text_evidence": _text_evidence_payload(evidence)},
                    ensure_ascii=False,
                    indent=2,
                ),
            })
            continue

        media = media_resolver.resolve(evidence)
        content.append({
            "type": "text",
            "text": json.dumps(
                {"visual_evidence": _visual_evidence_metadata(evidence)},
                ensure_ascii=False,
                indent=2,
            ),
        })
        encoded = base64.b64encode(media.path.read_bytes()).decode("ascii")
        content.append({
            "type": "image_url",
            "image_url": {
                "url": f"data:{media.mime_type};base64,{encoded}",
                "detail": "high",
            },
        })

    return content


def _common_metadata(evidence: PromptEvidence) -> dict[str, Any]:
    metadata: dict[str, Any] = {
        "evidence_id": evidence.evidence_id,
        "document_id": evidence.document_id,
        "page": evidence.page,
        "title": evidence.title,
    }
    if evidence.cross_document_references:
        metadata["cross_document_references"] = [
            item.model_dump(mode="json")
            for item in evidence.cross_document_references
        ]
    return metadata


def _text_evidence_payload(evidence: PromptEvidence) -> dict[str, Any]:
    return {
        **_common_metadata(evidence),
        "content": evidence.content,
    }


def _visual_evidence_metadata(evidence: PromptEvidence) -> dict[str, Any]:
    return {
        **_common_metadata(evidence),
        "modality": evidence.modality,
        "content": evidence.content,
        "summary": evidence.summary,
    }
