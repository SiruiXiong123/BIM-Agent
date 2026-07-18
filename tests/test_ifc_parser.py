"""Read-only integration tests against the three real IFC fixtures."""

import unittest
import json
from pathlib import Path
from tempfile import TemporaryDirectory

from src.ifc_parser import (
    _normalize_fire_resistance_grade,
    parse_ifc,
    write_parse_result_jsonl,
)


FIXTURES = Path(__file__).parents[1] / "test_sampe"


class IFCParserIntegrationTests(unittest.TestCase):
    def test_office_ifc2x3_is_converted_from_mm(self) -> None:
        result = parse_ifc(
            FIXTURES / "20160414office_model_CV2_fordesign.ifc",
            strict=True,
        )
        self.assertEqual(result.ifc_schema, "IFC2X3")
        self.assertEqual(result.unit_scale_to_mm, 1.0)
        self.assertEqual(result.total_ifc_door_count, 9)
        self.assertIsNone(result.requested_max_doors)
        self.assertEqual(result.door_count, 9)
        self.assertEqual(result.doors[0].overall_width, 900.0)
        self.assertTrue(all(door.building == "office" for door in result.doors))
        egress = next(
            item
            for item in result.doors[0].extra_info
            if item.source == "AC_Equantity_Door_19"
        )
        self.assertEqual(egress.data["Egress Width"], 830.0)
        self.assertTrue(all(door.adjacent_spaces for door in result.doors))
        d001 = next(door for door in result.doors if door.name == "D001")
        self.assertEqual(
            {space.space.long_name for space in d001.adjacent_spaces},
            {"Office", "Corridor"},
        )
        self.assertEqual(
            {space.internal_or_external for space in d001.adjacent_spaces},
            {"INTERNAL"},
        )

    def test_school_ifc4_is_converted_from_metres(self) -> None:
        result = parse_ifc(
            FIXTURES / "00 - Primary school project (IFC).ifc",
            strict=True,
        )
        self.assertEqual(result.ifc_schema, "IFC4")
        self.assertEqual(result.unit_scale_to_mm, 1000.0)
        self.assertEqual(result.total_ifc_door_count, 57)
        self.assertIsNone(result.requested_max_doors)
        self.assertEqual(result.door_count, 57)
        self.assertEqual(result.doors[0].overall_width, 700.0)
        self.assertTrue(
            all(door.building == "primary_school" for door in result.doors)
        )
        self.assertTrue(
            all(door.occupant_load_source == "default" for door in result.doors)
        )
        self.assertTrue(
            all(door.fire_resistance_grade is None for door in result.doors)
        )
        self.assertEqual(result.doors[0].type_reference.ifc_class, "IfcDoorType")
        self.assertTrue(all(not door.adjacent_spaces for door in result.doors))
        self.assertTrue(
            all(
                any("IfcRelSpaceBoundary" in warning for warning in door.parse_warnings)
                for door in result.doors
            )
        )

    def test_school_result_can_be_read_as_jsonl(self) -> None:
        result = parse_ifc(
            FIXTURES / "00 - Primary school project (IFC).ifc",
            strict=True,
        )
        with TemporaryDirectory() as directory:
            output = write_parse_result_jsonl(
                result,
                Path(directory) / "school.jsonl",
            )
            records = [
                json.loads(line)
                for line in output.read_text(encoding="utf-8").splitlines()
            ]

        self.assertEqual(len(records), 58)
        self.assertEqual(records[0]["record_type"], "ifc_parse_metadata")
        self.assertEqual(records[0]["total_ifc_door_count"], 57)
        self.assertIsNone(records[0]["requested_max_doors"])
        self.assertEqual(records[0]["door_count"], 57)
        self.assertTrue(all(row["record_type"] == "door" for row in records[1:]))
        self.assertEqual(records[1]["overall_width"], 700.0)

    def test_duplex_preserves_fire_exit_fact_in_extra_info(self) -> None:
        result = parse_ifc(
            FIXTURES / "Duplex_A_with_fire_exit (1).ifc",
            strict=True,
        )
        self.assertEqual(result.ifc_schema, "IFC2X3")
        self.assertEqual(result.door_count, 14)
        self.assertTrue(all(door.building == "apartment" for door in result.doors))
        fire_exit_values = []
        for door in result.doors:
            revit = next(
                item
                for item in door.extra_info
                if item.source == "PSet_Revit_Type_Other"
            )
            fire_exit_values.append(revit.data["IsFireExit"])
        self.assertEqual(fire_exit_values.count(True), 4)
        self.assertEqual(fire_exit_values.count(False), 10)
        self.assertTrue(all(door.adjacent_spaces for door in result.doors))
        self.assertTrue(
            all(
                len({item.space.ifc_id for item in door.adjacent_spaces})
                == len(door.adjacent_spaces)
                for door in result.doors
            )
        )

    def test_school_limit_is_applied_before_door_extraction(self) -> None:
        source = FIXTURES / "00 - Primary school project (IFC).ifc"
        limited = parse_ifc(source, strict=True, max_doors=10)
        full = parse_ifc(source, strict=True)

        self.assertEqual(limited.total_ifc_door_count, 57)
        self.assertEqual(limited.requested_max_doors, 10)
        self.assertEqual(limited.door_count, 10)
        self.assertEqual(
            [door.ifc_guid for door in limited.doors],
            [door.ifc_guid for door in full.doors[:10]],
        )

    def test_limit_above_available_count_processes_all_doors(self) -> None:
        result = parse_ifc(
            FIXTURES / "20160414office_model_CV2_fordesign.ifc",
            strict=True,
            max_doors=100,
        )

        self.assertEqual(result.total_ifc_door_count, 9)
        self.assertEqual(result.requested_max_doors, 100)
        self.assertEqual(result.door_count, 9)

    def test_invalid_limits_are_rejected_before_opening_the_file(self) -> None:
        for invalid in (0, -1, True, 1.5, "all"):
            with self.subTest(invalid=invalid):
                with self.assertRaises(ValueError):
                    parse_ifc(
                        FIXTURES / "missing.ifc",
                        max_doors=invalid,  # type: ignore[arg-type]
                    )

    def test_building_fire_resistance_grade_normalization(self) -> None:
        self.assertEqual(_normalize_fire_resistance_grade("Grade I"), "一级")
        self.assertEqual(_normalize_fire_resistance_grade("III级"), "三级")
        self.assertEqual(_normalize_fire_resistance_grade("四级"), "四级")
        self.assertIsNone(_normalize_fire_resistance_grade("2h"))


if __name__ == "__main__":
    unittest.main()
