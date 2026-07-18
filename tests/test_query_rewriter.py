import json
from pathlib import Path
from typing import Any

import pytest

from src.schemas.assessment import ClassifiedEvacuationDoorRecord, ClearWidthResolution
from src.search.document_catalog import DocumentCatalog
from src.search.iterative.models import IFCContext
from src.search.query_builder import build_retrieval_input
from src.search.query_rewriter import (
    DEFAULT_INITIAL_DOCUMENT,
    rewrite_initial_query,
)


EXAMPLES = Path(__file__).parents[1] / "examples"
SCHOOL_DOCUMENT = "中小学校设计规范GB 50099—2011(page1-50)"


class FakeRewriteClient:
    model_name = "fake-rewriter"

    def complete_json(
        self, *, system_prompt: str, payload: dict[str, Any]
    ) -> dict[str, Any]:
        self.system_prompt = system_prompt
        self.payload = payload
        return {
            "query": (
                "对于小学首层被识别为疏散门的双扇平开门，在IFC模型未提供"
                "明确净宽度的情况下，应从规范中确认哪些净宽度要求和适用条件？"
            ),
            "dense_query": (
                "For a double-leaf evacuation door on the ground floor of a primary school, "
                "what clear-width requirements and conditions apply when IFC clear width is unavailable?"
            ),
            "target_document": "模型不得改变目标文档",
            "reason": "需要检索适用的净宽度要求。",
        }


def _ifc_context() -> IFCContext:
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
    facts = next(item for item in input_rows if item["door_id"] == "Door 15600")
    assessment = next(
        item for item in output_rows if item["ifc_guid"] == facts["ifc_guid"]
    )
    retrieval_input = build_retrieval_input(
        ClassifiedEvacuationDoorRecord.model_validate(
            {**facts, "assessment": assessment}
        )
    )
    return IFCContext(
        subject=retrieval_input.subject,
        building_context=retrieval_input.building_context,
        door_facts=retrieval_input.door_facts,
        assessment=retrieval_input.assessment,
        clear_width_resolution=ClearWidthResolution(
            ifc_guid=retrieval_input.subject.ifc_guid,
            clear_width=None,
            method="unavailable",
        ),
        missing_information=retrieval_input.missing_information,
        data_quality_warnings=facts["data_quality_warnings"],
    )


def test_rewriter_uses_default_document_and_string_document_list() -> None:
    client = FakeRewriteClient()
    catalog = DocumentCatalog.discover()

    result = rewrite_initial_query(
        task="收集能判断疏散门净宽检查的相关信息但不做任何判断",
        original_query="检查上传IFC模型中的疏散门净宽度是否符合规范。",
        ifc_context=_ifc_context(),
        catalog=catalog,
        client=client,
    )

    assert result.target_document == DEFAULT_INITIAL_DOCUMENT
    assert result.dense_query.startswith("For a double-leaf evacuation door")
    assert client.payload["available_documents"] == catalog.available_documents()
    assert all(isinstance(item, str) for item in client.payload["available_documents"])
    assert client.payload["ifc_context"]["door_facts"]["overall_width"] == 3000.0
    assert client.payload["ifc_context"]["clear_width_resolution"]["clear_width"] is None
    assert "Do not\nask whether the IFC door passes" in client.system_prompt


def test_rewriter_honors_explicit_available_document() -> None:
    result = rewrite_initial_query(
        task="收集能判断疏散门净宽检查的相关信息但不做任何判断",
        original_query=f"请根据《{SCHOOL_DOCUMENT}》检查疏散门净宽度。",
        ifc_context=_ifc_context(),
        catalog=DocumentCatalog.discover(),
        client=FakeRewriteClient(),
    )

    assert result.target_document == SCHOOL_DOCUMENT


def test_rewriter_rejects_empty_original_query() -> None:
    with pytest.raises(ValueError, match="original_query cannot be empty"):
        rewrite_initial_query(
            task="收集能判断疏散门净宽检查的相关信息但不做任何判断",
            original_query=" ",
            ifc_context=_ifc_context(),
            catalog=DocumentCatalog.discover(),
            client=FakeRewriteClient(),
        )
