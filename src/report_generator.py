"""Generate one evidence-grounded detailed reason from a finished T4 result."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from prompt.report_generation import DETAILED_REASON_PROMPT
from src.ai.evacuation_door_classifier import StructuredLLMClient
from src.ai.multimodal_evidence import build_multimodal_evidence_content
from src.ai.openai_compatible_client import OpenAICompatibleJSONClient
from src.rules.calculation_context import build_t4_door_calculation_context
from src.rules.service import RuleServiceResult
from src.schemas.result import CheckStatus
from src.search.iterative.models import EvidenceHistoryItem, IFCContext


class DetailedReasonGenerationError(ValueError):
    """Raised when a finished T4 result cannot produce a valid explanation."""


ChineseCheckResult = Literal["合格", "不合格"]

T5_RESULT_LABELS: dict[CheckStatus, ChineseCheckResult] = {
    CheckStatus.PASS: "合格",
    CheckStatus.FAIL: "不合格",
}


class DetailedReasonLLMResponse(BaseModel):
    """The text and citations authored by the T5 VLM."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    detailed_reason: str = Field(min_length=1)
    evidence_ids: tuple[str, ...] = Field(min_length=1)


class DetailedReasonReport(DetailedReasonLLMResponse):
    """The complete T5 output with T4's result mapped for presentation."""

    result: ChineseCheckResult


def generate_detailed_reason(
    *,
    t4_result: RuleServiceResult,
    ifc_context: IFCContext,
    client: StructuredLLMClient | None = None,
) -> DetailedReasonReport:
    """Explain, but never recalculate, one completed T4 door check."""

    calculation = t4_result.calculation
    if calculation is None:
        raise DetailedReasonGenerationError(
            "T5 requires both completed T4 field calculations"
        )
    if t4_result.execution_errors:
        raise DetailedReasonGenerationError(
            "T5 does not explain a T4 result with execution errors"
        )

    evidence_items = _selected_evidence(t4_result)
    allowed_evidence = {item.evidence_id for item in evidence_items}
    if not allowed_evidence:
        raise DetailedReasonGenerationError(
            "T5 requires at least one T4-used regulation evidence item"
        )

    displayed_result = _display_result(t4_result.check_result.result)
    context = {
        "task": t4_result.evidence_package.task,
        "door_id": ifc_context.subject.door_id,
        "current_door_context": build_t4_door_calculation_context(
            ifc_context
        ).model_dump(mode="json"),
        "calculation": {
            "actual_clear_width_mm": calculation.actual_clear_width_mm,
            "required_clear_width_mm": calculation.required_clear_width_mm,
            "difference_mm": (
                calculation.actual_clear_width_mm
                - calculation.required_clear_width_mm
            ),
            "result": displayed_result,
        },
        "calculation_details": {
            target_field: _calculation_detail(t4_result, target_field)
            for target_field in (
                "actual_clear_width_mm",
                "required_clear_width_mm",
            )
        },
        "evidence_groups": {
            "actual_clear_width_evidence_ids": list(
                t4_result.field_evidence_ids.get(
                    "actual_clear_width_mm",
                    (),
                )
            ),
            "required_clear_width_evidence_ids": list(
                t4_result.field_evidence_ids.get(
                    "required_clear_width_mm",
                    (),
                )
            ),
        },
    }
    llm_client = client or OpenAICompatibleJSONClient.from_env(
        model_env_key="model_name"
    )
    response = llm_client.complete_json_multimodal(
        system_prompt=DETAILED_REASON_PROMPT,
        content=build_multimodal_evidence_content(
            context=context,
            evidence_items=evidence_items,
        ),
    )
    try:
        llm_response = DetailedReasonLLMResponse.model_validate(response)
    except ValidationError as exc:
        raise DetailedReasonGenerationError(
            f"T5 returned an invalid detailed reason: {exc}"
        ) from exc
    unknown = set(llm_response.evidence_ids) - allowed_evidence
    if unknown:
        raise DetailedReasonGenerationError(
            "T5 cited evidence not used by T4: " + ", ".join(sorted(unknown))
        )
    return DetailedReasonReport(
        result=displayed_result,
        detailed_reason=llm_response.detailed_reason,
        evidence_ids=llm_response.evidence_ids,
    )


def _display_result(status: CheckStatus) -> ChineseCheckResult:
    try:
        return T5_RESULT_LABELS[status]
    except KeyError as exc:
        raise DetailedReasonGenerationError(
            f"T5 requires a completed PASS/FAIL result, got {status.value}"
        ) from exc


def _calculation_detail(
    result: RuleServiceResult,
    target_field: str,
) -> dict[str, object]:
    field_result = result.field_results.get(target_field)
    script = result.scripts.get(target_field)
    return {
        "resolution_mode": result.resolution_modes.get(target_field),
        "value_mm": None if field_result is None else field_result.value_mm,
        "python_source": None if script is None else script.source,
        "evidence_ids": list(result.field_evidence_ids.get(target_field, ())),
    }


def _selected_evidence(result: RuleServiceResult) -> tuple[EvidenceHistoryItem, ...]:
    selected_ids = tuple(
        dict.fromkeys(
            evidence_id
            for target_field in (
                "actual_clear_width_mm",
                "required_clear_width_mm",
            )
            for evidence_id in result.field_evidence_ids.get(target_field, ())
        )
    )
    evidence_by_id = {
        item.evidence_id: item
        for item in result.evidence_package.evidence_history
    }
    unknown = set(selected_ids) - set(evidence_by_id)
    if unknown:
        raise DetailedReasonGenerationError(
            "T4 field provenance references missing evidence: "
            + ", ".join(sorted(unknown))
        )
    return tuple(evidence_by_id[item] for item in selected_ids)
