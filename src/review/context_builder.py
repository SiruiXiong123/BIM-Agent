"""Convert one effective T6 door input into the existing T3 IFC context."""

from __future__ import annotations

from src.clear_width_resolver import resolve_clear_width
from src.review.models import DoorReviewInput
from src.schemas.assessment import ClassifiedEvacuationDoorRecord
from src.schemas.bim import InputValueSource
from src.search.iterative.models import IFCContext
from src.search.models import PreSearchUserInputs
from src.search.query_builder import build_retrieval_input


def build_ifc_context(review_input: DoorReviewInput) -> IFCContext:
    """Apply effective per-door values without mutating the raw T1/T2 record."""

    raw_record = review_input.candidate.record
    raw_assessment = raw_record.assessment
    if raw_assessment is None:  # Guard callers that bypassed candidate validation.
        raise ValueError("review input candidate has no T2 assessment")

    record_data = raw_record.model_dump(mode="json")
    assessment_data = raw_assessment.model_dump(mode="json")
    assessment_data.update(
        {
            "classification": review_input.effective_classification,
            "is_fire_door": review_input.is_fire_door,
        }
    )
    record_data.update(
        {
            "occupant_load": review_input.occupant_load,
            "occupant_load_source": review_input.occupant_load_source,
            "fire_resistance_grade": review_input.fire_resistance_grade,
            "fire_resistance_grade_source": (
                review_input.fire_resistance_grade_source
            ),
            "assessment": assessment_data,
        }
    )
    effective_record = ClassifiedEvacuationDoorRecord.model_validate(record_data)
    user_inputs = PreSearchUserInputs(
        occupant_load=(
            review_input.occupant_load
            if review_input.occupant_load_source is InputValueSource.USER
            else None
        ),
        fire_resistance_grade=(
            review_input.fire_resistance_grade
            if review_input.fire_resistance_grade_source
            is InputValueSource.USER
            else None
        ),
    )
    retrieval_input = build_retrieval_input(effective_record, user_inputs)
    clear_width = resolve_clear_width(effective_record)
    return IFCContext(
        subject=retrieval_input.subject,
        building_context=retrieval_input.building_context,
        door_facts=retrieval_input.door_facts,
        assessment=retrieval_input.assessment,
        clear_width_resolution=clear_width,
        missing_information=retrieval_input.missing_information,
        data_quality_warnings=effective_record.data_quality_warnings,
    )
