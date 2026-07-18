"""Tests for converting effective T6 inputs into existing T3 contexts."""

from __future__ import annotations

from src.review.context_builder import build_ifc_context
from src.review.models import (
    ClassificationSource,
    DoorReviewCandidate,
    DoorReviewInput,
)
from src.schemas.assessment import (
    ClassifiedEvacuationDoorRecord,
    EvacuationDoorClass,
    EvacuationDoorClassification,
)
from src.schemas.bim import (
    DEFAULT_FIRE_RESISTANCE_GRADE,
    ExtraInfoItem,
    InputValueSource,
    SpatialElementReference,
)


def make_candidate(
    *,
    classification: EvacuationDoorClass,
    extra_info: list[ExtraInfoItem] | None = None,
) -> DoorReviewCandidate:
    assessment = EvacuationDoorClassification(
        ifc_guid="guid-15600",
        classification=classification,
        is_fire_door=None,
        evidence=[],
        reasoning="test classification",
        missing_information=["spatial topology"],
        evacuation_door_confidence=0.8,
        model_name="test-model",
        prompt_version="test",
    )
    record = ClassifiedEvacuationDoorRecord(
        ifc_guid="guid-15600",
        door_id="Door 15600",
        name="Door 15600",
        door_type="double swing emergency door",
        type_description="test type",
        operation_type="DOUBLE_DOOR_SINGLE_SWING",
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
        extra_info=extra_info or [],
        data_quality_warnings=["No direct space boundary was available."],
        assessment=assessment,
    )
    return DoorReviewCandidate(index=1, record=record)


def test_user_confirmed_door_builds_effective_t3_context_without_mutating_raw() -> None:
    candidate = make_candidate(classification=EvacuationDoorClass.UNCERTAIN)
    review_input = DoorReviewInput(
        candidate=candidate,
        classification_source=ClassificationSource.USER_CONFIRMATION,
        is_fire_door=False,
        occupant_load=120,
        occupant_load_source=InputValueSource.USER,
        fire_resistance_grade=DEFAULT_FIRE_RESISTANCE_GRADE,
        fire_resistance_grade_source=InputValueSource.DEFAULT,
    )

    context = build_ifc_context(review_input)

    assert context.subject.door_id == "Door 15600"
    assert context.building_context.building_type == "primary_school"
    assert context.building_context.storey_name == "Ground Floor"
    assert context.building_context.storey_band == "above_ground_1_2"
    assert context.building_context.fire_resistance_grade == "一级"
    assert (
        context.building_context.fire_resistance_grade_source
        is InputValueSource.DEFAULT
    )
    assert context.door_facts.door_type == "double swing emergency door"
    assert context.door_facts.operation_type == "DOUBLE_DOOR_SINGLE_SWING"
    assert context.door_facts.overall_width == 3000
    assert context.door_facts.occupant_load == 120
    assert context.door_facts.occupant_load_source is InputValueSource.USER
    assert context.assessment.classification is EvacuationDoorClass.EVACUATION_DOOR
    assert context.assessment.is_fire_door is False
    assert context.clear_width_resolution.clear_width is None
    assert context.clear_width_resolution.method == "unavailable"
    assert "clear_width_conversion_rule" in context.missing_information
    assert candidate.raw_classification is EvacuationDoorClass.UNCERTAIN
    assert candidate.record.occupant_load == 100


def test_explicit_ifc_clear_width_is_preserved_separately_from_overall_width() -> None:
    candidate = make_candidate(
        classification=EvacuationDoorClass.EVACUATION_DOOR,
        extra_info=[
            ExtraInfoItem(
                source="Pset_DoorCommon",
                data={"Egress Width": 830},
            )
        ],
    )
    review_input = DoorReviewInput(
        candidate=candidate,
        classification_source=ClassificationSource.LLM,
        is_fire_door=False,
        occupant_load=100,
        occupant_load_source=InputValueSource.DEFAULT,
        fire_resistance_grade=DEFAULT_FIRE_RESISTANCE_GRADE,
        fire_resistance_grade_source=InputValueSource.DEFAULT,
    )

    context = build_ifc_context(review_input)

    assert context.door_facts.overall_width == 3000
    assert context.clear_width_resolution.clear_width == 830
    assert context.clear_width_resolution.source == "Pset_DoorCommon.Egress Width"
    assert context.clear_width_resolution.method == "explicit_ifc_property"
    assert "clear_width_conversion_rule" not in context.missing_information


def test_user_fire_grade_override_reaches_t3_with_user_provenance() -> None:
    candidate = make_candidate(
        classification=EvacuationDoorClass.EVACUATION_DOOR
    )
    review_input = DoorReviewInput(
        candidate=candidate,
        classification_source=ClassificationSource.LLM,
        is_fire_door=False,
        occupant_load=100,
        occupant_load_source=InputValueSource.DEFAULT,
        fire_resistance_grade=DEFAULT_FIRE_RESISTANCE_GRADE,
        fire_resistance_grade_source=InputValueSource.USER,
    )

    context = build_ifc_context(review_input)

    assert context.building_context.fire_resistance_grade == "一级"
    assert (
        context.building_context.fire_resistance_grade_source
        is InputValueSource.USER
    )
