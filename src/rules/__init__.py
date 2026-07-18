"""T4 field resolution, safe execution and deterministic comparison."""

from src.rules.calculation_context import (
    T4DoorCalculationContext,
    build_t4_door_calculation_context,
)
from src.rules.evidence_groups import (
    T4EvidenceNotReadyError,
    T4EvidencePackage,
    build_t4_evidence_package,
)
from src.rules.sandbox_runner import RuleSandboxError, run_validated_field_script
from src.rules.result_cache import (
    T4ResultCache,
    T4ResultCacheKey,
    T4ResultResolution,
    build_t4_result_cache_key,
    execute_or_reuse_evacuation_door_rule,
)
from src.rules.script_generator import (
    FieldCalculationGenerationError,
    generate_field_calculation,
)
from src.rules.script_validator import (
    FieldScriptValidationError,
    validate_field_script,
)
from src.rules.service import RuleServiceResult, execute_evacuation_door_rule

__all__ = [
    "FieldCalculationGenerationError",
    "FieldScriptValidationError",
    "RuleSandboxError",
    "RuleServiceResult",
    "T4DoorCalculationContext",
    "T4EvidenceNotReadyError",
    "T4EvidencePackage",
    "T4ResultCache",
    "T4ResultCacheKey",
    "T4ResultResolution",
    "build_t4_evidence_package",
    "build_t4_door_calculation_context",
    "build_t4_result_cache_key",
    "execute_evacuation_door_rule",
    "execute_or_reuse_evacuation_door_rule",
    "generate_field_calculation",
    "run_validated_field_script",
    "validate_field_script",
]
