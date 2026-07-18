"""Deterministic comparison of resolved clear-width fields."""

from __future__ import annotations

from src.schemas.result import CheckResult, CheckStatus
from src.schemas.rule import RuleCalculationOutput


def evaluate_clear_width_rule(
    *,
    rule_id: str,
    door_id: str,
    calculation: RuleCalculationOutput | None,
    execution_error: str | None = None,
) -> CheckResult:
    """Return PASS/FAIL/UNKNOWN without an LLM."""

    if execution_error:
        return CheckResult(
            element_id=door_id,
            rule_id=rule_id,
            actual_value=(
                calculation.actual_clear_width_mm if calculation else None
            ),
            required_value=(
                calculation.required_clear_width_mm if calculation else None
            ),
            result=CheckStatus.UNKNOWN,
            message=f"Rule calculation failed: {execution_error}",
        )
    if calculation is None:
        return CheckResult(
            element_id=door_id,
            rule_id=rule_id,
            actual_value=None,
            required_value=None,
            result=CheckStatus.UNKNOWN,
            message="Rule calculation produced no result.",
        )
    actual = calculation.actual_clear_width_mm
    required = calculation.required_clear_width_mm
    status = CheckStatus.PASS if actual >= required else CheckStatus.FAIL
    operator = ">=" if status is CheckStatus.PASS else "<"
    return CheckResult(
        element_id=door_id,
        rule_id=rule_id,
        actual_value=actual,
        required_value=required,
        result=status,
        message=(
            f"actual_clear_width_mm={actual:g} {operator} "
            f"required_clear_width_mm={required:g}"
        ),
    )
