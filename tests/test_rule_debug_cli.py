import json
from pathlib import Path
from typing import Any

from src.rules.cli.debug_door_15600 import TracingJSONClient, load_t3_report
from src.search.cli.debug_door_15600 import _with_overall_width
from src.search.models import DEFAULT_RETRIEVAL_TASK
from tests.test_iterative_models import NANJING_DOCUMENT, _ifc_context


class _FakeDelegate:
    model_name = "fake-vlm"

    def complete_json_multimodal(self, **_: Any) -> dict[str, Any]:
        return {"plan": True}

    def complete_json(self, **_: Any) -> dict[str, Any]:
        return {"script": True}


def test_load_t3_report_preserves_explicit_evidence_groups(tmp_path: Path) -> None:
    actual_id = f"{NANJING_DOCUMENT}:text_actual"
    required_id = f"{NANJING_DOCUMENT}:text_required"
    context = _ifc_context().model_dump(mode="json")
    evidence = []
    for content_id, evidence_id in (
        ("text_actual", actual_id),
        ("text_required", required_id),
    ):
        evidence.append({
            "evidence_id": evidence_id,
            "document_id": NANJING_DOCUMENT,
            "content_id": content_id,
            "modality": "text",
            "page": 1,
            "title": "Evidence",
            "content": "Evidence content",
            "summary": "",
            "asset_path": None,
            "score": 1.0,
            "retrievers": ["bm25"],
            "cross_document_references": [],
            "iter": 1,
        })
    report = {
        "input": {
            "project_id": "primary-school-real-ifc",
            "ifc_context": context,
            "available_documents": [NANJING_DOCUMENT],
        },
        "result": {
            "action": "finish",
            "task": DEFAULT_RETRIEVAL_TASK,
            "original_query": "collect evidence",
            "evidence_ids": [actual_id, required_id],
            "missing_evidence": [],
            "extra_info": [],
            "actual_clear_width_calculation_ready": True,
            "actual_clear_width_evidence_ids": [actual_id],
            "required_clear_width_calculation_ready": True,
            "required_clear_width_evidence_ids": [required_id],
            "reason": "Both groups are ready.",
            "hop": 1,
            "query_history": [{
                "hop": 1,
                "query": "query",
                "dense_query": "dense query",
                "target_document": NANJING_DOCUMENT,
                "result_count": 2,
                "evidence_ids": [actual_id, required_id],
            }],
            "evidence_history": evidence,
        },
    }
    path = tmp_path / "t3.json"
    path.write_text(json.dumps(report, ensure_ascii=False), encoding="utf-8")

    bundle, loaded_context = load_t3_report(path)

    assert loaded_context.subject.door_id == context["subject"]["door_id"]
    assert bundle.actual_clear_width_evidence_ids == (actual_id,)
    assert bundle.required_clear_width_evidence_ids == (required_id,)


def test_tracing_labels_direct_multimodal_script_generation() -> None:
    client = TracingJSONClient(_FakeDelegate())  # type: ignore[arg-type]
    client.complete_json_multimodal(system_prompt="script", content=[])

    assert [item["call_type"] for item in client.calls] == [
        "field_calculation_generation",
    ]


def test_debug_width_override_does_not_mutate_original_context() -> None:
    original = _ifc_context()

    overridden = _with_overall_width(original, 700.0)

    assert original.door_facts.overall_width == 3000.0
    assert overridden.door_facts.overall_width == 700.0
