"""T4 orchestration: direct values or isolated calculations, then comparison."""

from __future__ import annotations

from pathlib import Path
import re

from pydantic import BaseModel, ConfigDict, Field

from src.ai.evacuation_door_classifier import StructuredLLMClient
from src.rule_engine import evaluate_clear_width_rule
from src.rules.calculation_context import build_t4_door_calculation_context
from src.rules.evidence_groups import (
    T4EvidenceGroup,
    T4EvidencePackage,
    build_t4_evidence_package,
)
from src.rules.sandbox_runner import (
    DEFAULT_PYTHON_EXECUTABLE,
    RuleSandboxError,
    run_validated_field_script,
)
from src.rules.script_generator import generate_field_calculation
from src.schemas.result import CheckResult
from src.schemas.rule import (
    FieldCalculationOutput,
    RuleCalculationOutput,
    ValidatedFieldScript,
)
from src.search.iterative.building_evidence_cache import BuildingEvidenceBundle
from src.search.iterative.models import IFCContext


class RuleServiceResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    rule_id: str = Field(min_length=1)
    evidence_package: T4EvidencePackage
    scripts: dict[str, ValidatedFieldScript] = Field(default_factory=dict)
    field_results: dict[str, FieldCalculationOutput] = Field(default_factory=dict)
    calculation: RuleCalculationOutput | None = None
    check_result: CheckResult
    code_hashes: dict[str, str] = Field(default_factory=dict)
    execution_errors: dict[str, str] = Field(default_factory=dict)
    resolution_modes: dict[str, str] = Field(default_factory=dict)
    field_evidence_ids: dict[str, tuple[str, ...]] = Field(default_factory=dict)


def execute_evacuation_door_rule(
    *,
    evidence_bundle: BuildingEvidenceBundle,
    ifc_context: IFCContext,
    client: StructuredLLMClient | None = None,
    python_executable: str | Path = DEFAULT_PYTHON_EXECUTABLE,
    timeout_seconds: float = 3.0,
) -> RuleServiceResult:
    """Resolve both widths, then compare them without an LLM judgment."""

    evidence_package = build_t4_evidence_package(evidence_bundle)
    calculation_context = build_t4_door_calculation_context(ifc_context)
    rule_id = _rule_id(evidence_package.building_type)
    scripts: dict[str, ValidatedFieldScript] = {}
    field_results: dict[str, FieldCalculationOutput] = {}
    execution_errors: dict[str, str] = {}
    resolution_modes: dict[str, str] = {}
    field_evidence_ids: dict[str, tuple[str, ...]] = {}

    for group in _evidence_groups(evidence_package):
        generated = generate_field_calculation(
            evidence_group=group,
            calculation_context=calculation_context,
            client=client,
        )
        field_evidence_ids[group.target_field] = generated.evidence_ids
        resolved = generated.value
        if isinstance(resolved, FieldCalculationOutput):
            field_results[group.target_field] = resolved
            resolution_modes[group.target_field] = (
                "ifc_direct"
                if group.target_field == "actual_clear_width_mm"
                else "evidence_direct"
            )
            continue
        script = resolved
        scripts[group.target_field] = script
        resolution_modes[group.target_field] = "python_script"
        try:
            field_results[group.target_field] = run_validated_field_script(
                script,
                python_executable=python_executable,
                timeout_seconds=timeout_seconds,
            )
        except RuleSandboxError as exc:
            execution_errors[group.target_field] = str(exc)

    calculation = _combine_field_results(field_results)
    combined_error = "; ".join(
        f"{key}: {value}" for key, value in execution_errors.items()
    ) or None
    check_result = evaluate_clear_width_rule(
        rule_id=rule_id,
        door_id=ifc_context.subject.door_id,
        calculation=calculation,
        execution_error=combined_error,
    )
    return RuleServiceResult(
        rule_id=rule_id,
        evidence_package=evidence_package,
        scripts=scripts,
        field_results=field_results,
        calculation=calculation,
        check_result=check_result,
        code_hashes={key: value.source_hash for key, value in scripts.items()},
        execution_errors=execution_errors,
        resolution_modes=resolution_modes,
        field_evidence_ids=field_evidence_ids,
    )


def _evidence_groups(
    package: T4EvidencePackage,
) -> tuple[T4EvidenceGroup, T4EvidenceGroup]:
    return package.actual_clear_width, package.required_clear_width


def _combine_field_results(
    results: dict[str, FieldCalculationOutput],
) -> RuleCalculationOutput | None:
    actual = results.get("actual_clear_width_mm")
    required = results.get("required_clear_width_mm")
    if actual is None or required is None:
        return None
    return RuleCalculationOutput(
        actual_clear_width_mm=actual.value_mm,
        required_clear_width_mm=required.value_mm,
    )


def _rule_id(building_type: str) -> str:
    token = re.sub(r"[^A-Za-z0-9_]+", "_", building_type).strip("_")
    return f"{token or 'building'}_evacuation_door_clear_width"
