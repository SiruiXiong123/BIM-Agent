"""Pydantic contracts for iterative regulation retrieval."""

from __future__ import annotations

from enum import StrEnum
from typing import Annotated, Literal

from pydantic import AliasChoices, BaseModel, ConfigDict, Field, model_validator

from src.schemas.assessment import ClearWidthResolution
from src.search.models import (
    ContentType,
    CrossDocumentReference,
    RetrievalAssessment,
    RetrievalBuildingContext,
    RetrievalDoorFacts,
    RetrievalSubject,
    RetrievalTask,
)

NonNegativeInt = Annotated[int, Field(ge=0)]
PositiveInt = Annotated[int, Field(gt=0)]


class IterativeModel(BaseModel):
    """Strict base model shared by iterative-retrieval contracts."""

    model_config = ConfigDict(extra="forbid", validate_assignment=True)


class RetrievalAction(StrEnum):
    SEARCH = "search"
    FINISH = "finish"
    INSUFFICIENT_EVIDENCE = "insufficient_evidence"


class IFCContext(IterativeModel):
    """Task-relevant IFC facts available before regulation retrieval."""

    subject: RetrievalSubject
    building_context: RetrievalBuildingContext
    door_facts: RetrievalDoorFacts
    assessment: RetrievalAssessment
    clear_width_resolution: ClearWidthResolution
    missing_information: list[str] = Field(default_factory=list)
    data_quality_warnings: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_identity(self) -> "IFCContext":
        if self.clear_width_resolution.ifc_guid != self.subject.ifc_guid:
            raise ValueError(
                "clear_width_resolution.ifc_guid must match subject.ifc_guid"
            )
        return self


class EvidenceHistoryItem(IterativeModel):
    """One immutable, traceable item returned by a retrieval hop."""

    evidence_id: str = Field(min_length=1)
    document_id: str = Field(min_length=1)
    content_id: str = Field(min_length=1)
    modality: ContentType
    page: PositiveInt | None = None
    title: str | None = None
    content: str = ""
    summary: str = ""
    asset_path: str | None = None
    score: float
    retrievers: list[Literal["bm25", "dense"]] = Field(default_factory=list)
    cross_document_references: list[CrossDocumentReference] = Field(
        default_factory=list
    )
    iter: PositiveInt = Field(
        validation_alias=AliasChoices("iter", "retrieved_at_hop")
    )

    @property
    def retrieved_at_hop(self) -> int:
        """Backward-compatible accessor; new serialized output uses ``iter``."""

        return self.iter

    @model_validator(mode="after")
    def validate_evidence_id(self) -> "EvidenceHistoryItem":
        expected = f"{self.document_id}:{self.content_id}"
        if self.evidence_id != expected:
            raise ValueError(f"evidence_id must equal {expected!r}")
        if not self.content.strip() and not self.summary.strip():
            raise ValueError("evidence must contain content or summary")
        return self


class QueryHistoryItem(IterativeModel):
    """One natural-language query that was actually executed."""

    hop: PositiveInt
    query: str = Field(min_length=1)
    dense_query: str = Field(min_length=1)
    target_document: str = Field(min_length=1)
    result_count: NonNegativeInt
    evidence_ids: list[str] = Field(default_factory=list)


class IterativeSearchDecision(IterativeModel):
    """Schema-validated decision returned by the ReAct controller."""

    action: RetrievalAction
    evidence_ids: list[str] = Field(default_factory=list)
    missing_evidence: list[str] = Field(default_factory=list)
    extra_info: list[str] = Field(default_factory=list)
    actual_clear_width_calculation_ready: bool
    actual_clear_width_evidence_ids: list[str] = Field(default_factory=list)
    required_clear_width_calculation_ready: bool
    required_clear_width_evidence_ids: list[str] = Field(default_factory=list)
    query: str | None = None
    dense_query: str | None = None
    target_document: str | None = None
    reason: str = Field(min_length=1)

    @model_validator(mode="after")
    def validate_action_fields(self) -> "IterativeSearchDecision":
        if self.action is RetrievalAction.SEARCH:
            if not self.query or not self.query.strip():
                raise ValueError("search requires a non-empty query")
            if not self.dense_query or not self.dense_query.strip():
                raise ValueError("search requires a non-empty dense_query")
            if not self.target_document or not self.target_document.strip():
                raise ValueError("search requires target_document")
        elif (
            self.query is not None
            or self.dense_query is not None
            or self.target_document is not None
        ):
            raise ValueError(
                "finish and insufficient_evidence require null query, dense_query "
                "and target_document"
            )
        both_ready = (
            self.actual_clear_width_calculation_ready
            and self.required_clear_width_calculation_ready
        )
        if self.action is RetrievalAction.FINISH and not both_ready:
            raise ValueError("finish requires both clear-width evidence groups")
        if self.action is not RetrievalAction.FINISH and both_ready:
            raise ValueError("both ready evidence groups require finish")
        if (
            self.actual_clear_width_calculation_ready
            and not self.actual_clear_width_evidence_ids
        ):
            raise ValueError(
                "actual clear-width readiness requires evidence IDs"
            )
        if (
            self.required_clear_width_calculation_ready
            and not self.required_clear_width_evidence_ids
        ):
            raise ValueError(
                "required clear-width readiness requires regulation evidence IDs"
            )
        return self


class InitialQueryRewrite(IterativeModel):
    """First natural-language query and document selected before retrieval."""

    query: str = Field(min_length=1)
    dense_query: str = Field(min_length=1)
    target_document: str = Field(min_length=1)
    reason: str = Field(min_length=1)


class IterativeRetrievalState(IterativeModel):
    """Complete resumable state passed between retrieval hops."""

    task: RetrievalTask
    original_query: str = Field(min_length=1)
    ifc_context: IFCContext
    available_documents: list[str] = Field(min_length=1)
    evidence_history: list[EvidenceHistoryItem] = Field(default_factory=list)
    query_history: list[QueryHistoryItem] = Field(default_factory=list)
    extra_info: list[str] = Field(default_factory=list)
    pending_cross_document_references: list[CrossDocumentReference] = Field(
        default_factory=list
    )
    hop: NonNegativeInt = 0
    max_hops: PositiveInt

    @model_validator(mode="after")
    def validate_state(self) -> "IterativeRetrievalState":
        if self.hop > self.max_hops:
            raise ValueError("hop cannot exceed max_hops")

        document_ids = self.available_documents
        if len(document_ids) != len(set(document_ids)):
            raise ValueError("available document IDs must be unique")
        allowed_documents = set(document_ids)

        evidence_ids = [item.evidence_id for item in self.evidence_history]
        if len(evidence_ids) != len(set(evidence_ids)):
            raise ValueError("evidence IDs must be unique")
        known_evidence = set(evidence_ids)

        query_hops = [item.hop for item in self.query_history]
        if query_hops != list(range(1, len(query_hops) + 1)):
            raise ValueError("query history hops must be consecutive from 1")
        if len(query_hops) != self.hop:
            raise ValueError("hop must equal the number of executed queries")

        for item in self.query_history:
            if item.target_document not in allowed_documents:
                raise ValueError("query history contains an unavailable document")
            if not set(item.evidence_ids).issubset(known_evidence):
                raise ValueError("query history references unknown evidence IDs")
        for item in self.evidence_history:
            if item.document_id not in allowed_documents:
                raise ValueError("evidence comes from an unavailable document")
            if item.iter > self.hop:
                raise ValueError("evidence cannot come from a future hop")
        return self


class IterativeRetrievalResult(IterativeModel):
    """Terminal T3 output: evidence plus two sufficiency judgments."""

    action: Literal[
        RetrievalAction.FINISH,
        RetrievalAction.INSUFFICIENT_EVIDENCE,
    ]
    task: RetrievalTask
    original_query: str = Field(min_length=1)
    evidence_ids: list[str] = Field(default_factory=list)
    missing_evidence: list[str] = Field(default_factory=list)
    extra_info: list[str] = Field(default_factory=list)
    actual_clear_width_calculation_ready: bool
    actual_clear_width_evidence_ids: list[str] = Field(default_factory=list)
    required_clear_width_calculation_ready: bool
    required_clear_width_evidence_ids: list[str] = Field(default_factory=list)
    reason: str = Field(min_length=1)
    hop: NonNegativeInt
    query_history: list[QueryHistoryItem] = Field(default_factory=list)
    evidence_history: list[EvidenceHistoryItem] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_result(self) -> "IterativeRetrievalResult":
        known_evidence = {item.evidence_id for item in self.evidence_history}
        referenced_evidence = (
            set(self.evidence_ids)
            | set(self.actual_clear_width_evidence_ids)
            | set(self.required_clear_width_evidence_ids)
        )
        if not referenced_evidence.issubset(known_evidence):
            raise ValueError("result references unknown evidence IDs")
        if self.hop != len(self.query_history):
            raise ValueError("result hop must equal the number of executed queries")
        both_ready = (
            self.actual_clear_width_calculation_ready
            and self.required_clear_width_calculation_ready
        )
        if self.action is RetrievalAction.FINISH and not both_ready:
            raise ValueError("finish requires both clear-width evidence groups")
        if self.action is RetrievalAction.INSUFFICIENT_EVIDENCE and both_ready:
            raise ValueError("ready evidence groups require finish")
        if (
            self.actual_clear_width_calculation_ready
            and not self.actual_clear_width_evidence_ids
        ):
            raise ValueError(
                "actual clear-width readiness requires evidence IDs"
            )
        if (
            self.required_clear_width_calculation_ready
            and not self.required_clear_width_evidence_ids
        ):
            raise ValueError(
                "required clear-width readiness requires regulation evidence IDs"
            )
        return self
