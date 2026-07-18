"""Schemas shared by the regulation search module."""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from src.schemas.assessment import (
    ClassificationEvidence,
    EvacuationDoorClass,
)
from src.schemas.bim import (
    DEFAULT_DOOR_OCCUPANT_LOAD,
    DEFAULT_FIRE_RESISTANCE_GRADE,
    DoorSpaceBoundary,
    ExtraInfoItem,
    FireResistanceGrade,
    InputValueSource,
)


PositiveInt = Annotated[int, Field(gt=0)]
RetrievalTask = Annotated[str, Field(min_length=1)]
DEFAULT_RETRIEVAL_TASK = (
    "收集能判断疏散门净宽是否符合适用规范的相关信息但不做任何判断"
)


class RetrievalSubject(BaseModel):
    model_config = ConfigDict(extra="forbid")

    ifc_guid: str = Field(min_length=1)
    door_id: str = Field(min_length=1)
    component_type: Literal["door"] = "door"


class RetrievalBuildingContext(BaseModel):
    model_config = ConfigDict(extra="forbid")

    building_type: str | None = None
    storey_name: str | None = None
    storey_elevation: float | None = None
    storey_band: Literal[
        "above_ground_1_2",
        "above_ground_3",
        "above_ground_4_5",
        "below_ground_1_2",
        "unknown",
    ] = "unknown"
    fire_resistance_grade: FireResistanceGrade = DEFAULT_FIRE_RESISTANCE_GRADE
    fire_resistance_grade_source: InputValueSource = InputValueSource.DEFAULT


class RetrievalDoorFacts(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1)
    door_type: str = Field(min_length=1)
    operation_type: str = Field(min_length=1)
    overall_width: float = Field(ge=0)
    overall_height: float = Field(ge=0)
    occupant_load: PositiveInt = DEFAULT_DOOR_OCCUPANT_LOAD
    occupant_load_source: InputValueSource = InputValueSource.DEFAULT
    dimension_unit: Literal["mm"] = "mm"
    adjacent_spaces: list[DoorSpaceBoundary] = Field(default_factory=list)
    extra_info: list[ExtraInfoItem] = Field(default_factory=list)


class RetrievalAssessment(BaseModel):
    model_config = ConfigDict(extra="forbid")

    classification: EvacuationDoorClass
    evacuation_door_confidence: Annotated[float, Field(ge=0, le=1)] | None = None
    is_fire_door: bool
    evidence: list[ClassificationEvidence] = Field(default_factory=list)


class RegulationRetrievalInput(BaseModel):
    """Structured door context used to construct one retrieval intent."""

    model_config = ConfigDict(extra="forbid")

    subject: RetrievalSubject
    building_context: RetrievalBuildingContext
    door_facts: RetrievalDoorFacts
    assessment: RetrievalAssessment
    missing_information: list[str] = Field(default_factory=list)
    task: RetrievalTask


class PreSearchUserInputs(BaseModel):
    """Optional values accepted before query rewriting when IFC facts are absent."""

    model_config = ConfigDict(extra="forbid")

    occupant_load: PositiveInt | None = None
    fire_resistance_grade: FireResistanceGrade | None = None


class RetrievalContext(BaseModel):
    model_config = ConfigDict(extra="forbid")

    building_type: str | None = None
    component_type: Literal["door"] = "door"
    classification: EvacuationDoorClass
    storey: str | None = None
    storey_band: str | None = None
    fire_resistance_grade: FireResistanceGrade | None = None


class RegulationSearchRequest(BaseModel):
    """Single complete query passed to the hybrid retrieval layer."""

    model_config = ConfigDict(extra="forbid")

    task: RetrievalTask
    door_id: str = Field(min_length=1)
    query_text: str = Field(min_length=1)
    candidate_k: PositiveInt
    top_k: PositiveInt
    retrieval_context: RetrievalContext

    @model_validator(mode="after")
    def validate_limits(self) -> "RegulationSearchRequest":
        if self.candidate_k < self.top_k:
            raise ValueError("candidate_k must be greater than or equal to top_k")
        return self


ContentType = Literal["text", "table", "image"]


class CrossDocumentReference(BaseModel):
    """Explicit offline mapping from one evidence item to referenced content."""

    model_config = ConfigDict(extra="forbid")

    target_document: str = Field(min_length=1)
    target_locator: str = Field(min_length=1)


class SearchHit(BaseModel):
    """One traceable regulation item returned by any retriever."""

    model_config = ConfigDict(extra="allow")

    id: str = Field(min_length=1)
    document_id: str = Field(min_length=1)
    modality: ContentType
    rank: PositiveInt
    score: float
    page: int | None = None
    title: str | None = None
    content: str = ""
    summary: str = ""
    asset_path: str | None = None
    hash: str | None = None
    faiss_id: int | None = None
    bm25_score: float | None = None
    dense_score: float | None = None
    rrf_score: float | None = None
    retrievers: list[Literal["bm25", "dense"]] = Field(default_factory=list)
    cross_document_references: list[CrossDocumentReference] = Field(
        default_factory=list
    )
