"""Run Door 15600 through iterative retrieval and emit a debug JSON report."""

from __future__ import annotations

import argparse
import json
import time
import traceback
from datetime import datetime
from pathlib import Path
from typing import Any

from src.ai.openai_compatible_client import OpenAICompatibleJSONClient
from src.schemas.assessment import ClassifiedEvacuationDoorRecord, ClearWidthResolution
from src.search.config import SearchConfig
from src.search.document_catalog import DocumentCatalog, DocumentDescriptor
from src.search.iterative.models import IFCContext
from src.search.iterative.service import run_iterative_retrieval
from src.search.models import PreSearchUserInputs, SearchHit
from src.search.models import DEFAULT_RETRIEVAL_TASK
from src.search.query_builder import build_retrieval_input
from src.search.retrievers.hybrid import HybridRetriever


PROJECT_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_OUTPUT = PROJECT_ROOT / "artifacts" / "debug" / "door_15600_iterative_retrieval.json"
DEFAULT_QUERY = "检查上传IFC模型中 Door 15600 的疏散门净宽度是否符合适用规范。"


class TracingJSONClient:
    """Record sanitized LLM requests and responses around the real client."""

    def __init__(self, delegate: OpenAICompatibleJSONClient) -> None:
        self.delegate = delegate
        self.calls: list[dict[str, Any]] = []

    @property
    def model_name(self) -> str:
        return self.delegate.model_name

    def complete_json(
        self, *, system_prompt: str, payload: dict[str, Any]
    ) -> dict[str, Any]:
        call_type = "initial_query_rewrite" if "target_document" in payload else "controller"
        started = time.perf_counter()
        trace: dict[str, Any] = {
            "call_number": len(self.calls) + 1,
            "call_type": call_type,
            "model_name": self.model_name,
            "system_prompt": system_prompt,
            "payload": payload,
        }
        self.calls.append(trace)
        try:
            response = self.delegate.complete_json(
                system_prompt=system_prompt,
                payload=payload,
            )
            trace["response"] = response
            return response
        except Exception as exc:
            trace["error"] = _error_data(exc)
            raise
        finally:
            trace["duration_ms"] = round((time.perf_counter() - started) * 1000, 2)

    def complete_json_multimodal(
        self,
        *,
        system_prompt: str,
        content: list[dict[str, Any]],
    ) -> dict[str, Any]:
        started = time.perf_counter()
        trace: dict[str, Any] = {
            "call_number": len(self.calls) + 1,
            "call_type": "controller",
            "model_name": self.model_name,
            "system_prompt": system_prompt,
            "content": _redact_image_data(content),
        }
        self.calls.append(trace)
        try:
            response = self.delegate.complete_json_multimodal(
                system_prompt=system_prompt,
                content=content,
            )
            trace["response"] = response
            return response
        except Exception as exc:
            trace["error"] = _error_data(exc)
            raise
        finally:
            trace["duration_ms"] = round((time.perf_counter() - started) * 1000, 2)


def _redact_image_data(content: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Keep multimodal debug traces readable without duplicating image bytes."""

    redacted: list[dict[str, Any]] = []
    for part in content:
        if part.get("type") != "image_url":
            redacted.append(part)
            continue
        image_url = part.get("image_url")
        detail = image_url.get("detail") if isinstance(image_url, dict) else None
        redacted.append({
            "type": "image_url",
            "image_url": {"url": "<base64 image omitted>", "detail": detail},
        })
    return redacted


class TracingRetriever:
    """Record the raw hybrid hits before history conversion and deduplication."""

    def __init__(
        self,
        delegate: HybridRetriever,
        document_id: str,
        traces: list[dict[str, Any]],
    ) -> None:
        self.delegate = delegate
        self.document_id = document_id
        self.traces = traces

    def search(
        self,
        query: str,
        *,
        dense_query: str | None = None,
        top_k: int | None = None,
    ) -> list[SearchHit]:
        started = time.perf_counter()
        trace: dict[str, Any] = {
            "retrieval_number": len(self.traces) + 1,
            "document_id": self.document_id,
            "query": query,
            "dense_query": dense_query,
            "top_k": top_k,
        }
        self.traces.append(trace)
        try:
            hits = self.delegate.search(
                query,
                dense_query=dense_query,
                top_k=top_k,
            )
            trace["result_count"] = len(hits)
            trace["hits"] = [hit.model_dump(mode="json") for hit in hits]
            return hits
        except Exception as exc:
            trace["error"] = _error_data(exc)
            raise
        finally:
            trace["duration_ms"] = round((time.perf_counter() - started) * 1000, 2)


def run_debug(
    *,
    output_path: Path,
    original_query: str = DEFAULT_QUERY,
    enable_dense: bool = True,
    user_inputs: PreSearchUserInputs | None = None,
    overall_width_mm: float | None = None,
) -> dict[str, Any]:
    """Execute the real pipeline and always persist a success or failure report."""

    started_at = datetime.now().astimezone()
    started = time.perf_counter()
    config = SearchConfig()
    catalog = DocumentCatalog.discover()
    ifc_context = _load_door_15600_context(user_inputs)
    if overall_width_mm is not None:
        ifc_context = _with_overall_width(ifc_context, overall_width_mm)
    llm_client = TracingJSONClient(
        OpenAICompatibleJSONClient.from_env(model_env_key="model_name")
    )
    retrieval_traces: list[dict[str, Any]] = []

    def retriever_factory(descriptor: DocumentDescriptor) -> TracingRetriever:
        retriever = HybridRetriever(
            descriptor.index_dir,
            config=config,
            enable_dense=enable_dense,
        )
        return TracingRetriever(retriever, descriptor.document_id, retrieval_traces)

    report: dict[str, Any] = {
        "debug_schema_version": "door-15600-t3-evidence-sufficiency-v2",
        "started_at": started_at.isoformat(),
        "input": {
            "task": DEFAULT_RETRIEVAL_TASK,
            "original_query": original_query,
            "ifc_context": ifc_context.model_dump(mode="json"),
            "available_documents": catalog.available_documents(),
            "config": config.model_dump(mode="json"),
            "dense_enabled": enable_dense,
            "debug_overrides": {
                "overall_width_mm": overall_width_mm,
            },
        },
        "llm_calls": llm_client.calls,
        "retrieval_calls": retrieval_traces,
    }
    try:
        result = run_iterative_retrieval(
            task=DEFAULT_RETRIEVAL_TASK,
            original_query=original_query,
            ifc_context=ifc_context,
            catalog=catalog,
            client=llm_client,
            config=config,
            enable_dense=enable_dense,
            retriever_factory=retriever_factory,
        )
        report["status"] = "success"
        report["result"] = result.model_dump(mode="json")
        report["t3_summary"] = {
            "action": result.action,
            "actual_clear_width_calculation_ready": (
                result.actual_clear_width_calculation_ready
            ),
            "required_clear_width_calculation_ready": (
                result.required_clear_width_calculation_ready
            ),
            "actual_clear_width_evidence_ids": (
                result.actual_clear_width_evidence_ids
            ),
            "required_clear_width_evidence_ids": (
                result.required_clear_width_evidence_ids
            ),
            "evidence_count": len(result.evidence_history),
            "query_count": len(result.query_history),
        }
    except Exception as exc:
        report["status"] = "error"
        report["error"] = {
            **_error_data(exc),
            "traceback": traceback.format_exc(),
        }
    finally:
        report["finished_at"] = datetime.now().astimezone().isoformat()
        report["duration_ms"] = round((time.perf_counter() - started) * 1000, 2)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(
            json.dumps(report, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    return report


def _load_door_15600_context(
    user_inputs: PreSearchUserInputs | None = None,
) -> IFCContext:
    input_path = PROJECT_ROOT / "examples" / "primary_school_classification_input.jsonl"
    output_path = (
        PROJECT_ROOT / "examples" / "primary_school_classification_output_v3_first10.jsonl"
    )
    facts = _find_jsonl_record(input_path, "door_id", "Door 15600")
    assessment = _find_jsonl_record(
        output_path,
        "ifc_guid",
        facts["ifc_guid"],
    )
    record = ClassifiedEvacuationDoorRecord.model_validate(
        {**facts, "assessment": assessment}
    )
    retrieval_input = build_retrieval_input(record, user_inputs)
    return IFCContext(
        subject=retrieval_input.subject,
        building_context=retrieval_input.building_context,
        door_facts=retrieval_input.door_facts,
        assessment=retrieval_input.assessment,
        clear_width_resolution=ClearWidthResolution(
            ifc_guid=record.ifc_guid,
            clear_width=None,
            source=None,
            method="unavailable",
            warnings=[
                "No explicit Egress Width or Clear Width was found; "
                "OverallWidth was not used as clear width."
            ],
        ),
        missing_information=retrieval_input.missing_information,
        data_quality_warnings=record.data_quality_warnings,
    )


def _find_jsonl_record(path: Path, key: str, value: str) -> dict[str, Any]:
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        record = json.loads(line)
        if record.get(key) == value:
            return record
    raise ValueError(f"No record with {key}={value!r} in {path}")


def _with_overall_width(
    ifc_context: IFCContext,
    overall_width_mm: float,
) -> IFCContext:
    """Return a validated debug-only context without changing source IFC data."""

    if overall_width_mm <= 0:
        raise ValueError("overall_width_mm must be greater than zero")
    data = ifc_context.model_dump(mode="json")
    data["door_facts"]["overall_width"] = overall_width_mm
    return IFCContext.model_validate(data)


def _error_data(exc: Exception) -> dict[str, str]:
    return {"type": type(exc).__name__, "message": str(exc)}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--query", default=DEFAULT_QUERY)
    parser.add_argument(
        "--bm25-only",
        action="store_true",
        help="Disable dense retrieval for offline diagnosis.",
    )
    parser.add_argument("--occupant-load", type=int)
    parser.add_argument(
        "--overall-width-mm",
        type=float,
        help="Debug-only OverallWidth override; the IFC fixture is not modified.",
    )
    parser.add_argument(
        "--fire-resistance-grade",
        choices=("一级", "二级", "三级", "四级"),
    )
    args = parser.parse_args()
    report = run_debug(
        output_path=args.output.resolve(),
        original_query=args.query,
        enable_dense=not args.bm25_only,
        user_inputs=PreSearchUserInputs(
            occupant_load=args.occupant_load,
            fire_resistance_grade=args.fire_resistance_grade,
        ),
        overall_width_mm=args.overall_width_mm,
    )
    print(json.dumps({
        "status": report["status"],
        "output": str(args.output.resolve()),
        "duration_ms": report["duration_ms"],
        "llm_call_count": len(report["llm_calls"]),
        "retrieval_call_count": len(report["retrieval_calls"]),
        "actual_clear_width_calculation_ready": (
            report.get("t3_summary", {}).get(
                "actual_clear_width_calculation_ready"
            )
        ),
        "required_clear_width_calculation_ready": (
            report.get("t3_summary", {}).get(
                "required_clear_width_calculation_ready"
            )
        ),
        "evidence_count": report.get("t3_summary", {}).get("evidence_count"),
        "error": report.get("error"),
    }, ensure_ascii=False, indent=2))
    return 0 if report["status"] == "success" else 1


if __name__ == "__main__":
    raise SystemExit(main())
