"""Tests for separated AI classification and deterministic width resolution."""

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any

from pydantic import ValidationError

from src.ai.evacuation_door_classifier import (
    build_classification_input,
    classify_evacuation_door,
)
from src.ai.run_evacuation_door_classification import classify_jsonl
from src.clear_width_resolver import assess_evacuation_door, resolve_clear_width
from src.schemas.assessment import (
    ClassifiedEvacuationDoorRecord,
    EvacuationDoorClass,
)
from src.schemas.bim import (
    Door,
    ElementPlacement,
    ExtraInfoItem,
    IfcEntityReference,
    SpatialElementReference,
)
from src.schemas.result import CheckStatus


class FakeLLMClient:
    model_name = "fake-model"

    def complete_json(
        self, *, system_prompt: str, payload: dict[str, Any]
    ) -> dict[str, Any]:
        self.system_prompt = system_prompt
        self.payload = payload
        return {
            "classification": "evacuation_door",
            "is_fire_door": None,
            "evidence": [
                {
                    "field": "extra_info.PSet_Revit_Type_Other.IsFireExit",
                    "value": True,
                    "impact": "positive",
                }
            ],
            "reasoning": "The source model explicitly marks this door as a fire exit.",
            "missing_information": [],
            "evacuation_door_confidence": 0.99,
            "fire_door_confidence": None,
        }


def make_door(*, extra_info: list[ExtraInfoItem] | None = None) -> Door:
    return Door(
        ifc_schema="IFC2X3",
        ifc_id=1,
        ifc_guid="guid",
        door_id="D-01",
        name="D-01",
        door_type="single swing",
        type_reference=IfcEntityReference(ifc_class="IfcDoorStyle"),
        operation_type="SINGLE_SWING_RIGHT",
        overall_width=900,
        overall_height=2100,
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
        extra_info=extra_info or [],
    )


class PipelineComponentTests(unittest.TestCase):
    def test_llm_classifier_is_separate_and_schema_validated(self) -> None:
        classification = classify_evacuation_door(make_door(), FakeLLMClient())
        self.assertEqual(
            classification.classification,
            EvacuationDoorClass.EVACUATION_DOOR,
        )
        self.assertEqual(classification.model_name, "fake-model")
        self.assertIsNone(classification.is_fire_door)
        self.assertEqual(classification.evacuation_door_confidence, 0.99)
        self.assertIsNone(classification.fire_door_confidence)

    def test_classification_input_includes_building_and_excludes_geometry_noise(
        self,
    ) -> None:
        door = make_door().model_copy(
            update={"building": "office"}
        )

        payload = build_classification_input(door).model_dump(mode="json")

        self.assertEqual(payload["building"], "office")
        self.assertEqual(payload["dimension_unit"], "mm")
        self.assertEqual(payload["occupant_load"], 100)
        self.assertNotIn("placement", payload)
        self.assertNotIn("representation_ids", payload)
        self.assertNotIn("host_element", payload)

    def test_parallel_batch_respects_limit(self) -> None:
        inputs = []
        for index in range(3):
            door = make_door().model_copy(
                update={"ifc_guid": f"guid-{index}", "door_id": f"D-{index}"}
            )
            inputs.append(build_classification_input(door).model_dump_json())

        with TemporaryDirectory() as directory:
            input_path = Path(directory) / "input.jsonl"
            output_path = Path(directory) / "output.jsonl"
            input_path.write_text("\n".join(inputs) + "\n", encoding="utf-8")
            classify_jsonl(
                input_path,
                output_path,
                limit=2,
                workers=2,
                client=FakeLLMClient(),
            )
            results = [
                ClassifiedEvacuationDoorRecord.model_validate_json(line)
                for line in output_path.read_text(encoding="utf-8").splitlines()
            ]

        self.assertEqual(len(results), 3)
        self.assertEqual(
            sum(result.assessment is not None for result in results),
            2,
        )

    def test_batch_can_enrich_input_in_place(self) -> None:
        input_row = build_classification_input(make_door()).model_dump_json()
        with TemporaryDirectory() as directory:
            input_path = Path(directory) / "input.jsonl"
            input_path.write_text(input_row + "\n", encoding="utf-8")

            classify_jsonl(input_path, client=FakeLLMClient())
            enriched = ClassifiedEvacuationDoorRecord.model_validate_json(
                input_path.read_text(encoding="utf-8").strip()
            )

        self.assertIsNotNone(enriched.assessment)
        self.assertEqual(enriched.door_id, "D-01")

    def test_enriched_record_rejects_mismatched_assessment_guid(self) -> None:
        facts = build_classification_input(make_door()).model_dump(mode="json")
        assessment = {
            **FakeLLMClient().complete_json(system_prompt="", payload={}),
            "ifc_guid": "another-guid",
            "model_name": "fake-model",
            "prompt_version": "v1",
        }

        with self.assertRaises(ValidationError):
            ClassifiedEvacuationDoorRecord.model_validate(
                {**facts, "assessment": assessment}
            )

    def test_resolver_prefers_explicit_egress_width(self) -> None:
        door = make_door(
            extra_info=[
                ExtraInfoItem(
                    source="AC_Equantity_Door_19",
                    data={"Egress Width": 830.0},
                )
            ]
        )
        width = resolve_clear_width(door)
        self.assertEqual(width.clear_width, 830.0)
        self.assertEqual(width.source, "AC_Equantity_Door_19.Egress Width")

    def test_resolver_never_uses_overall_width_as_clear_width(self) -> None:
        width = resolve_clear_width(make_door())
        self.assertIsNone(width.clear_width)
        self.assertEqual(width.method, "unavailable")

    def test_assessment_is_unknown_without_confirmed_classification(self) -> None:
        classification = FakeLLMClient().complete_json(system_prompt="", payload={})
        classification["classification"] = "uncertain"
        classification.update(
            {
                "ifc_guid": "guid",
                "model_name": "fake-model",
                "prompt_version": "v1",
            }
        )
        from src.schemas.assessment import EvacuationDoorClassification

        assessment = assess_evacuation_door(
            EvacuationDoorClassification.model_validate(classification),
            resolve_clear_width(make_door()),
            required_width=900,
        )
        self.assertEqual(assessment.status, CheckStatus.UNKNOWN)


if __name__ == "__main__":
    unittest.main()
