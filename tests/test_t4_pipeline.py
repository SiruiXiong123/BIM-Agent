from __future__ import annotations

import json
from typing import Any

import pytest

from src.rules.calculation_context import build_t4_door_calculation_context
from src.rules.evidence_groups import (
    T4EvidenceNotReadyError,
    build_t4_evidence_package,
)
from src.rules.sandbox_runner import RuleSandboxError, run_validated_field_script
from src.rules.script_generator import generate_field_calculation
from src.rules.script_validator import (
    FieldScriptValidationError,
    validate_field_script,
)
from src.rules.service import execute_evacuation_door_rule
from src.schemas.result import CheckStatus
from src.schemas.rule import GeneratedFieldScript, ValidatedFieldScript
from src.search.iterative.building_evidence_cache import (
    BuildingEvidenceBundle,
    BuildingEvidenceCacheKey,
)
from src.search.iterative.models import (
    EvidenceHistoryItem,
    IFCContext,
    QueryHistoryItem,
)
from src.search.models import DEFAULT_RETRIEVAL_TASK
from tests.test_iterative_models import NANJING_DOCUMENT, _ifc_context


ACTUAL_ID = f"{NANJING_DOCUMENT}:text_actual"
REQUIRED_ID = f"{NANJING_DOCUMENT}:text_required"
INITIAL_QUERY = (
    "小学建筑地上一、二层的疏散门 Door 15600，IfcDoor.OverallWidth为"
    "3000mm，按非防火门处理，建筑耐火等级为一级，疏散人数为100人。"
    "根据规范证据分别计算实际净宽和表中每100人的净宽阈值。"
)


def _bundle() -> BuildingEvidenceBundle:
    actual = EvidenceHistoryItem(
        evidence_id=ACTUAL_ID,
        document_id=NANJING_DOCUMENT,
        content_id="text_actual",
        modality="text",
        content=(
            "疏散门净宽：防火门由门洞尺寸扣减150mm，其他门扣减100mm。"
        ),
        score=1.0,
        iter=1,
    )
    required = EvidenceHistoryItem(
        evidence_id=REQUIRED_ID,
        document_id=NANJING_DOCUMENT,
        content_id="text_required",
        modality="text",
        content=(
            "表8.2.3：地上一、二层，一、二级耐火等级每100人净宽0.70m。"
        ),
        score=1.0,
        iter=2,
    )
    return BuildingEvidenceBundle(
        key=BuildingEvidenceCacheKey(
            project_id="primary-school",
            building_type="primary_school",
            task=DEFAULT_RETRIEVAL_TASK,
            available_documents=(NANJING_DOCUMENT,),
        ),
        source_ifc_guid="guid-15600",
        source_door_id="Door 15600",
        evidence_history=(actual, required),
        query_history=(
            QueryHistoryItem(
                hop=1,
                query=INITIAL_QUERY,
                dense_query="Calculate both current clear-width values.",
                target_document=NANJING_DOCUMENT,
                result_count=1,
                evidence_ids=[ACTUAL_ID],
            ),
            QueryHistoryItem(
                hop=2,
                query="读取表8.2.3当前条件对应的每100人净宽值。",
                dense_query="Read the applicable Table 8.2.3 value.",
                target_document=NANJING_DOCUMENT,
                result_count=1,
                evidence_ids=[REQUIRED_ID],
            ),
        ),
        actual_clear_width_calculation_ready=True,
        actual_clear_width_evidence_ids=(ACTUAL_ID,),
        required_clear_width_calculation_ready=True,
        required_clear_width_evidence_ids=(REQUIRED_ID,),
    )


def _script_response(target_field: str) -> dict[str, Any]:
    if target_field == "actual_clear_width_mm":
        source = (
            "def calculate_value() -> dict:\n"
            "    value_mm = 3000 - 100\n"
            "    return {'value_mm': value_mm}\n"
        )
        evidence_ids = [ACTUAL_ID]
    else:
        source = (
            "def calculate_value() -> dict:\n"
            "    value_mm = 0.70 * 100 / 100 * 1000\n"
            "    return {'value_mm': value_mm}\n"
        )
        evidence_ids = [REQUIRED_ID]
    return {
        "target_field": target_field,
        "resolution": "python_script",
        "value_mm": None,
        "language": "python",
        "entrypoint": "calculate_value",
        "source": source,
        "evidence_ids": evidence_ids,
    }


def _direct_response(
    target_field: str,
    value_mm: float,
    evidence_ids: list[str],
) -> dict[str, Any]:
    return {
        "target_field": target_field,
        "resolution": "direct_value",
        "value_mm": value_mm,
        "language": None,
        "entrypoint": None,
        "source": None,
        "evidence_ids": evidence_ids,
    }


def _script_contract(target_field: str) -> dict[str, Any]:
    response = _script_response(target_field)
    return {
        key: response[key]
        for key in (
            "target_field",
            "language",
            "entrypoint",
            "source",
            "evidence_ids",
        )
    }


class FakeDirectScriptClient:
    model_name = "fake-direct-script"

    def __init__(self) -> None:
        self.contexts: list[dict[str, Any]] = []

    def complete_json_multimodal(
        self,
        *,
        system_prompt: str,
        content: list[dict[str, Any]],
    ) -> dict[str, Any]:
        context = json.loads(content[0]["text"])["context"]
        self.contexts.append(context)
        return _script_response(context["target_field"])

    def complete_json(self, **_: Any) -> dict[str, Any]:
        raise AssertionError("T4 direct generation must be multimodal")


class FailIfCalledClient:
    model_name = "must-not-run"

    def complete_json_multimodal(self, **_: Any) -> dict[str, Any]:
        raise AssertionError("VLM must not be called")

    def complete_json(self, **_: Any) -> dict[str, Any]:
        raise AssertionError("LLM must not be called")


class FakeDirectValueClient(FakeDirectScriptClient):
    def complete_json_multimodal(
        self,
        *,
        system_prompt: str,
        content: list[dict[str, Any]],
    ) -> dict[str, Any]:
        context = json.loads(content[0]["text"])["context"]
        self.contexts.append(context)
        if context["target_field"] == "actual_clear_width_mm":
            return _direct_response("actual_clear_width_mm", 1250, [])
        return _direct_response(
            "required_clear_width_mm",
            900,
            [REQUIRED_ID],
        )


def test_t4_groups_contain_only_initial_query_and_assigned_evidence() -> None:
    package = build_t4_evidence_package(_bundle())

    assert package.actual_clear_width.initial_query.query == INITIAL_QUERY
    assert package.actual_clear_width.evidence_ids == (ACTUAL_ID,)
    assert package.required_clear_width.evidence_ids == (REQUIRED_ID,)
    assert not hasattr(package.actual_clear_width, "evidence_queries")


def test_t4_rejects_insufficient_or_queryless_t3_before_vlm() -> None:
    insufficient = _bundle().model_copy(update={
        "required_clear_width_calculation_ready": False,
        "required_clear_width_evidence_ids": (),
    })
    with pytest.raises(T4EvidenceNotReadyError, match="required-clear-width"):
        build_t4_evidence_package(insufficient)

    queryless = _bundle().model_copy(update={"query_history": ()})
    with pytest.raises(T4EvidenceNotReadyError, match="query history"):
        build_t4_evidence_package(queryless)


def test_direct_generator_sends_required_door_context_and_evidence() -> None:
    client = FakeDirectScriptClient()
    group = build_t4_evidence_package(_bundle()).required_clear_width
    calculation_context = build_t4_door_calculation_context(_ifc_context())

    generated = generate_field_calculation(
        evidence_group=group,
        calculation_context=calculation_context,
        client=client,
    )

    assert generated.value.target_field == "required_clear_width_mm"
    assert generated.evidence_ids == (REQUIRED_ID,)
    assert client.contexts == [{
        "initial_query": INITIAL_QUERY,
        "target_field": "required_clear_width_mm",
        "current_door_context": {
            "door_id": "Door 15600",
            "building_type": "primary_school",
            "storey_name": "Ground Floor",
            "storey_band": "above_ground_1_2",
            "fire_resistance_grade": "一级",
            "fire_resistance_grade_source": "default",
            "occupant_load": 100,
            "occupant_load_source": "default",
        },
        "assigned_evidence_ids": [REQUIRED_ID],
    }]


def test_actual_and_required_generation_receive_separate_door_facts() -> None:
    context = build_t4_door_calculation_context(_ifc_context())

    assert context.for_target_field("actual_clear_width_mm") == {
        "door_id": "Door 15600",
        "overall_width_mm": 3000.0,
        "explicit_clear_width_mm": None,
        "explicit_clear_width_source": None,
        "ifc_extra_info": [],
        "is_fire_door": False,
    }
    required = context.for_target_field("required_clear_width_mm")
    assert required["fire_resistance_grade"] == "一级"
    assert required["fire_resistance_grade_source"] == "default"
    assert required["occupant_load"] == 100
    assert required["occupant_load_source"] == "default"
    assert "overall_width_mm" not in required
    assert "occupant_load" not in context.for_target_field(
        "actual_clear_width_mm"
    )


def test_script_validator_rejects_wrong_evidence_and_unsafe_code() -> None:
    wrong_evidence = _script_response("actual_clear_width_mm")
    wrong_evidence["evidence_ids"] = [REQUIRED_ID]
    with pytest.raises(FieldScriptValidationError, match="outside its T3 group"):
        validate_field_script(
            GeneratedFieldScript.model_validate(
                _script_contract("actual_clear_width_mm")
                | {"evidence_ids": [REQUIRED_ID]}
            ),
            target_field="actual_clear_width_mm",
            allowed_evidence={ACTUAL_ID},
        )

    unsafe = _script_contract("actual_clear_width_mm")
    unsafe["source"] = (
        "def calculate_value() -> dict:\n"
        "    import os\n"
        "    return {'value_mm': 2900}\n"
    )
    with pytest.raises(FieldScriptValidationError, match="forbidden syntax"):
        validate_field_script(
            GeneratedFieldScript.model_validate(unsafe),
            target_field="actual_clear_width_mm",
            allowed_evidence={ACTUAL_ID},
        )


def test_sandbox_runs_no_argument_fixed_calculation() -> None:
    script = validate_field_script(
        GeneratedFieldScript.model_validate(
            _script_contract("actual_clear_width_mm")
        ),
        target_field="actual_clear_width_mm",
        allowed_evidence={ACTUAL_ID},
    )

    result = run_validated_field_script(script)

    assert result.value_mm == 2900


def test_validator_allows_safe_int_conversion() -> None:
    payload = _script_contract("required_clear_width_mm")
    payload["source"] = (
        "def calculate_value() -> dict:\n"
        "    value_mm = int(0.70 * 1000)\n"
        "    return {'value_mm': value_mm}\n"
    )
    script = validate_field_script(
        GeneratedFieldScript.model_validate(payload),
        target_field="required_clear_width_mm",
        allowed_evidence={REQUIRED_ID},
    )

    result = run_validated_field_script(script)

    assert result.value_mm == 700


def test_sandbox_reports_generated_runtime_error() -> None:
    script = ValidatedFieldScript(
        target_field="required_clear_width_mm",
        source=(
            "def calculate_value() -> dict:\n"
            "    return {'value_mm': 1 / 0}\n"
        ),
        source_hash="0" * 64,
        evidence_ids=(REQUIRED_ID,),
    )
    with pytest.raises(RuleSandboxError, match="generated field failed"):
        run_validated_field_script(script)


def test_direct_t4_generates_2900_and_700_then_passes() -> None:
    client = FakeDirectScriptClient()

    result = execute_evacuation_door_rule(
        evidence_bundle=_bundle(),
        ifc_context=_ifc_context(),
        client=client,
    )

    assert result.calculation is not None
    assert result.calculation.actual_clear_width_mm == 2900
    assert result.calculation.required_clear_width_mm == 700
    assert result.check_result.result is CheckStatus.PASS
    assert [context["target_field"] for context in client.contexts] == [
        "actual_clear_width_mm",
        "required_clear_width_mm",
    ]
    assert client.contexts[0]["current_door_context"]["overall_width_mm"] == 3000
    assert client.contexts[0]["current_door_context"]["is_fire_door"] is False
    assert client.contexts[1]["current_door_context"]["occupant_load"] == 100
    assert (
        client.contexts[1]["current_door_context"]["fire_resistance_grade"]
        == "一级"
    )
    assert result.resolution_modes == {
        "actual_clear_width_mm": "python_script",
        "required_clear_width_mm": "python_script",
    }
    assert result.field_evidence_ids == {
        "actual_clear_width_mm": (ACTUAL_ID,),
        "required_clear_width_mm": (REQUIRED_ID,),
    }


def test_t4_vlm_can_return_direct_values_for_both_fields() -> None:
    context_data = _ifc_context().model_dump(mode="json")
    context_data["door_facts"]["extra_info"] = [{
        "source": "Pset_DoorCommon",
        "data": {"AccessibleClearOpeningWidth": 1250.0},
    }]
    ifc_context = IFCContext.model_validate(context_data)
    client = FakeDirectValueClient()

    result = execute_evacuation_door_rule(
        evidence_bundle=_bundle(),
        ifc_context=ifc_context,
        client=client,
    )

    assert result.calculation is not None
    assert result.calculation.actual_clear_width_mm == 1250
    assert result.calculation.required_clear_width_mm == 900
    assert result.scripts == {}
    assert result.resolution_modes == {
        "actual_clear_width_mm": "ifc_direct",
        "required_clear_width_mm": "evidence_direct",
    }
    assert result.field_evidence_ids == {
        "actual_clear_width_mm": (),
        "required_clear_width_mm": (REQUIRED_ID,),
    }
    assert client.contexts[0]["current_door_context"]["ifc_extra_info"] == [{
        "source": "Pset_DoorCommon",
        "data": {"AccessibleClearOpeningWidth": 1250.0},
    }]
