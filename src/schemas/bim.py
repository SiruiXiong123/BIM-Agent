"""Structured BIM entities used by the compliance pipeline."""

from enum import StrEnum
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field


NonNegativeFloat = Annotated[float, Field(ge=0)]
PositiveInt = Annotated[int, Field(gt=0)]
DEFAULT_DOOR_OCCUPANT_LOAD = 100
DEFAULT_FIRE_RESISTANCE_GRADE = "一级"
FireResistanceGrade = Literal["一级", "二级", "三级", "四级"]


class InputValueSource(StrEnum):
    IFC = "ifc"
    USER = "user"
    DEFAULT = "default"


class BIMModel(BaseModel):
    """Base configuration shared by BIM schema models."""

    model_config = ConfigDict(extra="forbid", validate_assignment=True)


class Building(BIMModel):
    building_id: str = Field(min_length=1)
    building_type: str = Field(min_length=1)
    floor_count: PositiveInt | None = None
    fire_resistance_level: str | None = None


class Space(BIMModel):
    space_id: str = Field(min_length=1)
    space_type: str = Field(min_length=1)
    area: NonNegativeFloat | None = Field(default=None, description="Area in m².")
    occupant_number: Annotated[int, Field(ge=0)] | None = None
    is_corridor_end: bool | None = None
    door_ids: list[str] = Field(default_factory=list)


class IfcEntityReference(BIMModel):
    """Lightweight reference to a related IFC entity."""

    ifc_class: str = Field(min_length=1)
    ifc_id: PositiveInt | None = None
    global_id: str | None = None
    name: str | None = None
    description: str | None = None


class SpatialElementReference(IfcEntityReference):
    """Reference to a site, building, storey, or space."""

    long_name: str | None = None
    object_type: str | None = None
    elevation: float | None = Field(
        default=None, description="Elevation in millimetres."
    )


class ElementPlacement(BIMModel):
    """Element placement in project coordinates."""

    x: float = Field(description="Project X coordinate in millimetres.")
    y: float = Field(description="Project Y coordinate in millimetres.")
    z: float = Field(description="Project Z coordinate in millimetres.")
    matrix: list[list[float]] = Field(
        description="4×4 local-to-project matrix with translation in millimetres."
    )


class ExtraInfoItem(BIMModel):
    """A model-specific IFC payload with explicit provenance."""

    source: str = Field(min_length=1)
    data: dict[str, Any]


class DoorSpaceBoundary(BIMModel):
    """A standard IFC space boundary directly related to a door."""

    space: SpatialElementReference
    internal_or_external: str | None = None
    physical_or_virtual: str | None = None
    relationship_ifc_id: PositiveInt | None = None
    source: str = "IfcRelSpaceBoundary"


class Door(BIMModel):
    """Door fields available in all three project IFC fixtures."""

    # Identity fields shared by every fixture.
    ifc_schema: str = Field(min_length=1)
    ifc_id: PositiveInt
    ifc_guid: str = Field(min_length=1)
    door_id: str = Field(min_length=1)
    name: str = Field(min_length=1)

    # Type and operation fields shared by IFC2X3 and IFC4 fixtures.
    door_type: str = Field(min_length=1)
    type_reference: IfcEntityReference
    operation_type: str = Field(min_length=1)

    # Shared IFC dimensions, normalized to millimetres.
    overall_width: NonNegativeFloat = Field(
        description="IfcDoor.OverallWidth in millimetres; not clear width."
    )
    overall_height: NonNegativeFloat = Field(
        description="IfcDoor.OverallHeight in millimetres."
    )
    occupant_load: PositiveInt = DEFAULT_DOOR_OCCUPANT_LOAD
    occupant_load_source: InputValueSource = InputValueSource.DEFAULT
    dimension_sources: dict[str, str] = Field(default_factory=dict)

    # Shared spatial and construction relationships.
    building: str | None = Field(
        default=None,
        description="Minimal inferred building type, or null when unavailable.",
    )
    fire_resistance_grade: FireResistanceGrade | None = None
    fire_resistance_grade_source: InputValueSource | None = None
    storey: SpatialElementReference
    host_element: IfcEntityReference
    opening_element: IfcEntityReference
    adjacent_spaces: list[DoorSpaceBoundary] = Field(
        default_factory=list,
        description="IfcSpace entities directly related to this door by IfcRelSpaceBoundary.",
    )

    # Shared placement and lightweight geometry references.
    placement: ElementPlacement
    representation_ids: list[int] = Field(default_factory=list)

    # Every fixture exposes material information, though vendor keys differ.
    materials: list[str] = Field(default_factory=list)

    extra_info: list[ExtraInfoItem] = Field(
        default_factory=list,
        description="Model-specific door data outside the shared IFC field set.",
    )
    parse_warnings: list[str] = Field(default_factory=list)
