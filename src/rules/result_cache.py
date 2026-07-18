"""Reuse completed T4 calculations for doors with identical calculation inputs."""

from __future__ import annotations

from hashlib import sha256
import json
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from src.ai.evacuation_door_classifier import StructuredLLMClient
from src.rule_engine import evaluate_clear_width_rule
from src.rules.calculation_context import build_t4_door_calculation_context
from src.rules.evidence_groups import (
    T4EvidencePackage,
    build_t4_evidence_package,
)
from src.rules.sandbox_runner import DEFAULT_PYTHON_EXECUTABLE
from src.rules.service import RuleServiceResult, execute_evacuation_door_rule
from src.schemas.bim import FireResistanceGrade, InputValueSource
from src.schemas.result import CheckStatus
from src.search.iterative.building_evidence_cache import BuildingEvidenceBundle
from src.search.iterative.models import IFCContext


class T4ResultCacheKey(BaseModel):
    """Stable signature of all reusable T4 inputs except door identity.

    ``ifc_extra_info`` is deliberately excluded from this key by product
    decision. ``door_id`` is excluded so another door can reuse the same
    calculation result.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    project_id: str = Field(min_length=1)
    building_type: str = Field(min_length=1)
    task: str = Field(min_length=1)
    t3_evidence_fingerprint: str = Field(min_length=64, max_length=64)
    overall_width_mm: float = Field(ge=0)
    explicit_clear_width_mm: float | None = Field(default=None, ge=0)
    explicit_clear_width_source: str | None = None
    is_fire_door: bool
    storey_name: str | None = None
    storey_band: str
    fire_resistance_grade: FireResistanceGrade
    fire_resistance_grade_source: InputValueSource
    occupant_load: int = Field(gt=0)
    occupant_load_source: InputValueSource


class T4ResultResolution(BaseModel):
    """Uniform T4 outcome for a fresh execution or a result-cache hit."""

    model_config = ConfigDict(extra="forbid")

    status: Literal["cache_hit", "executed_and_cached", "executed_not_cached"]
    requested_door_id: str = Field(min_length=1)
    llm_skipped: bool
    sandbox_skipped: bool
    cache_key: T4ResultCacheKey
    result: RuleServiceResult


class T4ResultCache:
    """In-memory T4 cache intended for one IFC upload or batch."""

    def __init__(self) -> None:
        self._results: dict[T4ResultCacheKey, RuleServiceResult] = {}

    def get(self, key: T4ResultCacheKey) -> RuleServiceResult | None:
        result = self._results.get(key)
        return None if result is None else result.model_copy(deep=True)

    def put(self, key: T4ResultCacheKey, result: RuleServiceResult) -> bool:
        """Cache only complete PASS/FAIL results; return whether it was stored."""

        if not _is_cacheable(result):
            return False
        self._results[key] = result.model_copy(deep=True)
        return True

    def clear(self) -> None:
        self._results.clear()

    def __len__(self) -> int:
        return len(self._results)


def build_t4_result_cache_key(
    *,
    evidence_bundle: BuildingEvidenceBundle,
    ifc_context: IFCContext,
) -> T4ResultCacheKey:
    """Build the exact reusable T4 signature, excluding door ID and extra info."""

    evidence_package = build_t4_evidence_package(evidence_bundle)
    calculation_context = build_t4_door_calculation_context(ifc_context)
    return T4ResultCacheKey(
        project_id=evidence_package.project_id,
        building_type=(
            calculation_context.building_type or evidence_package.building_type
        ),
        task=evidence_package.task,
        t3_evidence_fingerprint=_evidence_fingerprint(evidence_package),
        overall_width_mm=calculation_context.overall_width_mm,
        explicit_clear_width_mm=calculation_context.explicit_clear_width_mm,
        explicit_clear_width_source=(
            calculation_context.explicit_clear_width_source
        ),
        is_fire_door=calculation_context.is_fire_door,
        storey_name=calculation_context.storey_name,
        storey_band=calculation_context.storey_band,
        fire_resistance_grade=calculation_context.fire_resistance_grade,
        fire_resistance_grade_source=(
            calculation_context.fire_resistance_grade_source
        ),
        occupant_load=calculation_context.occupant_load,
        occupant_load_source=calculation_context.occupant_load_source,
    )


def execute_or_reuse_evacuation_door_rule(
    *,
    evidence_bundle: BuildingEvidenceBundle,
    ifc_context: IFCContext,
    cache: T4ResultCache,
    client: StructuredLLMClient | None = None,
    python_executable: str | Path = DEFAULT_PYTHON_EXECUTABLE,
    timeout_seconds: float = 3.0,
) -> T4ResultResolution:
    """Reuse an identical T4 calculation or execute and cache a fresh one."""

    key = build_t4_result_cache_key(
        evidence_bundle=evidence_bundle,
        ifc_context=ifc_context,
    )
    cached = cache.get(key)
    if cached is not None:
        return T4ResultResolution(
            status="cache_hit",
            requested_door_id=ifc_context.subject.door_id,
            llm_skipped=True,
            sandbox_skipped=True,
            cache_key=key,
            result=_for_current_door(cached, ifc_context.subject.door_id),
        )

    result = execute_evacuation_door_rule(
        evidence_bundle=evidence_bundle,
        ifc_context=ifc_context,
        client=client,
        python_executable=python_executable,
        timeout_seconds=timeout_seconds,
    )
    stored = cache.put(key, result)
    return T4ResultResolution(
        status="executed_and_cached" if stored else "executed_not_cached",
        requested_door_id=ifc_context.subject.door_id,
        llm_skipped=False,
        sandbox_skipped=False,
        cache_key=key,
        result=result,
    )


def _evidence_fingerprint(evidence_package: T4EvidencePackage) -> str:
    payload = json.dumps(
        evidence_package.model_dump(mode="json"),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return sha256(payload).hexdigest()


def _is_cacheable(result: RuleServiceResult) -> bool:
    return (
        result.calculation is not None
        and not result.execution_errors
        and result.check_result.result in {CheckStatus.PASS, CheckStatus.FAIL}
    )


def _for_current_door(
    cached: RuleServiceResult,
    door_id: str,
) -> RuleServiceResult:
    """Rebind only the deterministic per-door result envelope."""

    check_result = evaluate_clear_width_rule(
        rule_id=cached.rule_id,
        door_id=door_id,
        calculation=cached.calculation,
    )
    return cached.model_copy(update={"check_result": check_result}, deep=True)
