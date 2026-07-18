"""Build the current-door facts supplied to T4 script generation."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict

from src.schemas.bim import ExtraInfoItem, FireResistanceGrade, InputValueSource
from src.search.iterative.models import IFCContext


TargetWidthField = Literal[
    "actual_clear_width_mm",
    "required_clear_width_mm",
]


class T4DoorCalculationContext(BaseModel):
    """Minimal per-door facts kept separate from building-shared evidence."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    door_id: str
    overall_width_mm: float
    explicit_clear_width_mm: float | None
    explicit_clear_width_source: str | None
    ifc_extra_info: tuple[ExtraInfoItem, ...]
    is_fire_door: bool
    building_type: str | None
    storey_name: str | None
    storey_band: str
    fire_resistance_grade: FireResistanceGrade
    fire_resistance_grade_source: InputValueSource
    occupant_load: int
    occupant_load_source: InputValueSource

    def for_target_field(self, target_field: TargetWidthField) -> dict[str, object]:
        """Expose only facts needed to calculate one target field."""

        if target_field == "actual_clear_width_mm":
            return {
                "door_id": self.door_id,
                "overall_width_mm": self.overall_width_mm,
                "explicit_clear_width_mm": self.explicit_clear_width_mm,
                "explicit_clear_width_source": self.explicit_clear_width_source,
                "ifc_extra_info": [
                    item.model_dump(mode="json") for item in self.ifc_extra_info
                ],
                "is_fire_door": self.is_fire_door,
            }
        return {
            "door_id": self.door_id,
            "building_type": self.building_type,
            "storey_name": self.storey_name,
            "storey_band": self.storey_band,
            "fire_resistance_grade": self.fire_resistance_grade,
            "fire_resistance_grade_source": self.fire_resistance_grade_source,
            "occupant_load": self.occupant_load,
            "occupant_load_source": self.occupant_load_source,
        }


def build_t4_door_calculation_context(
    ifc_context: IFCContext,
) -> T4DoorCalculationContext:
    """Convert T3's IFC context into T4's explicit per-door contract."""

    return T4DoorCalculationContext(
        door_id=ifc_context.subject.door_id,
        overall_width_mm=ifc_context.door_facts.overall_width,
        explicit_clear_width_mm=ifc_context.clear_width_resolution.clear_width,
        explicit_clear_width_source=ifc_context.clear_width_resolution.source,
        ifc_extra_info=tuple(ifc_context.door_facts.extra_info),
        is_fire_door=ifc_context.assessment.is_fire_door,
        building_type=ifc_context.building_context.building_type,
        storey_name=ifc_context.building_context.storey_name,
        storey_band=ifc_context.building_context.storey_band,
        fire_resistance_grade=(
            ifc_context.building_context.fire_resistance_grade
        ),
        fire_resistance_grade_source=(
            ifc_context.building_context.fire_resistance_grade_source
        ),
        occupant_load=ifc_context.door_facts.occupant_load,
        occupant_load_source=ifc_context.door_facts.occupant_load_source,
    )
