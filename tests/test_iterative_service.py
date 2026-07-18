import json
from pathlib import Path
from typing import Any

from src.search.config import SearchConfig
from src.search.document_catalog import DocumentCatalog, DocumentDescriptor
from src.search.iterative.service import run_iterative_retrieval
from src.search.models import SearchHit
from src.search.query_rewriter import DEFAULT_INITIAL_DOCUMENT
from tests.test_iterative_models import _ifc_context


def _resolved_ifc_context():
    context = _ifc_context()
    data = context.model_dump(mode="python")
    data["clear_width_resolution"].update({
        "clear_width": 2900.0,
        "source": "explicit test value",
        "method": "explicit",
    })
    return type(context).model_validate(data)


SECOND_DOCUMENT = "中小学校设计规范GB 50099—2011(page1-50)"


class FakeServiceClient:
    model_name = "fake-service"

    def __init__(self, decisions: list[dict[str, Any]]) -> None:
        self.decisions = list(decisions)
        self.controller_payloads: list[dict[str, Any]] = []

    def complete_json(
        self, *, system_prompt: str, payload: dict[str, Any]
    ) -> dict[str, Any]:
        if "target_document" in payload:
            return {
                "query": "小学首层疏散门需要适用哪些净宽度审查要求？",
                "dense_query": "What clear-width review requirements apply to a ground-floor primary-school evacuation door?",
                "target_document": payload["target_document"],
                "reason": "生成首轮规范检索问题。",
            }
        raise AssertionError("controller must use the multimodal client method")

    def complete_json_multimodal(
        self, *, system_prompt: str, content: list[dict[str, Any]]
    ) -> dict[str, Any]:
        self.controller_payloads.append({"content": content})
        return self.decisions.pop(0)


class FakeRetriever:
    def __init__(self, document_id: str, calls: list[tuple[str, str]]) -> None:
        self.document_id = document_id
        self.calls = calls
        self.hit_count = 0

    def search(
        self,
        query: str,
        *,
        dense_query: str | None = None,
        top_k: int | None = None,
    ) -> list[SearchHit]:
        self.calls.append((self.document_id, f"{query}|{dense_query}"))
        self.hit_count += 1
        return [
            SearchHit(
                id=f"text_{self.hit_count:06d}",
                document_id=self.document_id,
                modality="text",
                rank=1,
                score=0.03,
                page=len(self.calls),
                content=f"{self.document_id} 的召回证据",
                retrievers=["bm25", "dense"],
            )
        ]


class DeductionEvidenceRetriever(FakeRetriever):
    def search(
        self,
        query: str,
        *,
        dense_query: str | None = None,
        top_k: int | None = None,
    ) -> list[SearchHit]:
        hits = super().search(query, dense_query=dense_query, top_k=top_k)
        return [
            hits[0].model_copy(update={
                "content": (
                    "防火门门洞尺寸扣减150 mm，其他门门洞尺寸扣减100 mm。"
                )
            })
        ]


def _catalog(tmp_path: Path) -> DocumentCatalog:
    documents = [
        DocumentDescriptor(
            document_id=document_id,
            title=document_id,
            index_dir=tmp_path / document_id,
            aliases=(document_id,),
        )
        for document_id in (DEFAULT_INITIAL_DOCUMENT, SECOND_DOCUMENT)
    ]
    return DocumentCatalog(tmp_path, documents)


def _terminal(action: str = "finish") -> dict[str, Any]:
    resolved = action == "finish"
    actual_evidence_id = f"{DEFAULT_INITIAL_DOCUMENT}:text_000001"
    return {
        "action": action,
        "found_evidence": [],
        "evidence_ids": [],
        "missing_evidence": [],
        "actual_clear_width_calculation_ready": True,
        "actual_clear_width_evidence_ids": [actual_evidence_id],
        "required_clear_width_calculation_ready": resolved,
        "required_clear_width_evidence_ids": (
            [f"{DEFAULT_INITIAL_DOCUMENT}:text_000001"] if resolved else []
        ),
        "query": None,
        "dense_query": None,
        "target_document": None,
        "reason": "测试终止。",
    }


def test_service_finishes_after_first_retrieval(tmp_path: Path) -> None:
    calls: list[tuple[str, str]] = []
    built: list[str] = []

    def factory(descriptor: DocumentDescriptor) -> FakeRetriever:
        built.append(descriptor.document_id)
        return FakeRetriever(descriptor.document_id, calls)

    result = run_iterative_retrieval(
        task="收集能判断疏散门净宽检查的相关信息但不做任何判断",
        original_query="检查上传IFC模型中的疏散门净宽度。",
        ifc_context=_resolved_ifc_context(),
        catalog=_catalog(tmp_path),
        client=FakeServiceClient([_terminal()]),
        retriever_factory=factory,
    )

    assert result.action == "finish"
    assert not hasattr(result, "found_evidence")
    assert result.actual_clear_width_calculation_ready is True
    assert result.required_clear_width_calculation_ready is True
    assert result.required_clear_width_evidence_ids == [
        f"{DEFAULT_INITIAL_DOCUMENT}:text_000001"
    ]
    assert result.hop == 1
    assert len(result.query_history) == 1
    assert len(result.evidence_history) == 1
    assert built == [DEFAULT_INITIAL_DOCUMENT]
    assert calls[0][0] == DEFAULT_INITIAL_DOCUMENT


def test_service_follows_document_switch_and_returns_insufficient(
    tmp_path: Path,
) -> None:
    first_evidence_id = f"{DEFAULT_INITIAL_DOCUMENT}:text_000001"
    decisions = [
        {
            "action": "search",
            "found_evidence": ["首份文档仅给出转引。"],
            "evidence_ids": [first_evidence_id],
            "missing_evidence": ["具体净宽度阈值。"],
            "actual_clear_width_calculation_ready": True,
            "actual_clear_width_evidence_ids": [first_evidence_id],
            "required_clear_width_calculation_ready": False,
            "required_clear_width_evidence_ids": [first_evidence_id],
            "query": "小学首层疏散门的最小净宽度阈值和适用条件是什么？",
            "dense_query": "What minimum clear-width threshold and conditions apply to a ground-floor primary-school evacuation door?",
            "target_document": SECOND_DOCUMENT,
            "reason": "需要查询转引的学校设计规范。",
        },
        _terminal("insufficient_evidence"),
    ]
    calls: list[tuple[str, str]] = []
    built: list[str] = []

    def factory(descriptor: DocumentDescriptor) -> FakeRetriever:
        built.append(descriptor.document_id)
        return FakeRetriever(descriptor.document_id, calls)

    result = run_iterative_retrieval(
        task="收集能判断疏散门净宽检查的相关信息但不做任何判断",
        original_query="检查上传IFC模型中的疏散门净宽度。",
        ifc_context=_resolved_ifc_context(),
        catalog=_catalog(tmp_path),
        client=FakeServiceClient(decisions),
        retriever_factory=factory,
    )

    assert result.action == "insufficient_evidence"
    assert result.actual_clear_width_calculation_ready is True
    assert result.required_clear_width_calculation_ready is False
    assert result.hop == 2
    assert built == [DEFAULT_INITIAL_DOCUMENT, SECOND_DOCUMENT]
    assert result.query_history[1].target_document == SECOND_DOCUMENT


def test_service_reuses_retriever_for_same_document(tmp_path: Path) -> None:
    first_evidence_id = f"{DEFAULT_INITIAL_DOCUMENT}:text_000001"
    decisions = [
        {
            "action": "search",
            "found_evidence": [],
            "evidence_ids": [],
            "missing_evidence": ["计算条件。"],
            "actual_clear_width_calculation_ready": True,
            "actual_clear_width_evidence_ids": [first_evidence_id],
            "required_clear_width_calculation_ready": False,
            "required_clear_width_evidence_ids": [],
            "query": "小学首层疏散门净宽度计算还需要哪些适用条件？",
            "dense_query": "What additional conditions are needed to calculate a ground-floor primary-school evacuation door clear width?",
            "target_document": DEFAULT_INITIAL_DOCUMENT,
            "reason": "继续补充同一文档中的计算条件。",
        },
        _terminal(),
    ]
    calls: list[tuple[str, str]] = []
    build_count = 0

    def factory(descriptor: DocumentDescriptor) -> FakeRetriever:
        nonlocal build_count
        build_count += 1
        return FakeRetriever(descriptor.document_id, calls)

    result = run_iterative_retrieval(
        task="收集能判断疏散门净宽检查的相关信息但不做任何判断",
        original_query="检查疏散门净宽度。",
        ifc_context=_resolved_ifc_context(),
        catalog=_catalog(tmp_path),
        client=FakeServiceClient(decisions),
        config=SearchConfig(max_hops=2),
        retriever_factory=factory,
    )

    assert result.hop == 2
    assert build_count == 1
    assert len(calls) == 2


def test_service_replaces_missing_information_after_each_valid_decision(
    tmp_path: Path,
) -> None:
    first_evidence_id = f"{DEFAULT_INITIAL_DOCUMENT}:text_000001"
    updated_missing = ["还缺少适用的规范净宽阈值。"]
    decisions = [
        {
            "action": "search",
            "evidence_ids": [first_evidence_id],
            "missing_evidence": updated_missing,
            "actual_clear_width_calculation_ready": True,
            "actual_clear_width_evidence_ids": [first_evidence_id],
            "required_clear_width_calculation_ready": False,
            "required_clear_width_evidence_ids": [],
            "query": "小学首层疏散门适用的规范净宽阈值是多少？",
            "dense_query": "What required clear-width threshold applies to a ground-floor primary-school evacuation door?",
            "target_document": DEFAULT_INITIAL_DOCUMENT,
            "reason": "实际净宽计算证据已充分，仍需检索规范阈值。",
        },
        _terminal(),
    ]
    client = FakeServiceClient(decisions)

    run_iterative_retrieval(
        task="收集能判断疏散门净宽检查的相关信息但不做任何判断",
        original_query="检查疏散门净宽度。",
        ifc_context=_ifc_context(),
        catalog=_catalog(tmp_path),
        client=client,
        config=SearchConfig(max_hops=2),
        retriever_factory=lambda descriptor: FakeRetriever(
            descriptor.document_id,
            [],
        ),
    )

    first_context = json.loads(
        client.controller_payloads[0]["content"][0]["text"]
    )["context"]
    second_context = json.loads(
        client.controller_payloads[1]["content"][0]["text"]
    )["context"]
    assert first_context["ifc_context"]["missing_information"] == [
        "clear_width_conversion_rule",
        "adjacent_spaces relationships",
    ]
    assert second_context["ifc_context"]["missing_information"] == updated_missing


def test_service_does_not_calculate_clear_width_from_retrieved_evidence(
    tmp_path: Path,
) -> None:
    decision = {
        "action": "insufficient_evidence",
        "evidence_ids": [],
        "missing_evidence": ["两组计算证据尚不充分。"],
        "actual_clear_width_calculation_ready": False,
        "actual_clear_width_evidence_ids": [],
        "required_clear_width_calculation_ready": False,
        "required_clear_width_evidence_ids": [],
        "query": None,
        "dense_query": None,
        "target_document": None,
        "reason": "已达到最大检索轮次。",
    }
    client = FakeServiceClient([decision])

    result = run_iterative_retrieval(
        task="收集能判断疏散门净宽检查的相关信息但不做任何判断",
        original_query="检查疏散门净宽度。",
        ifc_context=_ifc_context(),
        catalog=_catalog(tmp_path),
        client=client,
        config=SearchConfig(max_hops=1),
        retriever_factory=lambda descriptor: DeductionEvidenceRetriever(
            descriptor.document_id,
            [],
        ),
    )

    context = json.loads(
        client.controller_payloads[0]["content"][0]["text"]
    )["context"]
    assert context["ifc_context"]["clear_width_resolution"]["clear_width"] is None
    assert result.actual_clear_width_calculation_ready is False
