"""Build one complete regulation-retrieval intent from a classified door."""

from __future__ import annotations

from src.schemas.assessment import ClassifiedEvacuationDoorRecord
from src.search.config import SearchConfig
from src.search.models import (
    DEFAULT_RETRIEVAL_TASK,
    RegulationRetrievalInput,
    RegulationSearchRequest,
    RetrievalAssessment,
    RetrievalBuildingContext,
    RetrievalContext,
    RetrievalDoorFacts,
    RetrievalSubject,
    PreSearchUserInputs,
)
from src.search.input_resolver import resolve_pre_search_inputs

def build_retrieval_input(
    record: ClassifiedEvacuationDoorRecord,
    user_inputs: PreSearchUserInputs | None = None,
) -> RegulationRetrievalInput:
    """Select facts relevant to regulation retrieval from one enriched row."""

    if record.assessment is None:
        raise ValueError("classified door record has no assessment")
    resolved = resolve_pre_search_inputs(record, user_inputs)
    missing = _missing_information(record)
    return RegulationRetrievalInput(
        subject=RetrievalSubject(
            ifc_guid=record.ifc_guid,
            door_id=record.door_id,
        ),
        building_context=RetrievalBuildingContext(
            building_type=record.building,
            storey_name=record.storey.name,
            storey_elevation=record.storey.elevation,
            storey_band=resolved.storey_band,
            fire_resistance_grade=resolved.fire_resistance_grade,
            fire_resistance_grade_source=resolved.fire_resistance_grade_source,
        ),
        door_facts=RetrievalDoorFacts(
            name=record.name,
            door_type=record.door_type,
            operation_type=record.operation_type,
            overall_width=record.overall_width,
            overall_height=record.overall_height,
            occupant_load=resolved.occupant_load,
            occupant_load_source=resolved.occupant_load_source,
            dimension_unit=record.dimension_unit,
            adjacent_spaces=record.adjacent_spaces,
            extra_info=record.extra_info,
        ),
        assessment=RetrievalAssessment(
            classification=record.assessment.classification,
            evacuation_door_confidence=(
                record.assessment.evacuation_door_confidence
            ),
            # Retrieval consumes one resolved fact.  Preserve the classifier's
            # nullable raw judgment upstream, but apply the project fallback
            # before any query rewriter or controller sees the assessment.
            is_fire_door=record.assessment.is_fire_door is True,
            evidence=record.assessment.evidence,
        ),
        missing_information=missing,
        task=DEFAULT_RETRIEVAL_TASK,
    )


def build_search_request(
    retrieval_input: RegulationRetrievalInput,
    config: SearchConfig,
) -> RegulationSearchRequest:
    """Build one query; later iterative retrieval may decide further queries."""

    context = retrieval_input.building_context
    parts = [
        context.building_type or "",
        context.storey_name or "",
        context.storey_band,
        context.fire_resistance_grade,
        retrieval_input.subject.component_type,
        retrieval_input.assessment.classification.value,
    ]
    query_text = " ".join(dict.fromkeys(part for part in parts if part))
    return RegulationSearchRequest(
        task=retrieval_input.task,
        door_id=retrieval_input.subject.door_id,
        query_text=query_text,
        candidate_k=config.default_candidate_k,
        top_k=config.default_top_k,
        retrieval_context=RetrievalContext(
            building_type=context.building_type,
            classification=retrieval_input.assessment.classification,
            storey=context.storey_name,
            storey_band=context.storey_band,
            fire_resistance_grade=context.fire_resistance_grade,
        ),
    )


def _missing_information(record: ClassifiedEvacuationDoorRecord) -> list[str]:
    assert record.assessment is not None
    missing = [
        item
        for item in record.assessment.missing_information
        if not _is_resolved_fire_door_missing_information(item)
    ]
    if not _has_explicit_clear_width(record):
        missing.insert(0, "clear_width_conversion_rule")
    return list(dict.fromkeys(missing))


def _is_resolved_fire_door_missing_information(item: str) -> bool:
    """Exclude fire-door facts resolved by the configured retrieval default."""

    normalized = item.casefold().replace("_", " ")
    return any(
        marker in normalized
        for marker in ("fire rating", "firerating", "fire door", "防火门")
    )


def _has_explicit_clear_width(record: ClassifiedEvacuationDoorRecord) -> bool:
    width_keys = {"egress width", "clear width", "egress dimensions"}
    return any(
        str(key).strip().casefold() in width_keys
        for item in record.extra_info
        for key in item.data
    )
