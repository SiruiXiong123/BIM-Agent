"""Data contracts for evidence-driven iterative regulation retrieval."""

from src.search.iterative.building_evidence_cache import (
    BuildingEvidenceBundle,
    BuildingEvidenceCache,
    BuildingEvidenceCacheError,
    BuildingEvidenceCacheKey,
    BuildingEvidenceResolution,
    retrieve_or_reuse_building_evidence,
)
from src.search.iterative.controller import (
    IterativeControllerError,
    decide_next_action,
)
from src.search.iterative.history import IterativeHistoryError, record_retrieval
from src.search.iterative.models import (
    EvidenceHistoryItem,
    IFCContext,
    InitialQueryRewrite,
    IterativeRetrievalResult,
    IterativeRetrievalState,
    IterativeSearchDecision,
    QueryHistoryItem,
    RetrievalAction,
)
from src.search.iterative.service import (
    EvidenceRetriever,
    RetrieverFactory,
    run_iterative_retrieval,
)

__all__ = [
    "BuildingEvidenceBundle",
    "BuildingEvidenceCache",
    "BuildingEvidenceCacheError",
    "BuildingEvidenceCacheKey",
    "BuildingEvidenceResolution",
    "EvidenceHistoryItem",
    "EvidenceRetriever",
    "IFCContext",
    "InitialQueryRewrite",
    "IterativeControllerError",
    "IterativeHistoryError",
    "IterativeRetrievalResult",
    "IterativeRetrievalState",
    "IterativeSearchDecision",
    "QueryHistoryItem",
    "RetrievalAction",
    "RetrieverFactory",
    "decide_next_action",
    "record_retrieval",
    "retrieve_or_reuse_building_evidence",
    "run_iterative_retrieval",
]
