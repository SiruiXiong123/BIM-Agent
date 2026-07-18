import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from src.schemas.assessment import ClassifiedEvacuationDoorRecord, ClearWidthResolution
from src.search.iterative.models import (
    EvidenceHistoryItem,
    IFCContext,
    IterativeRetrievalResult,
    IterativeRetrievalState,
    IterativeSearchDecision,
    QueryHistoryItem,
)
from src.search.query_builder import build_retrieval_input


EXAMPLES = Path(__file__).parents[1] / "examples"
NANJING_DOCUMENT = "南京地方标准建筑工程施工图信息模型智能审查规范"


def _door_15600_record() -> ClassifiedEvacuationDoorRecord:
    facts = next(
        json.loads(line)
        for line in (EXAMPLES / "primary_school_classification_input.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()
        if line and json.loads(line)["door_id"] == "Door 15600"
    )
    assessment = next(
        json.loads(line)
        for line in (EXAMPLES / "primary_school_classification_output_v2_first10.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()
        if line and json.loads(line)["ifc_guid"] == facts["ifc_guid"]
    )
    return ClassifiedEvacuationDoorRecord.model_validate(
        {**facts, "assessment": assessment}
    )


def _ifc_context() -> IFCContext:
    retrieval_input = build_retrieval_input(_door_15600_record())
    return IFCContext(
        subject=retrieval_input.subject,
        building_context=retrieval_input.building_context,
        door_facts=retrieval_input.door_facts,
        assessment=retrieval_input.assessment,
        clear_width_resolution=ClearWidthResolution(
            ifc_guid=retrieval_input.subject.ifc_guid,
            clear_width=None,
            source=None,
            method="unavailable",
            warnings=[
                "No explicit Egress Width or Clear Width was found; "
                "OverallWidth was not used."
            ],
        ),
        missing_information=retrieval_input.missing_information,
        data_quality_warnings=_door_15600_record().data_quality_warnings,
    )


def _evidence() -> EvidenceHistoryItem:
    return EvidenceHistoryItem(
        evidence_id=f"{NANJING_DOCUMENT}:table_000020",
        document_id=NANJING_DOCUMENT,
        content_id="table_000020",
        modality="table",
        page=24,
        content="疏散门净宽度应依据相关建筑设计规范确定。",
        score=0.0322,
        retrievers=["bm25", "dense"],
        retrieved_at_hop=1,
    )


def test_door_15600_ifc_context_keeps_overall_and_clear_width_distinct() -> None:
    context = _ifc_context()
    restored = IFCContext.model_validate_json(context.model_dump_json())

    assert restored.subject.door_id == "Door 15600"
    assert restored.building_context.building_type == "primary_school"
    assert restored.door_facts.overall_width == 3000.0
    assert restored.clear_width_resolution.clear_width is None
    assert restored.clear_width_resolution.method == "unavailable"


def test_ifc_context_rejects_mismatched_width_identity() -> None:
    data = _ifc_context().model_dump(mode="json")
    data["clear_width_resolution"]["ifc_guid"] = "another-guid"

    with pytest.raises(ValidationError, match="must match subject.ifc_guid"):
        IFCContext.model_validate(data)


def test_search_decision_requires_query_and_target_document() -> None:
    with pytest.raises(ValidationError, match="search requires a non-empty query"):
        IterativeSearchDecision(
            action="search",
            reason="Evidence is incomplete.",
            actual_clear_width_calculation_ready=False,
            required_clear_width_calculation_ready=False,
            query=None,
            target_document=NANJING_DOCUMENT,
        )


def test_terminal_decision_rejects_search_fields() -> None:
    with pytest.raises(ValidationError, match="require null query"):
        IterativeSearchDecision(
            action="finish",
            reason="Evidence is sufficient.",
            actual_clear_width_calculation_ready=True,
            required_clear_width_calculation_ready=True,
            required_clear_width_evidence_ids=["document:evidence"],
            query="This must not be present.",
            target_document=NANJING_DOCUMENT,
        )


def test_ready_judgment_requires_supporting_evidence_ids() -> None:
    with pytest.raises(ValidationError, match="actual clear-width readiness"):
        IterativeSearchDecision(
            action="search",
            reason="Actual calculation was claimed ready without evidence.",
            actual_clear_width_calculation_ready=True,
            actual_clear_width_evidence_ids=[],
            required_clear_width_calculation_ready=False,
            query="还需要检索哪些规范阈值证据？",
            dense_query="What threshold evidence is still required?",
            target_document=NANJING_DOCUMENT,
        )


def test_state_validates_query_and_evidence_history() -> None:
    evidence = _evidence()
    state = IterativeRetrievalState(
        task="收集能判断疏散门净宽检查的相关信息但不做任何判断",
        original_query="检查上传IFC模型中的疏散门净宽度是否符合规范。",
        ifc_context=_ifc_context(),
        available_documents=[NANJING_DOCUMENT],
        evidence_history=[evidence],
        query_history=[
            QueryHistoryItem(
                hop=1,
                    query="疏散门净宽度检查需要哪些模型数据和判定规则？",
                    dense_query="What model data and rules are needed to check evacuation-door clear width?",
                target_document=NANJING_DOCUMENT,
                result_count=1,
                evidence_ids=[evidence.evidence_id],
            )
        ],
        hop=1,
        max_hops=3,
    )

    assert IterativeRetrievalState.model_validate_json(
        state.model_dump_json()
    ) == state


def test_state_rejects_unknown_evidence_reference() -> None:
    with pytest.raises(ValidationError, match="unknown evidence IDs"):
        IterativeRetrievalState(
            task="收集能判断疏散门净宽检查的相关信息但不做任何判断",
            original_query="检查疏散门净宽度。",
            ifc_context=_ifc_context(),
            available_documents=[NANJING_DOCUMENT],
            query_history=[
                QueryHistoryItem(
                    hop=1,
                        query="疏散门净宽度要求是什么？",
                        dense_query="What are the evacuation-door clear-width requirements?",
                    target_document=NANJING_DOCUMENT,
                    result_count=1,
                    evidence_ids=["missing:evidence"],
                )
            ],
            hop=1,
            max_hops=3,
        )


def test_terminal_result_only_references_known_evidence() -> None:
    evidence = _evidence()
    query = QueryHistoryItem(
        hop=1,
        query="疏散门净宽度要求是什么？",
        dense_query="What are the evacuation-door clear-width requirements?",
        target_document=NANJING_DOCUMENT,
        result_count=1,
        evidence_ids=[evidence.evidence_id],
    )
    result = IterativeRetrievalResult(
        action="finish",
            task="收集能判断疏散门净宽检查的相关信息但不做任何判断",
        original_query="检查疏散门净宽度。",
        evidence_ids=[evidence.evidence_id],
        reason="Evidence is sufficient.",
        actual_clear_width_calculation_ready=True,
        actual_clear_width_evidence_ids=[evidence.evidence_id],
        required_clear_width_calculation_ready=True,
        required_clear_width_evidence_ids=[evidence.evidence_id],
        hop=1,
        query_history=[query],
        evidence_history=[evidence],
    )

    assert result.action == "finish"


def test_evidence_serializes_iter_and_reads_legacy_hop_name() -> None:
    evidence = _evidence()
    serialized = evidence.model_dump(mode="json")

    assert serialized["iter"] == 1
    assert "retrieved_at_hop" not in serialized
    assert evidence.retrieved_at_hop == 1
