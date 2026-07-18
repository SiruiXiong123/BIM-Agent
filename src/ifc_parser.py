"""Deterministic IFC-to-domain extraction.

This module reads facts only. It does not classify evacuation doors, calculate
clear width, interpret regulations, or make compliance decisions.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

import ifcopenshell
import ifcopenshell.util.element as element
import ifcopenshell.util.placement as placement
import ifcopenshell.util.unit as unit
from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from src.schemas.bim import (
    Door,
    DoorSpaceBoundary,
    ElementPlacement,
    ExtraInfoItem,
    IfcEntityReference,
    InputValueSource,
    SpatialElementReference,
)


class IFCParseError(RuntimeError):
    """Raised when an IFC file cannot be parsed safely."""


BUILDING_TYPE_KEYWORDS: dict[str, tuple[str, ...]] = {
    "office": ("office",),
    "apartment": ("apartment",),
    "primary_school": ("primary school", "elementary school"),
}


class IFCParseResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source_file: str
    ifc_schema: str
    unit_scale_to_mm: float = Field(gt=0)
    total_ifc_door_count: int = Field(ge=0)
    requested_max_doors: int | None = Field(default=None, gt=0)
    door_count: int = Field(ge=0)
    doors: list[Door]
    warnings: list[str] = Field(default_factory=list)
    errors: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_door_counts(self) -> "IFCParseResult":
        if self.door_count != len(self.doors):
            raise ValueError("door_count must equal the number of parsed doors")
        if self.door_count > self.total_ifc_door_count:
            raise ValueError("door_count cannot exceed total_ifc_door_count")
        if (
            self.requested_max_doors is not None
            and self.door_count > self.requested_max_doors
        ):
            raise ValueError("door_count cannot exceed requested_max_doors")
        return self


def parse_ifc(
    path: str | Path,
    *,
    strict: bool = False,
    max_doors: int | None = None,
) -> IFCParseResult:
    """Parse the first ``max_doors`` IfcDoor occurrences, or all when null."""

    validate_max_doors(max_doors)
    source = Path(path)
    if not source.is_file():
        raise IFCParseError(f"IFC file does not exist: {source}")
    if source.suffix.lower() != ".ifc":
        raise IFCParseError(f"Unsupported IFC format: {source.suffix or '<none>'}")

    try:
        model = ifcopenshell.open(source)
    except Exception as exc:  # IfcOpenShell exposes several native exceptions.
        raise IFCParseError(f"Unable to open IFC file {source}: {exc}") from exc

    scale_to_m = unit.calculate_unit_scale(model)
    scale_to_mm = scale_to_m * 1000.0
    if scale_to_mm <= 0:
        raise IFCParseError("The IFC project has an invalid length unit scale.")

    doors: list[Door] = []
    warnings: list[str] = []
    errors: list[str] = []
    all_entities = sorted(model.by_type("IfcDoor"), key=lambda item: item.id())
    total_ifc_door_count = len(all_entities)
    entities = all_entities if max_doors is None else all_entities[:max_doors]
    building_types = _resolve_building_types(model)
    if not all_entities:
        warnings.append("No IfcDoor entities were found.")

    for entity in entities:
        try:
            doors.append(
                _extract_door(
                    model,
                    entity,
                    scale_to_m,
                    scale_to_mm,
                    building_types,
                )
            )
        except (IFCParseError, ValidationError, AttributeError, ValueError) as exc:
            message = f"IfcDoor #{entity.id()} could not be parsed: {exc}"
            if strict:
                raise IFCParseError(message) from exc
            errors.append(message)

    return IFCParseResult(
        source_file=str(source),
        ifc_schema=model.schema,
        unit_scale_to_mm=scale_to_mm,
        total_ifc_door_count=total_ifc_door_count,
        requested_max_doors=max_doors,
        door_count=len(doors),
        doors=doors,
        warnings=warnings,
        errors=errors,
    )


def parse_doors(
    path: str | Path,
    *,
    strict: bool = False,
    max_doors: int | None = None,
) -> list[Door]:
    """Convenience wrapper returning only parsed doors."""

    return parse_ifc(path, strict=strict, max_doors=max_doors).doors


def validate_max_doors(max_doors: int | None) -> None:
    """Validate the framework-neutral representation of ``N`` or ``all``."""

    if max_doors is None:
        return
    if isinstance(max_doors, bool) or not isinstance(max_doors, int):
        raise ValueError("max_doors must be a positive integer or None")
    if max_doors <= 0:
        raise ValueError("max_doors must be greater than zero")


def write_parse_result_jsonl(
    result: IFCParseResult,
    output_path: str | Path,
) -> Path:
    """Write parser output as UTF-8 JSONL: one metadata row, then one row per door."""

    destination = Path(output_path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    metadata = {
        "record_type": "ifc_parse_metadata",
        "source_file": result.source_file,
        "ifc_schema": result.ifc_schema,
        "unit_scale_to_mm": result.unit_scale_to_mm,
        "total_ifc_door_count": result.total_ifc_door_count,
        "requested_max_doors": result.requested_max_doors,
        "door_count": result.door_count,
        "warnings": result.warnings,
        "errors": result.errors,
    }
    records = [metadata]
    records.extend(
        {
            "record_type": "door",
            "door_index": index,
            **door.model_dump(mode="json"),
        }
        for index, door in enumerate(result.doors, start=1)
    )
    content = "\n".join(
        json.dumps(record, ensure_ascii=False, sort_keys=False)
        for record in records
    )
    destination.write_text(content + "\n", encoding="utf-8")
    return destination


def _extract_door(
    model: ifcopenshell.file,
    door: ifcopenshell.entity_instance,
    scale_to_m: float,
    scale_to_mm: float,
    building_types: dict[int, str | None],
) -> Door:
    door_type = element.get_type(door)
    if door_type is None:
        raise IFCParseError("missing IfcDoorStyle/IfcDoorType relationship")

    storey = element.get_container(door, ifc_class="IfcBuildingStorey")
    if storey is None:
        raise IFCParseError("missing IfcBuildingStorey container")

    fills = list(getattr(door, "FillsVoids", ()) or ())
    if not fills:
        raise IFCParseError("missing IfcRelFillsElement relationship")
    opening = fills[0].RelatingOpeningElement
    host = element.get_voided_element(opening)
    if host is None:
        raise IFCParseError("opening does not void a host element")

    if door.OverallWidth is None or door.OverallHeight is None:
        raise IFCParseError("missing OverallWidth or OverallHeight")

    name = door.Name or door.Tag or door.GlobalId
    operation = getattr(door_type, "OperationType", None) or "UNKNOWN"
    warnings: list[str] = []
    if str(operation) == "NOTDEFINED":
        warnings.append("Door type OperationType is NOTDEFINED.")

    building_entity = _extract_building(storey)
    building = (
        building_types.get(building_entity.id())
        if building_entity is not None
        else None
    )
    if building_entity is None:
        warnings.append(
            "No standard IfcBuilding aggregate relationship was available for this door."
        )

    psets = element.get_psets(door, psets_only=True, verbose=True)
    qtos = element.get_psets(door, qtos_only=True, verbose=True)
    extra_info = _extract_extra_info(
        door,
        door_type,
        psets,
        qtos,
        scale_to_m,
        scale_to_mm,
        warnings,
    )
    adjacent_spaces = _extract_adjacent_spaces(door)
    if not adjacent_spaces:
        warnings.append(
            "No direct IfcRelSpaceBoundary relationship was available for this door."
        )

    matrix = placement.get_local_placement(door.ObjectPlacement).tolist()
    for index in range(3):
        matrix[index][3] = float(matrix[index][3]) * scale_to_mm

    storey_elevation = placement.get_storey_elevation(storey) * scale_to_mm
    representations = getattr(getattr(door, "Representation", None), "Representations", ())

    occupant_load, occupant_load_source = _extract_occupant_load(door)
    fire_resistance_grade = _extract_fire_resistance_grade(
        model,
        building_entity,
    )

    return Door(
        ifc_schema=model.schema,
        ifc_id=door.id(),
        ifc_guid=door.GlobalId,
        door_id=name,
        name=name,
        door_type=door_type.Name or door.ObjectType or door_type.is_a(),
        type_reference=_entity_reference(door_type),
        operation_type=str(operation),
        overall_width=float(door.OverallWidth) * scale_to_mm,
        overall_height=float(door.OverallHeight) * scale_to_mm,
        occupant_load=occupant_load,
        occupant_load_source=occupant_load_source,
        dimension_sources={
            "overall_width": "IfcDoor.OverallWidth",
            "overall_height": "IfcDoor.OverallHeight",
        },
        building=building,
        fire_resistance_grade=fire_resistance_grade,
        fire_resistance_grade_source=(
            InputValueSource.IFC
            if fire_resistance_grade is not None
            else None
        ),
        storey=SpatialElementReference(
            **_entity_reference(storey).model_dump(),
            long_name=getattr(storey, "LongName", None),
            elevation=storey_elevation,
        ),
        host_element=_entity_reference(host),
        opening_element=_entity_reference(opening),
        adjacent_spaces=adjacent_spaces,
        placement=ElementPlacement(
            x=matrix[0][3],
            y=matrix[1][3],
            z=matrix[2][3],
            matrix=matrix,
        ),
        representation_ids=[representation.id() for representation in representations],
        materials=_extract_materials(door),
        extra_info=extra_info,
        parse_warnings=warnings,
    )


_OCCUPANT_LOAD_KEYS = {
    "occupantload",
    "occupancynumber",
    "occupantnumber",
    "numberofoccupants",
    "numberofpeople",
    "designoccupancy",
    "疏散人数",
    "使用人数",
}


def _extract_occupant_load(
    door: ifcopenshell.entity_instance,
) -> tuple[int, InputValueSource]:
    """Read an explicit door/adjacent-space population or default to 100."""

    from src.schemas.bim import DEFAULT_DOOR_OCCUPANT_LOAD

    entities = [door]
    seen = {door.id()}
    for boundary in list(getattr(door, "ProvidesBoundaries", ()) or ()):
        space = getattr(boundary, "RelatingSpace", None)
        if space is not None and space.is_a("IfcSpace") and space.id() not in seen:
            entities.append(space)
            seen.add(space.id())

    values: list[int] = []
    for entity_instance in entities:
        for properties in element.get_psets(
            entity_instance,
            psets_only=True,
        ).values():
            for key, value in properties.items():
                normalized_key = re.sub(r"[\W_]+", "", str(key).casefold())
                if normalized_key not in _OCCUPANT_LOAD_KEYS:
                    continue
                parsed = _positive_integer(value)
                if parsed is not None:
                    values.append(parsed)
    if values:
        return max(values), InputValueSource.IFC
    return DEFAULT_DOOR_OCCUPANT_LOAD, InputValueSource.DEFAULT


_FIRE_RESISTANCE_GRADE_KEYS = {
    "fireresistancegrade",
    "fireresistancelevel",
    "buildingfireresistancegrade",
    "buildingfireresistancelevel",
    "耐火等级",
    "建筑耐火等级",
}


def _extract_fire_resistance_grade(
    model: ifcopenshell.file,
    building: ifcopenshell.entity_instance | None,
) -> str | None:
    """Read a building-grade property; never use door FireRating."""

    entities = [building] if building is not None else []
    entities.extend(model.by_type("IfcProject"))
    for entity_instance in entities:
        for properties in element.get_psets(
            entity_instance,
            psets_only=True,
        ).values():
            for key, value in properties.items():
                normalized_key = re.sub(r"[\W_]+", "", str(key).casefold())
                if normalized_key not in _FIRE_RESISTANCE_GRADE_KEYS:
                    continue
                grade = _normalize_fire_resistance_grade(value)
                if grade is not None:
                    return grade
    return None


def _normalize_fire_resistance_grade(value: object) -> str | None:
    normalized = re.sub(
        r"[\s_.-]+",
        "",
        str(value or "").strip().casefold(),
    )
    mappings = {
        "一级": "一级",
        "1级": "一级",
        "i级": "一级",
        "gradei": "一级",
        "二级": "二级",
        "2级": "二级",
        "ii级": "二级",
        "gradeii": "二级",
        "三级": "三级",
        "3级": "三级",
        "iii级": "三级",
        "gradeiii": "三级",
        "四级": "四级",
        "4级": "四级",
        "iv级": "四级",
        "gradeiv": "四级",
    }
    return mappings.get(normalized)


def _positive_integer(value: object) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)) and float(value).is_integer() and value > 0:
        return int(value)
    if isinstance(value, str):
        stripped = value.strip()
        if stripped.isdigit() and int(stripped) > 0:
            return int(stripped)
    return None


def _entity_reference(entity: ifcopenshell.entity_instance) -> IfcEntityReference:
    return IfcEntityReference(
        ifc_class=entity.is_a(),
        ifc_id=entity.id(),
        global_id=getattr(entity, "GlobalId", None),
        name=getattr(entity, "Name", None),
        description=getattr(entity, "Description", None),
    )


def _extract_building(
    spatial_element: ifcopenshell.entity_instance,
) -> ifcopenshell.entity_instance | None:
    """Walk standard spatial aggregation upward to the containing IfcBuilding."""

    current = spatial_element
    seen_ids: set[int] = set()
    while current is not None and current.id() not in seen_ids:
        seen_ids.add(current.id())
        if current.is_a("IfcBuilding"):
            return current
        current = element.get_aggregate(current)
    return None


def _resolve_building_types(model: ifcopenshell.file) -> dict[int, str | None]:
    """Resolve a minimal building type from project text or space frequency."""

    project_texts: list[str] = []
    for project in model.by_type("IfcProject"):
        for attribute in ("LongName", "Name"):
            value = getattr(project, attribute, None)
            if value:
                project_texts.append(str(value))

    project_match = _match_building_type(project_texts)
    buildings = model.by_type("IfcBuilding")
    if project_match is not None:
        return {building.id(): project_match for building in buildings}

    counts: dict[int, dict[str, int]] = {
        building.id(): {kind: 0 for kind in BUILDING_TYPE_KEYWORDS}
        for building in buildings
    }
    for space in model.by_type("IfcSpace"):
        building = _extract_building(space)
        if building is None or building.id() not in counts:
            continue
        texts = [
            str(value)
            for value in (
                getattr(space, "Name", None),
                getattr(space, "LongName", None),
                getattr(space, "ObjectType", None),
            )
            if value
        ]
        matched = _matched_building_types(texts)
        for kind in matched:
            counts[building.id()][kind] += 1

    return {
        building.id(): _unique_highest(counts[building.id()])
        for building in buildings
    }


def _match_building_type(texts: list[str]) -> str | None:
    matches = _matched_building_types(texts)
    return next(iter(matches)) if len(matches) == 1 else None


def _matched_building_types(texts: list[str]) -> set[str]:
    normalized = " ".join(texts).casefold()
    return {
        kind
        for kind, keywords in BUILDING_TYPE_KEYWORDS.items()
        if any(keyword in normalized for keyword in keywords)
    }


def _unique_highest(counts: dict[str, int]) -> str | None:
    highest = max(counts.values(), default=0)
    if highest == 0:
        return None
    winners = [kind for kind, count in counts.items() if count == highest]
    return winners[0] if len(winners) == 1 else None


def _extract_materials(door: ifcopenshell.entity_instance) -> list[str]:
    names: list[str] = []
    for material in element.get_materials(door):
        name = getattr(material, "Name", None)
        if name and name not in names:
            names.append(str(name))
    return names


def _extract_adjacent_spaces(
    door: ifcopenshell.entity_instance,
) -> list[DoorSpaceBoundary]:
    """Extract direct door-to-space facts without semantic classification."""

    result: list[DoorSpaceBoundary] = []
    seen_space_ids: set[int] = set()
    for boundary in list(getattr(door, "ProvidesBoundaries", ()) or ()):
        space = getattr(boundary, "RelatingSpace", None)
        if space is None or not space.is_a("IfcSpace") or space.id() in seen_space_ids:
            continue
        seen_space_ids.add(space.id())
        result.append(
            DoorSpaceBoundary(
                space=SpatialElementReference(
                    **_entity_reference(space).model_dump(),
                    long_name=getattr(space, "LongName", None),
                    object_type=getattr(space, "ObjectType", None),
                ),
                internal_or_external=_optional_string(
                    getattr(boundary, "InternalOrExternalBoundary", None)
                ),
                physical_or_virtual=_optional_string(
                    getattr(boundary, "PhysicalOrVirtualBoundary", None)
                ),
                relationship_ifc_id=boundary.id(),
            )
        )
    return result


def _extract_extra_info(
    door: ifcopenshell.entity_instance,
    door_type: ifcopenshell.entity_instance,
    psets: dict[str, dict[str, Any]],
    qtos: dict[str, dict[str, Any]],
    scale_to_m: float,
    scale_to_mm: float,
    warnings: list[str],
) -> list[ExtraInfoItem]:
    items: list[ExtraInfoItem] = []

    occurrence = _selected_attributes(
        door,
        exclude={"GlobalId", "Name", "OverallWidth", "OverallHeight"},
    )
    if occurrence:
        items.append(ExtraInfoItem(source="IfcDoor", data=occurrence))

    type_data = _selected_attributes(door_type, exclude={"Name", "OperationType"})
    if type_data:
        items.append(ExtraInfoItem(source=door_type.is_a(), data=type_data))

    for set_name, values in psets.items():
        data = _normalise_verbose_values(values, scale_to_m, scale_to_mm)
        if data:
            _collect_placeholder_warnings(set_name, data, warnings)
            items.append(ExtraInfoItem(source=set_name, data=data))

    for set_name, values in qtos.items():
        data = _normalise_verbose_values(values, scale_to_m, scale_to_mm)
        if data:
            items.append(ExtraInfoItem(source=set_name, data=data))

    return items


def _selected_attributes(
    entity: ifcopenshell.entity_instance,
    *,
    exclude: set[str],
) -> dict[str, Any]:
    data: dict[str, Any] = {}
    for key, value in entity.get_info(recursive=False).items():
        if key in {"id", "type", *exclude} or value in (None, ""):
            continue
        data[key] = _to_json_value(value)
    return data


def _normalise_verbose_values(
    values: dict[str, Any],
    scale_to_m: float,
    scale_to_mm: float,
) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for name, metadata in values.items():
        if name == "id" or not isinstance(metadata, dict):
            continue
        value = metadata.get("value")
        value_type = metadata.get("value_type")
        value_class = metadata.get("class")
        if value is None:
            continue
        if value_type == "IfcLengthMeasure" or value_class == "IfcQuantityLength":
            value = float(value) * scale_to_mm
        elif value_type == "IfcAreaMeasure" or value_class == "IfcQuantityArea":
            value = float(value) * scale_to_m**2
        elif value_type == "IfcVolumeMeasure" or value_class == "IfcQuantityVolume":
            value = float(value) * scale_to_m**3
        result[name] = _to_json_value(value)
    return result


def _collect_placeholder_warnings(
    source: str,
    data: dict[str, Any],
    warnings: list[str],
) -> None:
    for name, value in data.items():
        if (
            isinstance(value, str)
            and value.strip()
            and value.strip().casefold() == name.strip().casefold()
        ):
            warnings.append(f"{source}.{name} appears to be a placeholder value.")


def _to_json_value(value: Any) -> Any:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, (list, tuple)):
        return [_to_json_value(item) for item in value]
    if isinstance(value, dict):
        return {str(key): _to_json_value(item) for key, item in value.items()}
    if hasattr(value, "id") and hasattr(value, "is_a"):
        return {"ifc_id": value.id(), "ifc_class": value.is_a()}
    return str(value)


def _optional_string(value: Any) -> str | None:
    return None if value is None else str(value)
