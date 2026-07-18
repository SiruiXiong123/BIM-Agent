"""Building-scoped reuse of raw regulation evidence for evacuation doors."""

from __future__ import annotations

import unicodedata
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from src.ai.evacuation_door_classifier import StructuredLLMClient
from src.schemas.assessment import EvacuationDoorClass
from src.search.config import SearchConfig
from src.search.document_catalog import DocumentCatalog
from src.search.iterative.models import (
    EvidenceHistoryItem,
    IFCContext,
    IterativeRetrievalResult,
    QueryHistoryItem,
    RetrievalAction,
)
from src.search.iterative.service import RetrieverFactory, run_iterative_retrieval
from src.search.models import RetrievalTask
from src.search.retrievers.vector import EmbedQuery


class BuildingEvidenceCacheError(ValueError):
    """Raised when building-level evidence reuse is unsafe or inapplicable."""


class BuildingEvidenceCacheKey(BaseModel):
    """Stable key for evidence shared within one uploaded IFC project."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    project_id: str = Field(min_length=1)
    building_type: str = Field(min_length=1)
    task: RetrievalTask
    available_documents: tuple[str, ...] = Field(min_length=1)


class BuildingEvidenceBundle(BaseModel):
    """T3 output shared by doors in one building.

    The bundle deliberately stops at evidence and evidence-sufficiency
    judgments. It does not contain regulation parameters, executable code,
    calculated widths or a compliance result.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    key: BuildingEvidenceCacheKey
    source_ifc_guid: str = Field(min_length=1)
    source_door_id: str = Field(min_length=1)
    evidence_history: tuple[EvidenceHistoryItem, ...] = Field(min_length=1)
    query_history: tuple[QueryHistoryItem, ...] = Field(default_factory=tuple)
    actual_clear_width_calculation_ready: bool = False
    actual_clear_width_evidence_ids: tuple[str, ...] = Field(
        default_factory=tuple
    )
    required_clear_width_calculation_ready: bool = False
    required_clear_width_evidence_ids: tuple[str, ...] = Field(
        default_factory=tuple
    )

    @model_validator(mode="after")
    def validate_sufficiency_evidence(self) -> "BuildingEvidenceBundle":
        known_evidence = {item.evidence_id for item in self.evidence_history}
        referenced = (
            set(self.actual_clear_width_evidence_ids)
            | set(self.required_clear_width_evidence_ids)
        )
        unknown = referenced - known_evidence
        if unknown:
            raise ValueError(
                "T3 sufficiency judgments reference unknown evidence IDs: "
                + ", ".join(sorted(unknown))
            )
        if (
            self.required_clear_width_calculation_ready
            and not self.required_clear_width_evidence_ids
        ):
            raise ValueError(
                "a sufficient required-width judgment requires evidence IDs"
            )
        return self


class BuildingEvidenceResolution(BaseModel):
    """Uniform T3 outcome for a fresh retrieval or building-cache hit."""

    model_config = ConfigDict(extra="forbid")

    status: Literal["cache_hit", "retrieved_and_cached", "retrieved_not_cached"]
    requested_ifc_guid: str = Field(min_length=1)
    requested_door_id: str = Field(min_length=1)
    llm_skipped: bool
    actual_clear_width_calculation_ready: bool
    required_clear_width_calculation_ready: bool
    evidence_bundle: BuildingEvidenceBundle | None = None
    retrieval_result: IterativeRetrievalResult | None = None


class BuildingEvidenceCache:
    """In-memory evidence cache scoped explicitly by ``project_id``.

    Create one instance for an IFC upload/batch. The key deliberately excludes
    door-specific facts such as storey, width, fire-door state and occupant load.
    Those facts select or calculate parameters from the shared raw evidence later.
    """

    def __init__(self) -> None:
        self._bundles: dict[BuildingEvidenceCacheKey, BuildingEvidenceBundle] = {}

    def get(
        self,
        key: BuildingEvidenceCacheKey,
    ) -> BuildingEvidenceBundle | None:
        bundle = self._bundles.get(key)
        return None if bundle is None else bundle.model_copy(deep=True)

    def put(self, bundle: BuildingEvidenceBundle) -> None:
        self._bundles[bundle.key] = bundle.model_copy(deep=True)

    def clear(self) -> None:
        self._bundles.clear()

    def __len__(self) -> int:
        return len(self._bundles)


def retrieve_or_reuse_building_evidence(
    *,
    project_id: str,
    task: RetrievalTask,
    original_query: str,
    ifc_context: IFCContext,
    cache: BuildingEvidenceCache,
    catalog: DocumentCatalog | None = None,
    client: StructuredLLMClient | None = None,
    config: SearchConfig | None = None,
    embed_query: EmbedQuery | None = None,
    enable_dense: bool = True,
    retriever_factory: RetrieverFactory | None = None,
) -> BuildingEvidenceResolution:
    """Reuse building evidence or run retrieval once for a representative door.

    A cache hit returns before an LLM client or retriever is constructed. Only a
    confirmed evacuation door may read or populate the shared evidence cache.
    """

    _require_evacuating_door(ifc_context)
    selected_catalog = catalog or DocumentCatalog.discover()
    key = _build_key(
        project_id=project_id,
        task=task,
        ifc_context=ifc_context,
        available_documents=selected_catalog.available_documents(),
    )
    cached = cache.get(key)
    if cached is not None:
        return BuildingEvidenceResolution(
            status="cache_hit",
            requested_ifc_guid=ifc_context.subject.ifc_guid,
            requested_door_id=ifc_context.subject.door_id,
            llm_skipped=True,
            actual_clear_width_calculation_ready=(
                cached.actual_clear_width_calculation_ready
            ),
            required_clear_width_calculation_ready=(
                cached.required_clear_width_calculation_ready
            ),
            evidence_bundle=cached,
            retrieval_result=None,
        )

    result = run_iterative_retrieval(
        task=task,
        original_query=original_query,
        ifc_context=ifc_context,
        catalog=selected_catalog,
        client=client,
        config=config,
        embed_query=embed_query,
        enable_dense=enable_dense,
        retriever_factory=retriever_factory,
    )
    bundle = _bundle_from_result(key, ifc_context, result)
    cacheable = result.action == RetrievalAction.FINISH and bundle is not None
    if cacheable:
        cache.put(bundle)
    return BuildingEvidenceResolution(
        status="retrieved_and_cached" if cacheable else "retrieved_not_cached",
        requested_ifc_guid=ifc_context.subject.ifc_guid,
        requested_door_id=ifc_context.subject.door_id,
        llm_skipped=False,
        actual_clear_width_calculation_ready=(
            result.actual_clear_width_calculation_ready
        ),
        required_clear_width_calculation_ready=(
            result.required_clear_width_calculation_ready
        ),
        evidence_bundle=bundle,
        retrieval_result=result,
    )


def _build_key(
    *,
    project_id: str,
    task: RetrievalTask,
    ifc_context: IFCContext,
    available_documents: list[str],
) -> BuildingEvidenceCacheKey:
    normalized_project = _normalize(project_id)
    building_type = ifc_context.building_context.building_type
    normalized_building = _normalize(building_type)
    normalized_task = _normalize(task)
    if not normalized_project:
        raise BuildingEvidenceCacheError("project_id cannot be empty")
    if not normalized_building:
        raise BuildingEvidenceCacheError(
            "building_type is required for building-level evidence reuse"
        )
    if not normalized_task:
        raise BuildingEvidenceCacheError("task cannot be empty")
    documents = tuple(
        sorted(
            str(item).strip()
            for item in available_documents
            if str(item).strip()
        )
    )
    if not documents:
        raise BuildingEvidenceCacheError("available_documents cannot be empty")
    return BuildingEvidenceCacheKey(
        project_id=normalized_project,
        building_type=normalized_building,
        task=normalized_task,
        available_documents=documents,
    )


def _bundle_from_result(
    key: BuildingEvidenceCacheKey,
    ifc_context: IFCContext,
    result: IterativeRetrievalResult,
) -> BuildingEvidenceBundle | None:
    if not result.evidence_history:
        return None
    return BuildingEvidenceBundle(
        key=key,
        source_ifc_guid=ifc_context.subject.ifc_guid,
        source_door_id=ifc_context.subject.door_id,
        evidence_history=tuple(
            item.model_copy(deep=True) for item in result.evidence_history
        ),
        query_history=tuple(
            item.model_copy(deep=True) for item in result.query_history
        ),
        actual_clear_width_calculation_ready=(
            result.actual_clear_width_calculation_ready
        ),
        actual_clear_width_evidence_ids=tuple(
            result.actual_clear_width_evidence_ids
        ),
        required_clear_width_calculation_ready=(
            result.required_clear_width_calculation_ready
        ),
        required_clear_width_evidence_ids=tuple(
            result.required_clear_width_evidence_ids
        ),
    )


def _require_evacuating_door(ifc_context: IFCContext) -> None:
    if (
        ifc_context.assessment.classification
        is not EvacuationDoorClass.EVACUATION_DOOR
    ):
        raise BuildingEvidenceCacheError(
            "building evidence reuse requires a confirmed evacuation door"
        )


def _normalize(value: object) -> str:
    return unicodedata.normalize("NFKC", str(value or "")).strip().casefold()
