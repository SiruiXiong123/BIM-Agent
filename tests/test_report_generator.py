from __future__ import annotations

import json
from typing import Any

import pytest

from src.report_generator import (
    DetailedReasonGenerationError,
    T5_RESULT_LABELS,
    generate_detailed_reason,
)
from src.rules.service import execute_evacuation_door_rule
from src.schemas.result import CheckStatus
from tests.test_iterative_models import _ifc_context
from tests.test_t4_pipeline import (
    ACTUAL_ID,
    REQUIRED_ID,
    FakeDirectScriptClient,
    _bundle,
)


class FakeReasonClient:
    model_name = "fake-report-reason"

    def __init__(self, evidence_ids: list[str] | None = None) -> None:
        self.context: dict[str, Any] | None = None
        self.evidence_ids = evidence_ids or [ACTUAL_ID, REQUIRED_ID]

    def complete_json_multimodal(
        self,
        *,
        system_prompt: str,
        content: list[dict[str, Any]],
    ) -> dict[str, Any]:
        self.context = json.loads(content[0]["text"])["context"]
        return {
            "detailed_reason": (
                "Door 15600按非防火门扣减规则得到实际净宽2900mm；"
                "表8.2.3对应要求为700mm，因此既定结果为PASS。"
            ),
            "evidence_ids": self.evidence_ids,
        }

    def complete_json(self, **_: Any) -> dict[str, Any]:
        raise AssertionError("T5 detailed reason must use multimodal evidence")


def _t4_result():
    return execute_evacuation_door_rule(
        evidence_bundle=_bundle(),
        ifc_context=_ifc_context(),
        client=FakeDirectScriptClient(),
    )


def test_t5_sends_t4_values_context_and_exact_used_evidence() -> None:
    client = FakeReasonClient()

    report = generate_detailed_reason(
        t4_result=_t4_result(),
        ifc_context=_ifc_context(),
        client=client,
    )

    assert report.evidence_ids == (ACTUAL_ID, REQUIRED_ID)
    assert report.result == "合格"
    assert not hasattr(report, "markdown")
    assert client.context is not None
    assert client.context["door_id"] == "Door 15600"
    assert client.context["current_door_context"]["overall_width_mm"] == 3000
    assert client.context["calculation"] == {
        "actual_clear_width_mm": 2900.0,
        "required_clear_width_mm": 700.0,
        "difference_mm": 2200.0,
        "result": "合格",
    }
    details = client.context["calculation_details"]
    assert details["actual_clear_width_mm"]["resolution_mode"] == "python_script"
    assert "3000 - 100" in details["actual_clear_width_mm"]["python_source"]
    assert details["required_clear_width_mm"]["evidence_ids"] == [REQUIRED_ID]
    assert client.context["evidence_groups"] == {
        "actual_clear_width_evidence_ids": [ACTUAL_ID],
        "required_clear_width_evidence_ids": [REQUIRED_ID],
    }


def test_t5_rejects_evidence_not_used_by_t4() -> None:
    client = FakeReasonClient(evidence_ids=["another:evidence"])

    with pytest.raises(DetailedReasonGenerationError, match="not used by T4"):
        generate_detailed_reason(
            t4_result=_t4_result(),
            ifc_context=_ifc_context(),
            client=client,
        )


def test_t5_maps_machine_statuses_to_chinese_result_labels() -> None:
    assert T5_RESULT_LABELS == {
        CheckStatus.PASS: "合格",
        CheckStatus.FAIL: "不合格",
    }
