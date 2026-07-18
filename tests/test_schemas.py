"""Validation and serialization tests for the T1 domain schemas."""

import unittest

from pydantic import ValidationError

from src.schemas.bim import (
    Building,
    Door,
    DoorSpaceBoundary,
    ElementPlacement,
    ExtraInfoItem,
    IfcEntityReference,
    Space,
    SpatialElementReference,
)
from src.schemas.assessment import (
    ClassificationEvidence,
    EvacuationDoorClass,
    EvacuationDoorAssessment,
    EvacuationDoorClassification,
)
from src.schemas.result import CheckResult, CheckStatus
from src.schemas.rule import Rule


class BIMSchemaTests(unittest.TestCase):
    def test_bim_entities_round_trip(self) -> None:
        building = Building(
            building_id="B-01", building_type="office", floor_count=12
        )
        space = Space(
            space_id="S-01",
            space_type="corridor",
            area=24.5,
            occupant_number=30,
            door_ids=["D-01"],
        )
        door = Door(
            ifc_schema="IFC2X3",
            ifc_id=13808,
            ifc_guid="2P$exampleGuid",
            door_id="D-01",
            name="D-01",
            door_type="single_leaf",
            type_reference=IfcEntityReference(
                ifc_class="IfcDoorStyle", ifc_id=100, name="Door 19"
            ),
            operation_type="SINGLE_SWING_RIGHT",
            overall_width=1000.0,
            overall_height=2100.0,
            dimension_sources={
                "overall_width": "IfcDoor.OverallWidth",
                "overall_height": "IfcDoor.OverallHeight",
            },
            storey=SpatialElementReference(
                ifc_class="IfcBuildingStorey", name="Ground Floor", elevation=0.0
            ),
            host_element=IfcEntityReference(
                ifc_class="IfcWallStandardCase", global_id="wall-guid"
            ),
            opening_element=IfcEntityReference(
                ifc_class="IfcOpeningElement", global_id="opening-guid"
            ),
            adjacent_spaces=[
                DoorSpaceBoundary(
                    space=SpatialElementReference(
                        ifc_class="IfcSpace",
                        ifc_id=200,
                        name="014",
                        long_name="Corridor",
                    ),
                    internal_or_external="INTERNAL",
                    physical_or_virtual="PHYSICAL",
                    relationship_ifc_id=300,
                )
            ],
            placement=ElementPlacement(
                x=1000.0,
                y=2000.0,
                z=0.0,
                matrix=[
                    [1.0, 0.0, 0.0, 1000.0],
                    [0.0, 1.0, 0.0, 2000.0],
                    [0.0, 0.0, 1.0, 0.0],
                    [0.0, 0.0, 0.0, 1.0],
                ],
            ),
            materials=["Door panel"],
            extra_info=[
                ExtraInfoItem(
                    source="AC_Equantity_Door_19",
                    data={"Egress Width": 900.0},
                ),
                ExtraInfoItem(
                    source="IfcRelSpaceBoundary",
                    data={"adjacent_spaces": ["Office", "Corridor"]},
                ),
            ],
        )

        self.assertEqual(Building.model_validate_json(building.model_dump_json()), building)
        self.assertEqual(Space.model_validate_json(space.model_dump_json()), space)
        self.assertEqual(Door.model_validate_json(door.model_dump_json()), door)

    def test_extra_info_requires_source_and_data(self) -> None:
        with self.assertRaises(ValidationError):
            self._minimal_door(extra_info=[{"Egress Width": 900.0}])

    @staticmethod
    def _minimal_door(**overrides: object) -> Door:
        values = {
            "ifc_schema": "IFC4",
            "ifc_id": 1,
            "ifc_guid": "guid",
            "door_id": "D-01",
            "name": "D-01",
            "door_type": "single_leaf",
            "type_reference": IfcEntityReference(ifc_class="IfcDoorType"),
            "operation_type": "SINGLE_SWING_LEFT",
            "overall_width": 900.0,
            "overall_height": 2100.0,
            "storey": SpatialElementReference(ifc_class="IfcBuildingStorey"),
            "host_element": IfcEntityReference(ifc_class="IfcWall"),
            "opening_element": IfcEntityReference(ifc_class="IfcOpeningElement"),
            "placement": ElementPlacement(
                x=0,
                y=0,
                z=0,
                matrix=[
                    [1, 0, 0, 0],
                    [0, 1, 0, 0],
                    [0, 0, 1, 0],
                    [0, 0, 0, 1],
                ],
            ),
        }
        values.update(overrides)
        return Door.model_validate(values)

    def test_negative_width_is_rejected(self) -> None:
        with self.assertRaises(ValidationError):
            Door(
                ifc_schema="IFC4",
                ifc_id=1,
                ifc_guid="guid",
                door_id="D-01",
                name="D-01",
                door_type="single_leaf",
                type_reference=IfcEntityReference(ifc_class="IfcDoorType"),
                operation_type="SINGLE_SWING_LEFT",
                overall_width=-0.1,
                overall_height=2100.0,
                storey=SpatialElementReference(ifc_class="IfcBuildingStorey"),
                host_element=IfcEntityReference(ifc_class="IfcWall"),
                opening_element=IfcEntityReference(ifc_class="IfcOpeningElement"),
                placement=ElementPlacement(
                    x=0,
                    y=0,
                    z=0,
                    matrix=[
                        [1, 0, 0, 0],
                        [0, 1, 0, 0],
                        [0, 0, 1, 0],
                        [0, 0, 0, 1],
                    ],
                ),
            )

    def test_unknown_door_field_is_rejected(self) -> None:
        with self.assertRaises(ValidationError):
            Door(
                ifc_schema="IFC4",
                ifc_id=1,
                ifc_guid="guid",
                door_id="D-01",
                name="D-01",
                door_type="single_leaf",
                type_reference=IfcEntityReference(ifc_class="IfcDoorType"),
                operation_type="SINGLE_SWING_LEFT",
                overall_width=900.0,
                overall_height=2100.0,
                storey=SpatialElementReference(ifc_class="IfcBuildingStorey"),
                host_element=IfcEntityReference(ifc_class="IfcWall"),
                opening_element=IfcEntityReference(ifc_class="IfcOpeningElement"),
                placement=ElementPlacement(
                    x=0,
                    y=0,
                    z=0,
                    matrix=[
                        [1, 0, 0, 0],
                        [0, 1, 0, 0],
                        [0, 0, 1, 0],
                        [0, 0, 0, 1],
                    ],
                ),
                unsupported_ifc_data="value",
            )


class RuleSchemaTests(unittest.TestCase):
    def test_rule_round_trip(self) -> None:
        rule = Rule(
            rule_id="DOOR-WIDTH-001",
            standard="南京地方标准",
            article="6.1.1",
            rule_name="疏散门净宽检查",
            applicable_building_type=["office"],
            target_entity="Door",
            conditions={"is_evacuation_door": True},
            requirements={"clear_width": {"operator": ">=", "value": 0.9}},
        )

        self.assertEqual(Rule.model_validate_json(rule.model_dump_json()), rule)


class ResultSchemaTests(unittest.TestCase):
    def test_result_round_trip(self) -> None:
        result = CheckResult(
            element_id="D-01",
            rule_id="DOOR-WIDTH-001",
            actual_value=800,
            required_value=900,
            result=CheckStatus.FAIL,
            message="Clear width is below the required value.",
        )

        restored = CheckResult.model_validate_json(result.model_dump_json())
        self.assertEqual(restored, result)
        self.assertEqual(restored.result, CheckStatus.FAIL)

    def test_unknown_status_is_supported(self) -> None:
        result = CheckResult(
            element_id="D-01",
            rule_id="DOOR-WIDTH-001",
            actual_value=None,
            required_value=900,
            result="UNKNOWN",
            message="Clear width is unavailable.",
        )
        self.assertEqual(result.result, CheckStatus.UNKNOWN)


class AssessmentSchemaTests(unittest.TestCase):
    def test_classification_and_assessment_round_trip(self) -> None:
        classification = EvacuationDoorClassification(
            ifc_guid="guid",
            classification=EvacuationDoorClass.EVACUATION_DOOR,
            evidence=[
                ClassificationEvidence(
                    field="extra_info.PSet_Revit_Type_Other.IsFireExit",
                    value=True,
                    impact="positive",
                )
            ],
            reasoning="The IFC evidence explicitly marks this as a fire exit.",
            missing_information=[],
            confidence=0.98,
            model_name="test-model",
            prompt_version="v1",
        )
        assessment = EvacuationDoorAssessment(
            ifc_guid="guid",
            classification=classification.classification,
            clear_width=830,
            clear_width_source="AC_Equantity_Door_19.Egress Width",
            required_width=900,
            status=CheckStatus.FAIL,
            evidence=classification.evidence,
        )
        restored = EvacuationDoorAssessment.model_validate_json(
            assessment.model_dump_json()
        )
        self.assertEqual(restored, assessment)


if __name__ == "__main__":
    unittest.main()
