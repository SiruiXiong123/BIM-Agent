"""T3 orchestration for evidence retrieval and sufficiency judgment."""

from __future__ import annotations

from collections.abc import Callable
from typing import Protocol

from src.ai.evacuation_door_classifier import StructuredLLMClient
from src.ai.openai_compatible_client import OpenAICompatibleJSONClient
from src.search.config import SearchConfig
from src.search.document_catalog import DocumentCatalog, DocumentDescriptor
from src.search.iterative.controller import decide_next_action
from src.search.iterative.history import record_retrieval
from src.search.iterative.models import (
    IFCContext,
    IterativeRetrievalResult,
    IterativeRetrievalState,
    IterativeSearchDecision,
    RetrievalAction,
)
from src.search.models import RetrievalTask, SearchHit
from src.search.query_rewriter import rewrite_initial_query
from src.search.retrievers.hybrid import HybridRetriever
from src.search.retrievers.vector import EmbedQuery


class EvidenceRetriever(Protocol):
    """Small search interface required by the orchestration service."""

    def search(
        self,
        query: str,
        *,
        dense_query: str | None = None,
        top_k: int | None = None,
    ) -> list[SearchHit]: ...


RetrieverFactory = Callable[[DocumentDescriptor], EvidenceRetriever]


def run_iterative_retrieval(
    *,
    task: RetrievalTask,
    original_query: str,
    ifc_context: IFCContext,
    catalog: DocumentCatalog | None = None,
    client: StructuredLLMClient | None = None,
    config: SearchConfig | None = None,
    embed_query: EmbedQuery | None = None,
    enable_dense: bool = True,
    retriever_factory: RetrieverFactory | None = None,
) -> IterativeRetrievalResult:
    """Return retrieved evidence and both calculation-readiness judgments."""

    normalized_original_query = str(original_query or "").strip()
    if not normalized_original_query:
        raise ValueError("original_query cannot be empty")

    selected_catalog = catalog or DocumentCatalog.discover()
    selected_config = config or SearchConfig()
    selected_client = client or OpenAICompatibleJSONClient.from_env(
        model_env_key="model_name"
    )
    initial = rewrite_initial_query(
        task=task,
        original_query=normalized_original_query,
        ifc_context=ifc_context,
        catalog=selected_catalog,
        client=selected_client,
    )
    state = IterativeRetrievalState(
        task=task,
        original_query=normalized_original_query,
        ifc_context=ifc_context,
        available_documents=selected_catalog.available_documents(),
        max_hops=selected_config.max_hops,
    )

    factory = retriever_factory or _default_retriever_factory(
        config=selected_config,
        embed_query=embed_query,
        enable_dense=enable_dense,
    )
    retrievers: dict[str, EvidenceRetriever] = {}
    query = initial.query
    dense_query = initial.dense_query
    target_document = initial.target_document

    while True:
        retriever = retrievers.get(target_document)
        if retriever is None:
            descriptor = selected_catalog.resolve(target_document)
            retriever = factory(descriptor)
            retrievers[target_document] = retriever

        hits = retriever.search(
            query,
            dense_query=dense_query,
            top_k=selected_config.default_top_k,
        )
        state = record_retrieval(
            state,
            query=query,
            dense_query=dense_query,
            target_document=target_document,
            hits=hits,
        )
        decision = decide_next_action(state, selected_client)
        state = _merge_extra_info(state, decision.extra_info)
        state = _update_missing_information(state, decision.missing_evidence)

        if decision.action is not RetrievalAction.SEARCH:
            return _build_terminal_result(state, decision)

        # The controller schema and runtime validation guarantee both values.
        assert decision.query is not None
        assert decision.dense_query is not None
        assert decision.target_document is not None
        query = decision.query
        dense_query = decision.dense_query
        target_document = decision.target_document


def _default_retriever_factory(
    *,
    config: SearchConfig,
    embed_query: EmbedQuery | None,
    enable_dense: bool,
) -> RetrieverFactory:
    def build(descriptor: DocumentDescriptor) -> HybridRetriever:
        return HybridRetriever(
            descriptor.index_dir,
            config=config,
            embed_query=embed_query,
            enable_dense=enable_dense,
        )

    return build


def _build_terminal_result(
    state: IterativeRetrievalState,
    decision: IterativeSearchDecision,
) -> IterativeRetrievalResult:
    return IterativeRetrievalResult(
        action=decision.action,
        task=state.task,
        original_query=state.original_query,
        evidence_ids=decision.evidence_ids,
        missing_evidence=decision.missing_evidence,
        extra_info=state.extra_info,
        actual_clear_width_calculation_ready=(
            decision.actual_clear_width_calculation_ready
        ),
        actual_clear_width_evidence_ids=(
            decision.actual_clear_width_evidence_ids
        ),
        required_clear_width_calculation_ready=(
            decision.required_clear_width_calculation_ready
        ),
        required_clear_width_evidence_ids=(
            decision.required_clear_width_evidence_ids
        ),
        reason=decision.reason,
        hop=state.hop,
        query_history=state.query_history,
        evidence_history=state.evidence_history,
    )


def _merge_extra_info(
    state: IterativeRetrievalState,
    additions: list[str],
) -> IterativeRetrievalState:
    merged = list(
        dict.fromkeys(
            item.strip()
            for item in [*state.extra_info, *additions]
            if item and item.strip()
        )
    )
    if merged == state.extra_info:
        return state
    data = state.model_dump(mode="python")
    data["extra_info"] = merged
    return IterativeRetrievalState.model_validate(data)


def _update_missing_information(
    state: IterativeRetrievalState,
    current_missing: list[str],
) -> IterativeRetrievalState:
    """Replace pre-retrieval gaps with the latest readiness assessment.

    The controller first judges the complete evidence pool for the current
    hop.  Only that validated decision becomes the missing-information input
    for the next hop, so resolved gaps cannot remain as stale IFC context.
    """

    normalized = list(
        dict.fromkeys(
            item.strip()
            for item in current_missing
            if item and item.strip()
        )
    )
    if normalized == state.ifc_context.missing_information:
        return state
    data = state.model_dump(mode="python")
    data["ifc_context"]["missing_information"] = normalized
    return IterativeRetrievalState.model_validate(data)
