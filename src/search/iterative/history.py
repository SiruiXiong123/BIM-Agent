"""Immutable history updates for iterative regulation retrieval."""

from __future__ import annotations

from collections.abc import Sequence
import unicodedata

from src.search.iterative.models import (
    EvidenceHistoryItem,
    IterativeRetrievalState,
    QueryHistoryItem,
)
from src.search.models import SearchHit


class IterativeHistoryError(ValueError):
    """Raised when retrieval output cannot be recorded in the current state."""


MAX_EVIDENCE_PER_HOP = 3


def record_retrieval(
    state: IterativeRetrievalState,
    *,
    query: str,
    dense_query: str,
    target_document: str,
    hits: Sequence[SearchHit],
) -> IterativeRetrievalState:
    """Record one executed query and its hits without mutating ``state``.

    ``result_count`` is the number of final Top 3 hits retained from this
    retrieval call, including evidence seen in earlier hops. Global evidence
    history retains only the first occurrence of each stable evidence ID.
    """

    normalized_query = str(query or "").strip()
    if not normalized_query:
        raise IterativeHistoryError("query cannot be empty")
    normalized_dense_query = str(dense_query or "").strip()
    if not normalized_dense_query:
        raise IterativeHistoryError("dense_query cannot be empty")
    if target_document not in state.available_documents:
        raise IterativeHistoryError(
            "target_document is not in available_documents"
        )
    if state.hop >= state.max_hops:
        raise IterativeHistoryError("cannot record retrieval beyond max_hops")

    next_hop = state.hop + 1
    all_hits = list(hits)
    wrong_documents = {
        hit.document_id
        for hit in all_hits
        if hit.document_id != target_document
    }
    if wrong_documents:
        documents = ", ".join(sorted(wrong_documents))
        raise IterativeHistoryError(
            f"retrieval hits contain documents other than target_document: {documents}"
        )
    # T3 has a stable output budget independent of retriever implementation.
    # Retrievers should already rank their final output, so retaining this
    # prefix makes every hop contribute at most its final Top 3 evidence.
    hit_list = all_hits[:MAX_EVIDENCE_PER_HOP]

    existing_ids = {item.evidence_id for item in state.evidence_history}
    new_evidence: list[EvidenceHistoryItem] = []
    current_evidence_ids: list[str] = []
    current_seen: set[str] = set()

    for hit in hit_list:
        evidence_id = _evidence_id(hit)
        if evidence_id not in current_seen:
            current_evidence_ids.append(evidence_id)
            current_seen.add(evidence_id)
        if evidence_id in existing_ids:
            continue
        new_evidence.append(_to_evidence(hit, next_hop))
        existing_ids.add(evidence_id)

    query_item = QueryHistoryItem(
        hop=next_hop,
        query=normalized_query,
        dense_query=normalized_dense_query,
        target_document=target_document,
        result_count=len(hit_list),
        evidence_ids=current_evidence_ids,
    )
    pending_references = _pending_cross_document_references(
        state,
        hit_list,
        query=normalized_query,
        target_document=target_document,
    )
    return IterativeRetrievalState.model_validate(
        {
            **state.model_dump(mode="python"),
            "evidence_history": [*state.evidence_history, *new_evidence],
            "query_history": [*state.query_history, query_item],
            "pending_cross_document_references": pending_references,
            "hop": next_hop,
        }
    )


def _pending_cross_document_references(
    state: IterativeRetrievalState,
    hits: list[SearchHit],
    *,
    query: str,
    target_document: str,
) -> list[dict[str, str]]:
    references = [
        reference.model_dump(mode="python")
        for reference in state.pending_cross_document_references
    ]
    references.extend(
        reference.model_dump(mode="python")
        for hit in hits
        for reference in hit.cross_document_references
    )
    unique = list(
        {
            (item["target_document"], item["target_locator"]): item
            for item in references
        }.values()
    )
    normalized_query = unicodedata.normalize("NFKC", query).casefold()
    return [
        item
        for item in unique
        if not (
            item["target_document"] == target_document
            and unicodedata.normalize("NFKC", item["target_locator"]).casefold()
            in normalized_query
        )
    ]


def _evidence_id(hit: SearchHit) -> str:
    return f"{hit.document_id}:{hit.id}"


def _to_evidence(hit: SearchHit, hop: int) -> EvidenceHistoryItem:
    return EvidenceHistoryItem(
        evidence_id=_evidence_id(hit),
        document_id=hit.document_id,
        content_id=hit.id,
        modality=hit.modality,
        page=hit.page,
        title=hit.title,
        content=hit.content,
        summary=hit.summary,
        asset_path=hit.asset_path,
        score=hit.score,
        retrievers=hit.retrievers,
        cross_document_references=hit.cross_document_references,
        iter=hop,
    )
