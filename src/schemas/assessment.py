"""AI classification and deterministic evacuation-door assessment schemas."""

from enum import StrEnum
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from src.schemas.bim import (
    DEFAULT_DOOR_OCCUPANT_LOAD,
    DoorSpaceBoundary,
    ExtraInfoItem,
    FireResistanceGrade,
    InputValueSource,
    SpatialElementReference,
)
from src.schemas.result import CheckStatus


NonNegativeFloat = Annotated[float, Field(ge=0)]


class EvacuationDoorClass(StrEnum):
    EVACUATION_DOOR = "evacuation_door"
    NON_EVACUATION_DOOR = "non_evacuation_door"
    UNCERTAIN = "uncertain"


class EvidenceImpact(StrEnum):
    POSITIVE = "positive"
    NEGATIVE = "negative"
    NEUTRAL = "neutral"


class ClassificationEvidence(BaseModel):
    """One auditable input fact cited by an LLM classification."""

    model_config = ConfigDict(extra="forbid", validate_assignment=True)

    field: str = Field(min_length=1)
    value: Any = None
    impact: EvidenceImpact


class EvacuationDoorClassificationInput(BaseModel):
    """Minimal IFC fact view sent to the evacuation-door classifier."""

    model_config = ConfigDict(extra="forbid", validate_assignment=True)

    ifc_guid: str = Field(min_length=1)
    door_id: str = Field(min_length=1)
    name: str = Field(min_length=1)
    door_type: str = Field(min_length=1)
    type_description: str | None = None
    operation_type: str = Field(min_length=1)
    building: str | None = None
    storey: SpatialElementReference
    overall_width: NonNegativeFloat
    overall_height: NonNegativeFloat
    occupant_load: Annotated[int, Field(gt=0)] = DEFAULT_DOOR_OCCUPANT_LOAD
    occupant_load_source: InputValueSource = InputValueSource.DEFAULT
    fire_resistance_grade: FireResistanceGrade | None = None
    fire_resistance_grade_source: InputValueSource | None = None
    dimension_unit: Literal["mm"] = "mm"
    adjacent_spaces: list[DoorSpaceBoundary] = Field(default_factory=list)
    extra_info: list[ExtraInfoItem] = Field(default_factory=list)
    data_quality_warnings: list[str] = Field(default_factory=list)


class EvacuationDoorClassification(BaseModel):
    """Auditable LLM judgments about evacuation and fire-door semantics."""

    model_config = ConfigDict(extra="forbid", validate_assignment=True)

    ifc_guid: str = Field(min_length=1)
    classification: EvacuationDoorClass
    is_fire_door: bool | None = None
    evidence: list[ClassificationEvidence] = Field(default_factory=list)
    reasoning: str = Field(min_length=1)
    missing_information: list[str] = Field(default_factory=list)
    evacuation_door_confidence: Annotated[float, Field(ge=0, le=1)] | None = None
    fire_door_confidence: Annotated[float, Field(ge=0, le=1)] | None = None
    model_name: str = Field(min_length=1)
    prompt_version: str = Field(min_length=1)

    @model_validator(mode="before")
    @classmethod
    def migrate_legacy_confidence(cls, data: Any) -> Any:
        """Read historical classifier output while always emitting the new schema."""

        if isinstance(data, dict) and "confidence" in data:
            data = dict(data)
            data.setdefault("evacuation_door_confidence", data.pop("confidence"))
        return data


class ClassifiedEvacuationDoorRecord(EvacuationDoorClassificationInput):
    """Classifier input facts enriched with the auditable LLM result."""

    assessment: EvacuationDoorClassification | None = None

    @model_validator(mode="after")
    def validate_assessment_identity(self) -> "ClassifiedEvacuationDoorRecord":
        if self.assessment is not None and self.assessment.ifc_guid != self.ifc_guid:
            raise ValueError("assessment.ifc_guid must match the door ifc_guid")
        return self


class ClearWidthResolution(BaseModel):
    """Explicit clear-width fact resolved before regulation retrieval."""

    model_config = ConfigDict(extra="forbid", validate_assignment=True)

    ifc_guid: str = Field(min_length=1)
    clear_width: NonNegativeFloat | None = Field(
        default=None, description="Clear width in millimetres."
    )
    source: str | None = None
    method: str = Field(min_length=1)
    warnings: list[str] = Field(default_factory=list)


class EvacuationDoorAssessment(BaseModel):
    """Combined classification, width evidence, and deterministic check result."""

    model_config = ConfigDict(extra="forbid", validate_assignment=True)

    ifc_guid: str = Field(min_length=1)
    classification: EvacuationDoorClass
    clear_width: NonNegativeFloat | None = Field(
        default=None, description="Resolved clear width in millimetres."
    )
    clear_width_source: str | None = None
    required_width: NonNegativeFloat | None = Field(
        default=None, description="Required clear width in millimetres."
    )
    status: CheckStatus
    evidence: list[ClassificationEvidence] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
