"""Deterministic clear-width resolution and compliance assessment."""

from __future__ import annotations

from src.schemas.assessment import (
    ClassifiedEvacuationDoorRecord,
    ClearWidthResolution,
    EvacuationDoorClass,
    EvacuationDoorAssessment,
    EvacuationDoorClassification,
)
from src.schemas.bim import Door
from src.schemas.result import CheckStatus


WIDTH_PRIORITY = (
    "Egress Width",
    "Clear Width",
)


def resolve_clear_width(
    door: Door | ClassifiedEvacuationDoorRecord,
) -> ClearWidthResolution:
    """Resolve an explicit clear-width fact without treating OverallWidth as clear."""

    for field_name in WIDTH_PRIORITY:
        for item in door.extra_info:
            value = _case_insensitive_get(item.data, field_name)
            if isinstance(value, (int, float)) and not isinstance(value, bool):
                if value < 0:
                    continue
                return ClearWidthResolution(
                    ifc_guid=door.ifc_guid,
                    clear_width=float(value),
                    source=f"{item.source}.{field_name}",
                    method="explicit_ifc_property",
                )

    return ClearWidthResolution(
        ifc_guid=door.ifc_guid,
        clear_width=None,
        source=None,
        method="unavailable",
        warnings=[
            "No explicit Egress Width or Clear Width was found; OverallWidth was not used."
        ],
    )


def assess_evacuation_door(
    classification: EvacuationDoorClassification,
    width: ClearWidthResolution,
    *,
    required_width: float,
) -> EvacuationDoorAssessment:
    """Compare resolved width to a requirement only when classification is true."""

    warnings = list(width.warnings)
    if classification.classification is not EvacuationDoorClass.EVACUATION_DOOR:
        status = CheckStatus.UNKNOWN
        warnings.append("Door is not confirmed as an evacuation door; width not assessed.")
    elif width.clear_width is None:
        status = CheckStatus.UNKNOWN
    elif width.clear_width >= required_width:
        status = CheckStatus.PASS
    else:
        status = CheckStatus.FAIL

    return EvacuationDoorAssessment(
        ifc_guid=classification.ifc_guid,
        classification=classification.classification,
        clear_width=width.clear_width,
        clear_width_source=width.source,
        required_width=required_width,
        status=status,
        evidence=classification.evidence,
        warnings=warnings,
    )


def _case_insensitive_get(data: dict[str, object], name: str) -> object | None:
    expected = name.casefold()
    for key, value in data.items():
        if key.casefold() == expected:
            return value
    return None
