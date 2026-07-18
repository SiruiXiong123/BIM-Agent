import json
from typing import Any

import pytest

from src.search.iterative.controller import (
    IterativeControllerError,
    decide_next_action,
)
from src.search.iterative.models import (
    EvidenceHistoryItem,
    IFCContext,
    IterativeRetrievalState,
    QueryHistoryItem,
)
from tests.test_iterative_models import NANJING_DOCUMENT, _ifc_context


class FakeControllerClient:
    model_name = "fake-controller"

    def __init__(self, response: dict[str, Any]) -> None:
        self.response = response

    def complete_json(
        self, *, system_prompt: str, payload: dict[str, Any]
    ) -> dict[str, Any]:
        self.system_prompt = system_prompt
        self.payload = payload
        return self.response

    def complete_json_multimodal(
        self, *, system_prompt: str, content: list[dict[str, Any]]
    ) -> dict[str, Any]:
        self.system_prompt = system_prompt
        self.content = content
        return self.response


class SequencedControllerClient:
    model_name = "sequenced-controller"

    def __init__(self, responses: list[dict[str, Any]]) -> None:
        self.responses = list(responses)
        self.contents: list[list[dict[str, Any]]] = []

    def complete_json_multimodal(
        self, *, system_prompt: str, content: list[dict[str, Any]]
    ) -> dict[str, Any]:
        self.contents.append(content)
        return self.responses.pop(0)


def _state(*, hop: int = 1, max_hops: int = 3) -> IterativeRetrievalState:
    evidence = EvidenceHistoryItem(
        evidence_id=f"{NANJING_DOCUMENT}:table_000020",
        document_id=NANJING_DOCUMENT,
        content_id="table_000020",
        modality="text",
        page=24,
        content="疏散门净宽度应依据相关建筑设计规范确定。",
        score=0.0322,
        retrievers=["bm25", "dense"],
        retrieved_at_hop=1,
    )
    query_history = [
        QueryHistoryItem(
            hop=1,
            query="小学首层疏散门净宽度检查需要哪些模型数据和判定规则？",
            dense_query="What model data and rules are required for a primary-school evacuation door clear-width check?",
            target_document=NANJING_DOCUMENT,
            result_count=1,
            evidence_ids=[evidence.evidence_id],
        )
    ]
    if hop > 1:
        query_history.extend(
            QueryHistoryItem(
                hop=index,
                query=f"第{index}轮已经执行的不同自然语言问题是什么？",
                dense_query=f"What distinct natural-language question was executed at hop {index}?",
                target_document=NANJING_DOCUMENT,
                result_count=0,
            )
            for index in range(2, hop + 1)
        )
    context_data = _ifc_context().model_dump(mode="python")
    context_data["clear_width_resolution"].update({
        "clear_width": 1200.0,
        "source": "IFC explicit ClearWidth property",
        "method": "explicit_ifc_property",
    })
    return IterativeRetrievalState(
        task="收集能判断疏散门净宽检查的相关信息但不做任何判断",
        original_query="检查上传IFC模型中的疏散门净宽度是否符合规范。",
        ifc_context=IFCContext.model_validate(context_data),
        available_documents=[NANJING_DOCUMENT],
        evidence_history=[evidence],
        query_history=query_history,
        hop=hop,
        max_hops=max_hops,
    )


def _search_response() -> dict[str, Any]:
    return {
        "action": "search",
        "found_evidence": ["当前文档要求引用相关建筑设计规范。"],
        "evidence_ids": [f"{NANJING_DOCUMENT}:table_000020"],
        "missing_evidence": ["小学疏散门净宽度阈值及适用条件。"],
        "actual_clear_width_calculation_ready": True,
        "actual_clear_width_evidence_ids": [
            f"{NANJING_DOCUMENT}:table_000020"
        ],
        "required_clear_width_calculation_ready": "false",
        "required_clear_width_evidence_ids": [
            f"{NANJING_DOCUMENT}:table_000020"
        ],
        "query": "小学首层疏散门适用的最小净宽度阈值和适用条件是什么？",
        "dense_query": "What minimum clear-width threshold and conditions apply to a ground-floor primary-school evacuation door?",
        "target_document": NANJING_DOCUMENT,
        "reason": "现有证据仅给出转引要求，尚缺少具体阈值。",
    }


def test_controller_returns_validated_search_decision() -> None:
    client = FakeControllerClient(_search_response())
    state = _state()

    decision = decide_next_action(state, client)

    assert not hasattr(decision, "found_evidence")

    assert decision.action == "search"
    context = json.loads(client.content[0]["text"])["context"]
    assert context == state.model_dump(mode="json", exclude={"evidence_history"})
    serialized = "\n".join(
        part["text"] for part in client.content if part["type"] == "text"
    )
    assert state.evidence_history[0].content in serialized
    assert "完整自然语言问题" in client.system_prompt


def test_controller_repairs_invalid_decision_without_new_retrieval_hop() -> None:
    invalid = {
        "action": "finish",
        "found_evidence": ["must not survive repair"],
        "evidence_ids": [],
        "missing_evidence": ["缺少规范阈值证据。"],
        "extra_info": [],
        "actual_clear_width_calculation_ready": True,
        "actual_clear_width_evidence_ids": [
            f"{NANJING_DOCUMENT}:table_000020"
        ],
        "required_clear_width_calculation_ready": False,
        "required_clear_width_evidence_ids": [],
        "query": None,
        "dense_query": None,
        "target_document": None,
    }
    client = SequencedControllerClient([invalid, _search_response()])

    decision = decide_next_action(_state(), client)

    assert decision.action == "search"
    assert len(client.contents) == 2
    first_context = json.loads(client.contents[0][0]["text"])["context"]
    second_context = json.loads(client.contents[1][0]["text"])["context"]
    assert "repair_context" not in first_context
    repair = second_context["repair_context"]
    assert repair["attempt"] == 2
    assert "reason" in repair["validation_errors"][0]
    assert "found_evidence" not in repair["previous_invalid_response"]
    assert len(_state().query_history) == 1


def test_controller_rejects_unknown_evidence_id() -> None:
    response = _search_response()
    response["evidence_ids"] = ["unknown:evidence"]

    with pytest.raises(IterativeControllerError, match="unknown evidence IDs"):
        decide_next_action(_state(), FakeControllerClient(response))


def test_controller_rejects_unavailable_target_document() -> None:
    response = _search_response()
    response["target_document"] = "不存在的规范"

    with pytest.raises(IterativeControllerError, match="available_documents"):
        decide_next_action(_state(), FakeControllerClient(response))


def test_controller_resolves_unique_document_title_without_page_suffix() -> None:
    response = _search_response()
    response["target_document"] = "中小学校设计规范GB 50099—2011"
    state = _state()
    state.available_documents.append(
        "中小学校设计规范GB 50099—2011(page1-50)"
    )

    decision = decide_next_action(state, FakeControllerClient(response))

    assert (
        decision.target_document
        == "中小学校设计规范GB 50099—2011(page1-50)"
    )


def test_controller_rejects_duplicate_query() -> None:
    response = _search_response()
    response["query"] = "小学首层疏散门，净宽度检查需要哪些模型数据和判定规则？"

    with pytest.raises(IterativeControllerError, match="duplicates"):
        decide_next_action(_state(), FakeControllerClient(response))


def test_controller_converts_search_to_insufficient_at_max_hops() -> None:
    decision = decide_next_action(
        _state(hop=3, max_hops=3),
        FakeControllerClient(_search_response()),
    )

    assert decision.action == "insufficient_evidence"


def test_controller_allows_terminal_decision_at_max_hops() -> None:
    evidence_id = f"{NANJING_DOCUMENT}:table_000020"
    response = {
        "action": "insufficient_evidence",
        "found_evidence": [],
        "evidence_ids": [],
        "missing_evidence": ["缺少明确阈值。"],
        "actual_clear_width_calculation_ready": True,
        "actual_clear_width_evidence_ids": [evidence_id],
        "required_clear_width_calculation_ready": False,
        "required_clear_width_evidence_ids": [],
        "query": None,
        "dense_query": None,
        "target_document": None,
        "reason": "已达到最大轮次，现有证据不足。",
    }

    decision = decide_next_action(
        _state(hop=3, max_hops=3), FakeControllerClient(response)
    )

    assert decision.action == "insufficient_evidence"


def test_controller_does_not_override_model_actual_readiness_from_ifc_value() -> None:
    response = _search_response()
    response["actual_clear_width_calculation_ready"] = False
    response["actual_clear_width_evidence_ids"] = []

    decision = decide_next_action(_state(), FakeControllerClient(response))

    assert decision.action == "search"
    assert decision.actual_clear_width_calculation_ready is False
    assert decision.actual_clear_width_evidence_ids == []


def test_controller_finishes_only_when_both_evidence_groups_are_ready() -> None:
    response = {
        "action": "search",
        "found_evidence": ["已找到按人数和耐火等级查表的规则。"],
        "evidence_ids": [f"{NANJING_DOCUMENT}:table_000020"],
        "missing_evidence": [],
        "extra_info": [],
        "actual_clear_width_calculation_ready": True,
        "actual_clear_width_evidence_ids": [
            f"{NANJING_DOCUMENT}:table_000020"
        ],
        "required_clear_width_calculation_ready": True,
        "required_clear_width_evidence_ids": [
            f"{NANJING_DOCUMENT}:table_000020"
        ],
        "query": "This will be cleared by the deterministic controller.",
        "dense_query": "This will be cleared by the deterministic controller.",
        "target_document": NANJING_DOCUMENT,
        "reason": "缺少耐火等级，无法选择唯一表格单元格。",
    }

    decision = decide_next_action(_state(), FakeControllerClient(response))

    assert decision.action == "finish"


def test_controller_follows_reference_instead_of_accepting_false_readiness() -> None:
    state = _state()
    target_document = "中小学校设计规范GB 50099—2011(page1-50)"
    evidence_data = state.evidence_history[0].model_dump(mode="python")
    evidence_data["cross_document_references"] = [{
        "target_document": target_document,
        "target_locator": "表8.2.3",
    }]
    evidence = EvidenceHistoryItem.model_validate(evidence_data)
    state_data = state.model_dump(mode="python")
    state_data["available_documents"].append(target_document)
    state_data["evidence_history"] = [evidence]
    state_data["pending_cross_document_references"] = [
        {
            "target_document": target_document,
            "target_locator": "表8.2.3",
        }
    ]
    state = IterativeRetrievalState.model_validate(state_data)
    response = {
        "action": "finish",
        "found_evidence": [],
        "evidence_ids": [evidence.evidence_id],
        "missing_evidence": [],
        "extra_info": [],
        "actual_clear_width_calculation_ready": True,
        "actual_clear_width_evidence_ids": [evidence.evidence_id],
        "required_clear_width_calculation_ready": True,
        "required_clear_width_evidence_ids": [evidence.evidence_id],
        "query": None,
        "dense_query": None,
        "target_document": None,
        "reason": "The cited table has not actually been retrieved.",
    }

    decision = decide_next_action(state, FakeControllerClient(response))

    assert decision.action == "search"
    assert decision.required_clear_width_calculation_ready is False
    assert decision.target_document == target_document
    assert "表8.2.3" in decision.query
