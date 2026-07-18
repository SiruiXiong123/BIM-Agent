"""Generate one current-door calculation directly from query and evidence."""

from __future__ import annotations

from dataclasses import dataclass

from pydantic import ValidationError

from prompt.field_script_generation import FIELD_CALCULATION_PROMPT
from src.ai.evacuation_door_classifier import StructuredLLMClient
from src.ai.multimodal_evidence import build_multimodal_evidence_content
from src.ai.openai_compatible_client import OpenAICompatibleJSONClient
from src.rules.calculation_context import T4DoorCalculationContext
from src.rules.evidence_groups import T4EvidenceGroup
from src.rules.script_validator import (
    FieldScriptValidationError,
    validate_field_script,
)
from src.schemas.rule import (
    FieldCalculationOutput,
    GeneratedFieldCalculation,
    GeneratedFieldScript,
    ValidatedFieldScript,
)


class FieldCalculationGenerationError(ValueError):
    """Raised when one evidence group cannot produce a safe calculation."""


MAX_SCRIPT_ATTEMPTS = 3


FieldGenerationValue = FieldCalculationOutput | ValidatedFieldScript


@dataclass(frozen=True)
class FieldGenerationResult:
    """One validated T4 generation result with its exact evidence provenance."""

    value: FieldGenerationValue
    evidence_ids: tuple[str, ...]


def generate_field_calculation(
    *,
    evidence_group: T4EvidenceGroup,
    calculation_context: T4DoorCalculationContext,
    client: StructuredLLMClient | None = None,
) -> FieldGenerationResult:
    """Generate a direct value or one safe current-door script."""

    llm_client = client or OpenAICompatibleJSONClient.from_env(
        model_env_key="model_name"
    )
    base_context: dict[str, object] = {
        "initial_query": evidence_group.initial_query.query,
        "target_field": evidence_group.target_field,
        "current_door_context": calculation_context.for_target_field(
            evidence_group.target_field
        ),
        "assigned_evidence_ids": list(evidence_group.evidence_ids),
    }
    repair_context: dict[str, object] | None = None
    last_error: Exception | None = None
    for attempt in range(1, MAX_SCRIPT_ATTEMPTS + 1):
        context = dict(base_context)
        if repair_context is not None:
            context["repair_context"] = repair_context
        content = build_multimodal_evidence_content(
            context=context,
            evidence_items=evidence_group.evidence_history,
        )
        response = llm_client.complete_json_multimodal(
            system_prompt=FIELD_CALCULATION_PROMPT,
            content=content,
        )
        try:
            generated = GeneratedFieldCalculation.model_validate(response)
            evidence_ids = _validate_generated_evidence(
                generated,
                target_field=evidence_group.target_field,
                allowed_evidence=set(evidence_group.evidence_ids),
            )
            if generated.resolution == "direct_value":
                assert generated.value_mm is not None
                return FieldGenerationResult(
                    value=FieldCalculationOutput(
                        target_field=generated.target_field,
                        value_mm=generated.value_mm,
                    ),
                    evidence_ids=evidence_ids,
                )
            assert generated.source is not None
            script = GeneratedFieldScript(
                target_field=generated.target_field,
                source=generated.source,
                evidence_ids=list(evidence_ids),
            )
            return FieldGenerationResult(
                value=validate_field_script(
                    script,
                    target_field=evidence_group.target_field,
                    allowed_evidence=set(evidence_group.evidence_ids),
                ),
                evidence_ids=evidence_ids,
            )
        except (ValidationError, FieldScriptValidationError) as exc:
            last_error = exc
            if attempt == MAX_SCRIPT_ATTEMPTS:
                break
            repair_context = {
                "attempt": attempt + 1,
                "previous_invalid_response": response,
                "validation_errors": [str(exc)],
                "instruction": (
                    "Return the complete corrected direct-value or no-argument "
                    "script response without changing the initial query or "
                    "assigned evidence."
                ),
            }
    assert last_error is not None
    raise FieldCalculationGenerationError(
        f"{evidence_group.target_field} calculation generation failed after "
        f"{MAX_SCRIPT_ATTEMPTS} attempts: {last_error}"
    ) from last_error


def _validate_generated_evidence(
    generated: GeneratedFieldCalculation,
    *,
    target_field: str,
    allowed_evidence: set[str],
) -> tuple[str, ...]:
    if generated.target_field != target_field:
        raise FieldScriptValidationError(
            "generated target_field does not match group"
        )
    evidence_ids = tuple(dict.fromkeys(generated.evidence_ids))
    if generated.resolution == "python_script" and not evidence_ids:
        raise FieldScriptValidationError(
            "python_script must cite assigned evidence"
        )
    if target_field == "required_clear_width_mm" and not evidence_ids:
        raise FieldScriptValidationError(
            "required_clear_width_mm must cite assigned regulation evidence"
        )
    unknown = set(evidence_ids) - allowed_evidence
    if unknown:
        raise FieldScriptValidationError(
            "generated result cites evidence outside its T3 group: "
            + ", ".join(sorted(unknown))
        )
    return evidence_ids
