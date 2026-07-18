"""Strict application contracts for the T6 IFC review workflow."""

from __future__ import annotations

from enum import StrEnum
from typing import Annotated, Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    model_validator,
)

from src.schemas.assessment import (
    ClassifiedEvacuationDoorRecord,
    EvacuationDoorClass,
)
from src.schemas.bim import FireResistanceGrade, InputValueSource
from src.schemas.result import CheckStatus


NonNegativeFloat = Annotated[float, Field(ge=0)]
NonNegativeInt = Annotated[int, Field(ge=0)]
PositiveInt = Annotated[int, Field(gt=0)]
DisplayCheckResult = Literal["合格", "不合格"]
EffectiveEvacuationDoorClass = Literal[EvacuationDoorClass.EVACUATION_DOOR]


class ReviewModel(BaseModel):
    """Strict base shared by all T6 application contracts."""

    model_config = ConfigDict(extra="forbid", validate_assignment=True)


class ClassificationSource(StrEnum):
    LLM = "llm"
    USER_CONFIRMATION = "user_confirmation"


class DoorReviewStatus(StrEnum):
    COMPLETED = "completed"
    SKIPPED = "skipped"
    ERROR = "error"


class ReviewStage(StrEnum):
    PARSE = "parse"
    CLASSIFY = "classify"
    AWAITING_CONFIRMATION = "awaiting_confirmation"
    T3 = "t3"
    T4 = "t4"
    T5 = "t5"
    COMPLETE = "complete"


class DoorReviewCandidate(ReviewModel):
    """One full T1/T2 record exposed through lightweight UI properties."""

    index: PositiveInt
    record: ClassifiedEvacuationDoorRecord

    @model_validator(mode="after")
    def validate_assessment(self) -> "DoorReviewCandidate":
        if self.record.assessment is None:
            raise ValueError("candidate record requires a T2 assessment")
        return self

    @property
    def door_id(self) -> str:
        return self.record.door_id

    @property
    def ifc_guid(self) -> str:
        return self.record.ifc_guid

    @property
    def building_type(self) -> str | None:
        return self.record.building

    @property
    def storey_name(self) -> str | None:
        return self.record.storey.name or self.record.storey.long_name

    @property
    def overall_width_mm(self) -> float:
        """IfcDoor.OverallWidth in millimetres; never clear width."""

        return self.record.overall_width

    @property
    def raw_classification(self) -> EvacuationDoorClass:
        assert self.record.assessment is not None
        return self.record.assessment.classification

    @property
    def raw_confidence(self) -> float | None:
        assert self.record.assessment is not None
        return self.record.assessment.evacuation_door_confidence

    @property
    def raw_is_fire_door(self) -> bool | None:
        assert self.record.assessment is not None
        return self.record.assessment.is_fire_door

    @property
    def raw_fire_door_confidence(self) -> float | None:
        assert self.record.assessment is not None
        return self.record.assessment.fire_door_confidence

    @property
    def occupant_load(self) -> int:
        return self.record.occupant_load

    @property
    def occupant_load_source(self) -> InputValueSource:
        return self.record.occupant_load_source

    @property
    def fire_resistance_grade(self) -> FireResistanceGrade | None:
        return self.record.fire_resistance_grade

    @property
    def fire_resistance_grade_source(self) -> InputValueSource | None:
        return self.record.fire_resistance_grade_source

    @property
    def data_quality_warnings(self) -> list[str]:
        return self.record.data_quality_warnings

    @property
    def requires_user_confirmation(self) -> bool:
        return self.raw_classification is EvacuationDoorClass.UNCERTAIN


class ReviewPreparation(ReviewModel):
    """T6 preparation output before uncertain-door decisions are applied."""

    project_id: str = Field(min_length=1)
    source_filename: str = Field(min_length=1)
    source_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    ifc_schema: str = Field(min_length=1)
    unit_scale_to_mm: float = Field(gt=0)
    total_ifc_door_count: NonNegativeInt
    requested_max_doors: PositiveInt | None = None
    door_count: NonNegativeInt
    candidates: list[DoorReviewCandidate] = Field(default_factory=list)
    parser_warnings: list[str] = Field(default_factory=list)
    parser_errors: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_candidates(self) -> "ReviewPreparation":
        if self.door_count != len(self.candidates):
            raise ValueError("door_count must equal the number of candidates")
        if self.door_count > self.total_ifc_door_count:
            raise ValueError("door_count cannot exceed total_ifc_door_count")
        if (
            self.requested_max_doors is not None
            and self.door_count > self.requested_max_doors
        ):
            raise ValueError("door_count cannot exceed requested_max_doors")
        guids = [item.ifc_guid for item in self.candidates]
        if len(guids) != len(set(guids)):
            raise ValueError("candidate ifc_guid values must be unique")
        door_ids = [item.door_id for item in self.candidates]
        if len(door_ids) != len(set(door_ids)):
            raise ValueError("candidate door_id values must be unique")
        indexes = [item.index for item in self.candidates]
        if indexes != list(range(1, len(indexes) + 1)):
            raise ValueError("candidate indexes must be consecutive from 1")
        return self

    @property
    def confirmed_evacuation_door_count(self) -> int:
        return sum(
            item.raw_classification is EvacuationDoorClass.EVACUATION_DOOR
            for item in self.candidates
        )

    @property
    def uncertain_door_count(self) -> int:
        return sum(item.requires_user_confirmation for item in self.candidates)

    @property
    def non_evacuation_door_count(self) -> int:
        return sum(
            item.raw_classification
            is EvacuationDoorClass.NON_EVACUATION_DOOR
            for item in self.candidates
        )


class ReviewSelection(ReviewModel):
    """Auditable user choices applied after preparation."""

    included_uncertain_door_ids: list[str] = Field(default_factory=list)
    occupant_load_overrides: dict[str, PositiveInt] = Field(default_factory=dict)
    fire_resistance_grade_overrides: dict[str, FireResistanceGrade] = Field(
        default_factory=dict
    )

    @model_validator(mode="after")
    def validate_door_keys(self) -> "ReviewSelection":
        selected = [item.strip() for item in self.included_uncertain_door_ids]
        if any(not item for item in selected):
            raise ValueError("included uncertain door IDs cannot be empty")
        if len(selected) != len(set(selected)):
            raise ValueError("included uncertain door IDs must be unique")
        override_keys = (
            list(self.occupant_load_overrides)
            + list(self.fire_resistance_grade_overrides)
        )
        if any(not item.strip() for item in override_keys):
            raise ValueError("override door IDs cannot be empty")
        # Avoid re-entering assignment validation from an ``after`` validator.
        object.__setattr__(self, "included_uncertain_door_ids", selected)
        return self


class DoorReviewInput(ReviewModel):
    """One effective evacuation-door input passed to the T3–T5 runner."""

    candidate: DoorReviewCandidate
    effective_classification: EffectiveEvacuationDoorClass = (
        EvacuationDoorClass.EVACUATION_DOOR
    )
    classification_source: ClassificationSource
    is_fire_door: bool
    occupant_load: PositiveInt
    occupant_load_source: InputValueSource
    fire_resistance_grade: FireResistanceGrade
    fire_resistance_grade_source: InputValueSource

    @model_validator(mode="after")
    def validate_classification_audit(self) -> "DoorReviewInput":
        raw = self.candidate.raw_classification
        if raw is EvacuationDoorClass.EVACUATION_DOOR:
            if self.classification_source is not ClassificationSource.LLM:
                raise ValueError(
                    "a confirmed evacuation door requires classification_source=llm"
                )
        elif raw is EvacuationDoorClass.UNCERTAIN:
            if (
                self.classification_source
                is not ClassificationSource.USER_CONFIRMATION
            ):
                raise ValueError(
                    "an uncertain door requires user_confirmation before review"
                )
        else:
            raise ValueError("a non-evacuation door cannot enter the review runner")
        return self


class DoorReviewResult(ReviewModel):
    """One final, skipped, or failed door outcome presented by T6."""

    door_id: str = Field(min_length=1)
    ifc_guid: str = Field(min_length=1)
    raw_classification: EvacuationDoorClass
    effective_classification: EffectiveEvacuationDoorClass | None = None
    classification_source: ClassificationSource | None = None
    overall_width_mm: NonNegativeFloat
    actual_clear_width_mm: NonNegativeFloat | None = None
    required_clear_width_mm: NonNegativeFloat | None = None
    machine_result: CheckStatus | None = None
    display_result: DisplayCheckResult | None = None
    detailed_reason: str | None = None
    evidence_ids: list[str] = Field(default_factory=list)
    t3_cache_hit: bool = False
    t4_cache_hit: bool = False
    status: DoorReviewStatus
    error: str | None = None

    @model_validator(mode="after")
    def validate_outcome(self) -> "DoorReviewResult":
        if len(self.evidence_ids) != len(set(self.evidence_ids)):
            raise ValueError("result evidence IDs must be unique")
        if self.status is DoorReviewStatus.COMPLETED:
            required = (
                self.effective_classification,
                self.classification_source,
                self.actual_clear_width_mm,
                self.required_clear_width_mm,
                self.machine_result,
                self.display_result,
                self.detailed_reason,
            )
            if any(item is None for item in required):
                raise ValueError("a completed review requires all result fields")
            if self.machine_result not in {CheckStatus.PASS, CheckStatus.FAIL}:
                raise ValueError("a completed review requires PASS or FAIL")
            expected: DisplayCheckResult = (
                "合格" if self.machine_result is CheckStatus.PASS else "不合格"
            )
            if self.display_result != expected:
                raise ValueError(
                    "display_result must match the deterministic machine result"
                )
            if not self.detailed_reason or not self.detailed_reason.strip():
                raise ValueError("a completed review requires detailed_reason")
            if self.error is not None:
                raise ValueError("a completed review cannot contain an error")
        elif self.status is DoorReviewStatus.SKIPPED:
            if any(
                item is not None
                for item in (
                    self.actual_clear_width_mm,
                    self.required_clear_width_mm,
                    self.machine_result,
                    self.display_result,
                )
            ):
                raise ValueError("a skipped door cannot contain a check result")
        elif not self.error or not self.error.strip():
            raise ValueError("an error result requires an error message")
        return self


class ReviewBatchResult(ReviewModel):
    """Serializable result for one uploaded IFC review session."""

    project_id: str = Field(min_length=1)
    source_filename: str = Field(min_length=1)
    total_doors: NonNegativeInt
    results: list[DoorReviewResult] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_results(self) -> "ReviewBatchResult":
        if self.total_doors != len(self.results):
            raise ValueError("total_doors must equal the number of results")
        guids = [item.ifc_guid for item in self.results]
        if len(guids) != len(set(guids)):
            raise ValueError("result ifc_guid values must be unique")
        return self

    @property
    def reviewed_doors(self) -> int:
        return sum(item.status is DoorReviewStatus.COMPLETED for item in self.results)

    @property
    def passed_doors(self) -> int:
        return sum(item.machine_result is CheckStatus.PASS for item in self.results)

    @property
    def failed_doors(self) -> int:
        return sum(item.machine_result is CheckStatus.FAIL for item in self.results)

    @property
    def skipped_doors(self) -> int:
        return sum(item.status is DoorReviewStatus.SKIPPED for item in self.results)

    @property
    def error_doors(self) -> int:
        return sum(item.status is DoorReviewStatus.ERROR for item in self.results)


class ReviewProgressEvent(ReviewModel):
    """Framework-neutral progress update emitted by the future ReviewService."""

    stage: ReviewStage
    current: NonNegativeInt
    total: NonNegativeInt
    door_id: str | None = None
    message: str = Field(min_length=1)

    @model_validator(mode="after")
    def validate_progress(self) -> "ReviewProgressEvent":
        if self.current > self.total:
            raise ValueError("progress current cannot exceed total")
        return self
