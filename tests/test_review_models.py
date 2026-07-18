"""Tests for the framework-neutral T6 review contracts."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from src.review.models import (
    ClassificationSource,
    DoorReviewCandidate,
    DoorReviewInput,
    DoorReviewResult,
    DoorReviewStatus,
    ReviewBatchResult,
    ReviewPreparation,
    ReviewProgressEvent,
    ReviewSelection,
    ReviewStage,
)
from src.schemas.assessment import (
    ClassifiedEvacuationDoorRecord,
    EvacuationDoorClass,
    EvacuationDoorClassification,
)
from src.schemas.bim import (
    DEFAULT_FIRE_RESISTANCE_GRADE,
    InputValueSource,
    SpatialElementReference,
)
from src.schemas.result import CheckStatus


def make_candidate(
    *,
    index: int = 1,
    door_id: str = "Door 15600",
    ifc_guid: str = "guid-15600",
    classification: EvacuationDoorClass = EvacuationDoorClass.EVACUATION_DOOR,
) -> DoorReviewCandidate:
    assessment = EvacuationDoorClassification(
        ifc_guid=ifc_guid,
        classification=classification,
        is_fire_door=False,
        reasoning="test classification",
        evacuation_door_confidence=0.91,
        model_name="test-model",
        prompt_version="test",
    )
    record = ClassifiedEvacuationDoorRecord(
        ifc_guid=ifc_guid,
        door_id=door_id,
        name=door_id,
        door_type="test door",
        operation_type="SINGLE_SWING_LEFT",
        building="primary_school",
        storey=SpatialElementReference(
            ifc_class="IfcBuildingStorey",
            name="Ground Floor",
            elevation=0,
        ),
        overall_width=3000,
        overall_height=2700,
        occupant_load=100,
        occupant_load_source=InputValueSource.DEFAULT,
        fire_resistance_grade=DEFAULT_FIRE_RESISTANCE_GRADE,
        fire_resistance_grade_source=InputValueSource.DEFAULT,
        assessment=assessment,
    )
    return DoorReviewCandidate(
        index=index,
        record=record,
    )


def make_completed_result(
    *,
    door_id: str = "Door 15600",
    ifc_guid: str = "guid-15600",
    machine_result: CheckStatus = CheckStatus.PASS,
) -> DoorReviewResult:
    return DoorReviewResult(
        door_id=door_id,
        ifc_guid=ifc_guid,
        raw_classification=EvacuationDoorClass.EVACUATION_DOOR,
        effective_classification=EvacuationDoorClass.EVACUATION_DOOR,
        classification_source=ClassificationSource.LLM,
        overall_width_mm=3000,
        actual_clear_width_mm=2900,
        required_clear_width_mm=700,
        machine_result=machine_result,
        display_result="合格" if machine_result is CheckStatus.PASS else "不合格",
        detailed_reason="实际净宽 2900 mm 大于等于规范阈值 700 mm。",
        evidence_ids=["doc-a:table_000031", "doc-b:table_000012"],
        status=DoorReviewStatus.COMPLETED,
    )


def test_preparation_is_serializable_and_reports_classification_counts() -> None:
    candidates = [
        make_candidate(),
        make_candidate(
            index=2,
            door_id="Door 2",
            ifc_guid="guid-2",
            classification=EvacuationDoorClass.UNCERTAIN,
        ),
        make_candidate(
            index=3,
            door_id="Door 3",
            ifc_guid="guid-3",
            classification=EvacuationDoorClass.NON_EVACUATION_DOOR,
        ),
    ]
    preparation = ReviewPreparation(
        project_id="project-school",
        source_filename="school.ifc",
        source_sha256="a" * 64,
        ifc_schema="IFC2X3",
        unit_scale_to_mm=1,
        total_ifc_door_count=3,
        door_count=3,
        candidates=candidates,
    )

    assert preparation.confirmed_evacuation_door_count == 1
    assert preparation.uncertain_door_count == 1
    assert preparation.non_evacuation_door_count == 1
    assert candidates[1].requires_user_confirmation is True
    assert ReviewPreparation.model_validate_json(preparation.model_dump_json()) == preparation


@pytest.mark.parametrize(
    ("candidates", "door_count", "message"),
    [
        ([make_candidate()], 2, "door_count"),
        (
            [make_candidate(), make_candidate(index=2, door_id="Door 2")],
            2,
            "ifc_guid",
        ),
        (
            [make_candidate(), make_candidate(index=2, ifc_guid="guid-2")],
            2,
            "door_id",
        ),
        (
            [make_candidate(index=2)],
            1,
            "consecutive",
        ),
    ],
)
def test_preparation_rejects_inconsistent_candidates(
    candidates: list[DoorReviewCandidate], door_count: int, message: str
) -> None:
    with pytest.raises(ValidationError, match=message):
        ReviewPreparation(
            project_id="project-school",
            source_filename="school.ifc",
            source_sha256="a" * 64,
            ifc_schema="IFC2X3",
            unit_scale_to_mm=1,
            total_ifc_door_count=max(door_count, len(candidates)),
            door_count=door_count,
            candidates=candidates,
        )


def test_selection_normalizes_ids_and_validates_overrides() -> None:
    selection = ReviewSelection(
        included_uncertain_door_ids=[" Door 1 ", "Door 2"],
        occupant_load_overrides={"Door 1": 120},
        fire_resistance_grade_overrides={
            "Door 2": DEFAULT_FIRE_RESISTANCE_GRADE
        },
    )
    assert selection.included_uncertain_door_ids == ["Door 1", "Door 2"]

    with pytest.raises(ValidationError, match="unique"):
        ReviewSelection(included_uncertain_door_ids=["Door 1", " Door 1 "])
    with pytest.raises(ValidationError):
        ReviewSelection(occupant_load_overrides={"Door 1": 0})


def test_review_input_preserves_raw_and_effective_classification_audit() -> None:
    confirmed = DoorReviewInput(
        candidate=make_candidate(),
        classification_source=ClassificationSource.LLM,
        is_fire_door=False,
        occupant_load=100,
        occupant_load_source=InputValueSource.DEFAULT,
        fire_resistance_grade=DEFAULT_FIRE_RESISTANCE_GRADE,
        fire_resistance_grade_source=InputValueSource.DEFAULT,
    )
    assert confirmed.candidate.raw_classification is EvacuationDoorClass.EVACUATION_DOOR

    uncertain = DoorReviewInput(
        candidate=make_candidate(classification=EvacuationDoorClass.UNCERTAIN),
        classification_source=ClassificationSource.USER_CONFIRMATION,
        is_fire_door=False,
        occupant_load=100,
        occupant_load_source=InputValueSource.DEFAULT,
        fire_resistance_grade=DEFAULT_FIRE_RESISTANCE_GRADE,
        fire_resistance_grade_source=InputValueSource.DEFAULT,
    )
    assert uncertain.candidate.raw_classification is EvacuationDoorClass.UNCERTAIN
    assert uncertain.effective_classification is EvacuationDoorClass.EVACUATION_DOOR

    with pytest.raises(ValidationError, match="user_confirmation"):
        DoorReviewInput(
            candidate=make_candidate(classification=EvacuationDoorClass.UNCERTAIN),
            classification_source=ClassificationSource.LLM,
            is_fire_door=False,
            occupant_load=100,
            occupant_load_source=InputValueSource.DEFAULT,
            fire_resistance_grade=DEFAULT_FIRE_RESISTANCE_GRADE,
            fire_resistance_grade_source=InputValueSource.DEFAULT,
        )
    with pytest.raises(ValidationError, match="non-evacuation"):
        DoorReviewInput(
            candidate=make_candidate(
                classification=EvacuationDoorClass.NON_EVACUATION_DOOR
            ),
            classification_source=ClassificationSource.LLM,
            is_fire_door=False,
            occupant_load=100,
            occupant_load_source=InputValueSource.DEFAULT,
            fire_resistance_grade=DEFAULT_FIRE_RESISTANCE_GRADE,
            fire_resistance_grade_source=InputValueSource.DEFAULT,
        )


def test_completed_result_keeps_overall_and_clear_width_distinct() -> None:
    result = make_completed_result()
    restored = DoorReviewResult.model_validate_json(result.model_dump_json())

    assert restored.overall_width_mm == 3000
    assert restored.actual_clear_width_mm == 2900
    assert restored.display_result == "合格"


def test_result_state_contracts_reject_inconsistent_outputs() -> None:
    payload = make_completed_result().model_dump()
    payload["display_result"] = "不合格"
    with pytest.raises(ValidationError, match="deterministic machine result"):
        DoorReviewResult.model_validate(payload)

    payload = make_completed_result().model_dump()
    payload["actual_clear_width_mm"] = None
    with pytest.raises(ValidationError, match="all result fields"):
        DoorReviewResult.model_validate(payload)

    with pytest.raises(ValidationError, match="cannot contain a check result"):
        DoorReviewResult(
            door_id="Door 1",
            ifc_guid="guid-1",
            raw_classification=EvacuationDoorClass.UNCERTAIN,
            overall_width_mm=900,
            actual_clear_width_mm=800,
            status=DoorReviewStatus.SKIPPED,
        )

    with pytest.raises(ValidationError, match="error message"):
        DoorReviewResult(
            door_id="Door 1",
            ifc_guid="guid-1",
            raw_classification=EvacuationDoorClass.EVACUATION_DOOR,
            overall_width_mm=900,
            status=DoorReviewStatus.ERROR,
        )


def test_batch_counts_results_and_rejects_duplicate_guids() -> None:
    passed = make_completed_result()
    failed = make_completed_result(
        door_id="Door 2", ifc_guid="guid-2", machine_result=CheckStatus.FAIL
    )
    skipped = DoorReviewResult(
        door_id="Door 3",
        ifc_guid="guid-3",
        raw_classification=EvacuationDoorClass.UNCERTAIN,
        overall_width_mm=900,
        status=DoorReviewStatus.SKIPPED,
    )
    batch = ReviewBatchResult(
        project_id="project-school",
        source_filename="school.ifc",
        total_doors=3,
        results=[passed, failed, skipped],
    )

    assert batch.reviewed_doors == 2
    assert batch.passed_doors == 1
    assert batch.failed_doors == 1
    assert batch.skipped_doors == 1
    assert batch.error_doors == 0

    with pytest.raises(ValidationError, match="ifc_guid"):
        ReviewBatchResult(
            project_id="project-school",
            source_filename="school.ifc",
            total_doors=2,
            results=[passed, make_completed_result(door_id="Door duplicate")],
        )


def test_progress_and_strict_extra_field_contracts() -> None:
    event = ReviewProgressEvent(
        stage=ReviewStage.T3,
        current=1,
        total=4,
        door_id="Door 15600",
        message="正在检索规范证据",
    )
    assert event.current == 1

    with pytest.raises(ValidationError, match="cannot exceed"):
        ReviewProgressEvent(
            stage=ReviewStage.T3,
            current=5,
            total=4,
            message="invalid",
        )
    with pytest.raises(ValidationError, match="Extra inputs"):
        ReviewSelection.model_validate({"unexpected": True})
