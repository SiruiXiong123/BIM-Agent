import json
from pathlib import Path

from src.schemas.assessment import ClassifiedEvacuationDoorRecord
from src.search.config import SearchConfig
from src.search.query_builder import build_retrieval_input, build_search_request
from src.search.models import PreSearchUserInputs


EXAMPLES = Path(__file__).parents[1] / "examples"


def _door_15600_record() -> ClassifiedEvacuationDoorRecord:
    input_rows = [
        json.loads(line)
        for line in (EXAMPLES / "primary_school_classification_input.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()
        if line.strip()
    ]
    output_rows = [
        json.loads(line)
        for line in (EXAMPLES / "primary_school_classification_output_v2_first10.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()
        if line.strip()
    ]
    facts = next(row for row in input_rows if row["door_id"] == "Door 15600")
    assessment = next(
        row for row in output_rows if row["ifc_guid"] == facts["ifc_guid"]
    )
    return ClassifiedEvacuationDoorRecord.model_validate(
        {**facts, "assessment": assessment}
    )


def _config() -> SearchConfig:
    return SearchConfig()


def test_door_15600_builds_the_agreed_retrieval_input() -> None:
    retrieval_input = build_retrieval_input(_door_15600_record())

    assert retrieval_input.subject.door_id == "Door 15600"
    assert retrieval_input.building_context.building_type == "primary_school"
    assert retrieval_input.building_context.storey_name == "Ground Floor"
    assert retrieval_input.building_context.storey_band == "above_ground_1_2"
    assert retrieval_input.building_context.fire_resistance_grade == "一级"
    assert retrieval_input.building_context.fire_resistance_grade_source == "default"
    assert retrieval_input.assessment.classification == "evacuation_door"
    assert retrieval_input.assessment.is_fire_door is False
    assert not hasattr(retrieval_input.assessment, "fire_door_confidence")
    assert not hasattr(retrieval_input.assessment, "effective_is_fire_door")
    assert not hasattr(retrieval_input.assessment, "fire_door_resolution")
    assert retrieval_input.task == "收集能判断疏散门净宽是否符合适用规范的相关信息但不做任何判断"
    assert retrieval_input.door_facts.occupant_load == 100
    assert retrieval_input.door_facts.occupant_load_source == "default"
    assert retrieval_input.missing_information == [
        "clear_width_conversion_rule",
        "adjacent_spaces relationships",
    ]


def test_door_15600_builds_one_complete_search_request() -> None:
    retrieval_input = build_retrieval_input(_door_15600_record())
    request = build_search_request(retrieval_input, _config())

    assert request.model_dump(mode="json") == {
        "task": "收集能判断疏散门净宽是否符合适用规范的相关信息但不做任何判断",
        "door_id": "Door 15600",
        "query_text": "primary_school Ground Floor above_ground_1_2 一级 door evacuation_door",
        "candidate_k": 50,
        "top_k": 3,
        "retrieval_context": {
            "building_type": "primary_school",
            "component_type": "door",
            "classification": "evacuation_door",
            "storey": "Ground Floor",
            "storey_band": "above_ground_1_2",
            "fire_resistance_grade": "一级",
        },
    }


def test_pre_search_user_inputs_fill_only_missing_ifc_values() -> None:
    record = _door_15600_record()
    resolved = build_retrieval_input(
        record,
        PreSearchUserInputs(
            occupant_load=240,
            fire_resistance_grade="四级",
        ),
    )

    assert resolved.door_facts.occupant_load == 240
    assert resolved.door_facts.occupant_load_source == "user"
    assert resolved.building_context.fire_resistance_grade == "四级"
    assert resolved.building_context.fire_resistance_grade_source == "user"

    ifc_record = record.model_copy(update={
        "occupant_load": 180,
        "occupant_load_source": "ifc",
        "fire_resistance_grade": "三级",
        "fire_resistance_grade_source": "ifc",
    })
    ifc_wins = build_retrieval_input(
        ifc_record,
        PreSearchUserInputs(
            occupant_load=240,
            fire_resistance_grade="四级",
        ),
    )

    assert ifc_wins.door_facts.occupant_load == 180
    assert ifc_wins.door_facts.occupant_load_source == "ifc"
    assert ifc_wins.building_context.fire_resistance_grade == "三级"
    assert ifc_wins.building_context.fire_resistance_grade_source == "ifc"
