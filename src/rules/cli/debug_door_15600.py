"""Run the refactored T4 pipeline from a finished Door 15600 T3 report."""

from __future__ import annotations

import argparse
import json
import time
import traceback
from datetime import datetime
from pathlib import Path
from typing import Any

from src.ai.openai_compatible_client import OpenAICompatibleJSONClient
from src.rules.service import execute_evacuation_door_rule
from src.search.cli.debug_door_15600 import _error_data, _redact_image_data
from src.search.document_catalog import DocumentCatalog
from src.search.iterative.building_evidence_cache import (
    BuildingEvidenceBundle,
    BuildingEvidenceCacheKey,
)
from src.search.iterative.models import IFCContext, IterativeRetrievalResult


PROJECT_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_EVIDENCE_REPORT = (
    PROJECT_ROOT
    / "artifacts"
    / "debug"
    / "door_15600_t3_visual_content_summary.json"
)
DEFAULT_OUTPUT = (
    PROJECT_ROOT
    / "artifacts"
    / "debug"
    / "door_15600_t4_refactored.json"
)


class TracingJSONClient:
    """Capture direct multimodal script-generation calls without image bytes."""

    def __init__(self, delegate: OpenAICompatibleJSONClient) -> None:
        self.delegate = delegate
        self.calls: list[dict[str, Any]] = []

    @property
    def model_name(self) -> str:
        return self.delegate.model_name

    def complete_json(
        self,
        *,
        system_prompt: str,
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        return self._trace(
            call_type="field_script_generation",
            system_prompt=system_prompt,
            request_key="payload",
            request_value=payload,
            invoke=lambda: self.delegate.complete_json(
                system_prompt=system_prompt,
                payload=payload,
            ),
        )

    def complete_json_multimodal(
        self,
        *,
        system_prompt: str,
        content: list[dict[str, Any]],
    ) -> dict[str, Any]:
        return self._trace(
            call_type="field_calculation_generation",
            system_prompt=system_prompt,
            request_key="content",
            request_value=_redact_image_data(content),
            invoke=lambda: self.delegate.complete_json_multimodal(
                system_prompt=system_prompt,
                content=content,
            ),
        )

    def _trace(
        self,
        *,
        call_type: str,
        system_prompt: str,
        request_key: str,
        request_value: Any,
        invoke: Any,
    ) -> dict[str, Any]:
        started = time.perf_counter()
        trace: dict[str, Any] = {
            "call_number": len(self.calls) + 1,
            "call_type": call_type,
            "model_name": self.model_name,
            "system_prompt": system_prompt,
            request_key: request_value,
        }
        self.calls.append(trace)
        try:
            response = invoke()
            trace["response"] = response
            return response
        except Exception as exc:
            trace["error"] = _error_data(exc)
            raise
        finally:
            trace["duration_ms"] = round(
                (time.perf_counter() - started) * 1000,
                2,
            )


def run_debug(
    *,
    evidence_report: Path,
    output_path: Path,
) -> dict[str, Any]:
    started_at = datetime.now().astimezone()
    started = time.perf_counter()
    bundle, ifc_context = load_t3_report(evidence_report)
    tracing_client = TracingJSONClient(
        OpenAICompatibleJSONClient.from_env(model_env_key="model_name")
    )
    report: dict[str, Any] = {
        "debug_schema_version": "door-15600-t4-direct-script-v1",
        "started_at": started_at.isoformat(),
        "input": {
            "evidence_report": str(evidence_report.resolve()),
            "ifc_context": ifc_context.model_dump(mode="json"),
            "evidence_bundle": bundle.model_dump(mode="json"),
        },
        "llm_calls": tracing_client.calls,
    }
    try:
        result = execute_evacuation_door_rule(
            evidence_bundle=bundle,
            ifc_context=ifc_context,
            client=tracing_client,
        )
        report["t4_result"] = result.model_dump(mode="json")
        report["status"] = "success"
    except Exception as exc:
        report["status"] = "error"
        report["error"] = {
            **_error_data(exc),
            "traceback": traceback.format_exc(),
        }
    finally:
        report["finished_at"] = datetime.now().astimezone().isoformat()
        report["duration_ms"] = round(
            (time.perf_counter() - started) * 1000,
            2,
        )
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(
            json.dumps(report, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    return report


def load_t3_report(
    report_path: Path,
) -> tuple[BuildingEvidenceBundle, IFCContext]:
    data = json.loads(report_path.read_text(encoding="utf-8"))
    input_data = data.get("input")
    result_data = data.get("result")
    if not isinstance(input_data, dict) or not isinstance(result_data, dict):
        raise ValueError("T3 report must contain input and result objects")
    context_data = input_data.get("ifc_context")
    if not isinstance(context_data, dict):
        raise ValueError("T3 report has no IFC context")
    ifc_context = IFCContext.model_validate(context_data)
    compatible_result = dict(result_data)
    compatible_result.pop("found_evidence", None)
    result = IterativeRetrievalResult.model_validate(compatible_result)
    if result.action != "finish":
        raise ValueError("T4 accepts only a finished T3 report")

    documents = input_data.get("available_documents")
    if not isinstance(documents, list) or not documents:
        documents = DocumentCatalog.discover().available_documents()
    bundle = BuildingEvidenceBundle(
        key=BuildingEvidenceCacheKey(
            project_id=str(
                input_data.get("project_id") or "primary-school-real-ifc"
            ),
            building_type=(
                ifc_context.building_context.building_type or "unknown"
            ),
            task=result.task,
            available_documents=tuple(sorted(str(item) for item in documents)),
        ),
        source_ifc_guid=ifc_context.subject.ifc_guid,
        source_door_id=ifc_context.subject.door_id,
        evidence_history=tuple(result.evidence_history),
        query_history=tuple(result.query_history),
        actual_clear_width_calculation_ready=(
            result.actual_clear_width_calculation_ready
        ),
        actual_clear_width_evidence_ids=tuple(
            result.actual_clear_width_evidence_ids
        ),
        required_clear_width_calculation_ready=(
            result.required_clear_width_calculation_ready
        ),
        required_clear_width_evidence_ids=tuple(
            result.required_clear_width_evidence_ids
        ),
    )
    return bundle, ifc_context


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--evidence-report",
        type=Path,
        default=DEFAULT_EVIDENCE_REPORT,
    )
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    report = run_debug(
        evidence_report=args.evidence_report.resolve(),
        output_path=args.output.resolve(),
    )
    result = report.get("t4_result", {})
    check = result.get("check_result", {})
    print(json.dumps({
        "status": report["status"],
        "output": str(args.output.resolve()),
        "duration_ms": report["duration_ms"],
        "llm_call_count": len(report["llm_calls"]),
        "check_status": check.get("result"),
        "actual_clear_width_mm": check.get("actual_value"),
        "required_clear_width_mm": check.get("required_value"),
        "error": report.get("error"),
    }, ensure_ascii=False, indent=2))
    return 0 if report["status"] == "success" else 1


if __name__ == "__main__":
    raise SystemExit(main())
