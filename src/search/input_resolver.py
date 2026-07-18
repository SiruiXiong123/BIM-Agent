"""Resolve IFC, user and default inputs before regulation search."""

from __future__ import annotations

import re
import unicodedata

from pydantic import BaseModel, ConfigDict

from src.schemas.assessment import ClassifiedEvacuationDoorRecord
from src.schemas.bim import (
    DEFAULT_DOOR_OCCUPANT_LOAD,
    DEFAULT_FIRE_RESISTANCE_GRADE,
    FireResistanceGrade,
    InputValueSource,
)
from src.search.models import PreSearchUserInputs


class ResolvedPreSearchInputs(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    occupant_load: int
    occupant_load_source: InputValueSource
    fire_resistance_grade: FireResistanceGrade
    fire_resistance_grade_source: InputValueSource
    storey_band: str


def resolve_pre_search_inputs(
    record: ClassifiedEvacuationDoorRecord,
    user_inputs: PreSearchUserInputs | None = None,
) -> ResolvedPreSearchInputs:
    """Apply IFC > user > configured default precedence."""

    supplied = user_inputs or PreSearchUserInputs()
    if record.occupant_load_source == InputValueSource.IFC:
        occupant_load = record.occupant_load
        occupant_source = InputValueSource.IFC
    elif supplied.occupant_load is not None:
        occupant_load = supplied.occupant_load
        occupant_source = InputValueSource.USER
    else:
        occupant_load = DEFAULT_DOOR_OCCUPANT_LOAD
        occupant_source = InputValueSource.DEFAULT

    if (
        record.fire_resistance_grade is not None
        and record.fire_resistance_grade_source == InputValueSource.IFC
    ):
        fire_grade = record.fire_resistance_grade
        fire_grade_source = InputValueSource.IFC
    elif supplied.fire_resistance_grade is not None:
        fire_grade = supplied.fire_resistance_grade
        fire_grade_source = InputValueSource.USER
    else:
        fire_grade = DEFAULT_FIRE_RESISTANCE_GRADE
        fire_grade_source = InputValueSource.DEFAULT

    return ResolvedPreSearchInputs(
        occupant_load=occupant_load,
        occupant_load_source=occupant_source,
        fire_resistance_grade=fire_grade,
        fire_resistance_grade_source=fire_grade_source,
        storey_band=resolve_storey_band(
            record.storey.name,
            record.storey.elevation,
        ),
    )


def resolve_storey_band(name: str | None, elevation_mm: float | None) -> str:
    """Normalize an IFC storey for regulation lookup selectors."""

    normalized = unicodedata.normalize("NFKC", str(name or "")).casefold()
    compact = re.sub(r"[\s_.-]+", "", normalized)
    if (elevation_mm is not None and elevation_mm < 0) or any(
        marker in compact for marker in ("basement", "地下", "b1", "b2")
    ):
        return "below_ground_1_2"
    if any(marker in compact for marker in ("groundfloor", "firstfloor", "1层", "一层", "二层", "secondfloor", "level1", "level2")):
        return "above_ground_1_2"
    if any(marker in compact for marker in ("thirdfloor", "3层", "三层", "level3")):
        return "above_ground_3"
    if any(marker in compact for marker in ("fourthfloor", "fifthfloor", "4层", "5层", "四层", "五层", "level4", "level5")):
        return "above_ground_4_5"
    return "unknown"
