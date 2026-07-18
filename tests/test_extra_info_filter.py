"""Tests for evacuation evidence filtering."""

import json
import tempfile
import unittest
from pathlib import Path

from src.extra_info_filter import (
    filter_door_extra_info,
    filter_extra_info,
    filter_jsonl,
)
from src.schemas.bim import ExtraInfoItem
from tests.test_pipeline_components import make_door


class ExtraInfoFilterTests(unittest.TestCase):
    def test_keeps_only_whitelisted_fields_grouped_by_source(self) -> None:
        result = filter_extra_info(
            [
                ExtraInfoItem(
                    source="AC_Equantity_Door_19",
                    data={
                        "Egress Width": 830.0,
                        "Egress Height": 2065.0,
                        "Leaf Area": 1.8,
                    },
                ),
                ExtraInfoItem(
                    source="ArchiCADProperties",
                    data={"From Zone": "Exit lobby", "Acoustic Rating": 35},
                ),
                ExtraInfoItem(source="Unrelated", data={"IsFireExit": True}),
            ]
        )

        self.assertEqual(
            [item.model_dump() for item in result],
            [
                {
                    "source": "AC_Equantity_Door_19",
                    "data": {"Egress Width": 830.0, "Egress Height": 2065.0},
                },
                {
                    "source": "ArchiCADProperties",
                    "data": {"From Zone": "Exit lobby"},
                },
            ],
        )

    def test_retains_false_and_zero_but_removes_empty_values(self) -> None:
        result = filter_extra_info(
            [
                ExtraInfoItem(
                    source="PSet_Revit_Type_Other",
                    data={"IsFireExit": False},
                ),
                ExtraInfoItem(
                    source="Pset_DoorCommon",
                    data={"FireRating": "  "},
                ),
                ExtraInfoItem(
                    source="AC_Equantity_Door_19",
                    data={"Egress Width": 0},
                ),
            ]
        )

        self.assertEqual(result[0].data, {"IsFireExit": False})
        self.assertEqual(result[1].data, {"Egress Width": 0})
        self.assertEqual(len(result), 2)

    def test_matching_is_case_insensitive_without_renaming_output(self) -> None:
        result = filter_extra_info(
            [ExtraInfoItem(source="pset_doorcommon", data={"firerating": "60min"})]
        )

        self.assertEqual(
            result[0].model_dump(),
            {"source": "pset_doorcommon", "data": {"firerating": "60min"}},
        )

    def test_door_filter_returns_copy_without_mutating_original(self) -> None:
        door = make_door(
            extra_info=[
                ExtraInfoItem(
                    source="PSet_Revit_Type_Other",
                    data={"IsFireExit": True, "Manufacturer": "Example"},
                )
            ]
        )

        filtered = filter_door_extra_info(door)

        self.assertIsNot(filtered, door)
        self.assertEqual(filtered.extra_info[0].data, {"IsFireExit": True})
        self.assertIn("Manufacturer", door.extra_info[0].data)

    def test_jsonl_filter_preserves_all_fields_except_filtered_extra_info(self) -> None:
        metadata = {
            "record_type": "ifc_parse_metadata",
            "source_file": "sample.ifc",
            "door_count": 1,
        }
        door = {
            "record_type": "door",
            "door_index": 1,
            "ifc_guid": "guid",
            "overall_width": 900.0,
            "custom_top_level_field": {"unchanged": True},
            "extra_info": [
                {
                    "source": "PSet_Revit_Type_Other",
                    "data": {"IsFireExit": False, "Manufacturer": "Example"},
                },
                {"source": "Unrelated", "data": {"Foo": "bar"}},
            ],
        }

        with tempfile.TemporaryDirectory() as directory:
            input_path = Path(directory) / "input.jsonl"
            output_path = Path(directory) / "output.jsonl"
            input_path.write_text(
                "\n".join(json.dumps(row) for row in (metadata, door)) + "\n",
                encoding="utf-8",
            )

            result_path = filter_jsonl(input_path, output_path)
            records = [
                json.loads(line)
                for line in result_path.read_text(encoding="utf-8").splitlines()
            ]

        self.assertEqual(records[0], metadata)
        expected_door = dict(door)
        expected_door["extra_info"] = [
            {
                "source": "PSet_Revit_Type_Other",
                "data": {"IsFireExit": False},
            }
        ]
        self.assertEqual(records[1], expected_door)


if __name__ == "__main__":
    unittest.main()
