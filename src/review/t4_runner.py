"""Batch T4 rule execution with exact calculation-input result reuse."""

from __future__ import annotations

from collections.abc import Callable
from concurrent.futures import Future, ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Literal, Protocol

from pydantic import BaseModel, ConfigDict, Field, model_validator

from src.ai.evacuation_door_classifier import StructuredLLMClient
from src.review.models import ReviewProgressEvent, ReviewStage
from src.review.t3_runner import T3BatchResult, T3DoorRun
from src.rules.result_cache import (
    T4ResultCache,
    T4ResultCacheKey,
    T4ResultResolution,
    build_t4_result_cache_key,
    execute_or_reuse_evacuation_door_rule,
)
from src.rules.sandbox_runner import DEFAULT_PYTHON_EXECUTABLE
from src.search.iterative.building_evidence_cache import BuildingEvidenceBundle
from src.search.iterative.models import IFCContext


T4DoorStatus = Literal[
    "cache_hit",
    "executed_and_cached",
    "executed_not_cached",
    "skipped_t3_error",
    "skipped_insufficient_evidence",
    "error",
]
ProgressCallback = Callable[[ReviewProgressEvent], None]
DEFAULT_T4_MAX_WORKERS = 4


class RuleResolver(Protocol):
    def __call__(
        self,
        *,
        evidence_bundle: BuildingEvidenceBundle,
        ifc_context: IFCContext,
        cache: T4ResultCache,
    ) -> T4ResultResolution: ...


class T4DoorRun(BaseModel):
    """One T3 door outcome enriched with its T4 execution result."""

    model_config = ConfigDict(extra="forbid")

    t3_run: T3DoorRun
    status: T4DoorStatus
    resolution: T4ResultResolution | None = None
    detail: str | None = None

    @model_validator(mode="after")
    def validate_outcome(self) -> "T4DoorRun":
        successful = {
            "cache_hit",
            "executed_and_cached",
            "executed_not_cached",
        }
        door_id = self.t3_run.review_input.candidate.door_id
        if self.status in successful:
            if self.resolution is None:
                raise ValueError("a successful T4 result requires a resolution")
            if self.detail is not None:
                raise ValueError("a successful T4 result cannot contain detail")
            if self.status != self.resolution.status:
                raise ValueError("T4 status must match resolution.status")
            if self.resolution.requested_door_id != door_id:
                raise ValueError("T4 resolution door_id does not match T3 input")
            return self
        if self.resolution is not None:
            raise ValueError("a skipped or failed T4 result cannot contain resolution")
        if not self.detail or not self.detail.strip():
            raise ValueError("a skipped or failed T4 result requires detail")
        return self


class T4BatchResult(BaseModel):
    """T4 results in exactly the same door order as the source T3 batch."""

    model_config = ConfigDict(extra="forbid")

    project_id: str = Field(min_length=1)
    door_runs: list[T4DoorRun] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_runs(self) -> "T4BatchResult":
        door_ids = [
            item.t3_run.review_input.candidate.door_id for item in self.door_runs
        ]
        if len(door_ids) != len(set(door_ids)):
            raise ValueError("T4 batch door IDs must be unique")
        return self

    @property
    def executed_count(self) -> int:
        return sum(
            item.status in {"executed_and_cached", "executed_not_cached"}
            for item in self.door_runs
        )

    @property
    def cache_hit_count(self) -> int:
        return sum(item.status == "cache_hit" for item in self.door_runs)

    @property
    def skipped_count(self) -> int:
        return sum(item.status.startswith("skipped_") for item in self.door_runs)

    @property
    def error_count(self) -> int:
        return sum(item.status == "error" for item in self.door_runs)


def run_t4_batch(
    *,
    t3_result: T3BatchResult,
    cache: T4ResultCache,
    progress: ProgressCallback | None = None,
    rule_resolver: RuleResolver | None = None,
    client: StructuredLLMClient | None = None,
    python_executable: str | Path = DEFAULT_PYTHON_EXECUTABLE,
    timeout_seconds: float = 3.0,
    max_workers: int = DEFAULT_T4_MAX_WORKERS,
) -> T4BatchResult:
    """Execute or safely reuse T4 for every eligible T3 door result."""

    _validate_max_workers(max_workers)
    total = len(t3_result.door_runs)
    _emit_progress(
        progress,
        current=0,
        total=total,
        message="正在准备 T4 门净宽规则执行",
    )
    runs_by_index: dict[int, T4DoorRun] = {}
    messages_by_index: dict[int, str] = {}
    groups: dict[
        T4ResultCacheKey,
        list[tuple[int, T3DoorRun, BuildingEvidenceBundle, IFCContext]],
    ] = {}
    for index, t3_run in enumerate(t3_result.door_runs):
        door_id = t3_run.review_input.candidate.door_id
        if t3_run.status == "error":
            runs_by_index[index] = T4DoorRun(
                t3_run=t3_run,
                status="skipped_t3_error",
                detail=t3_run.error or "T3 failed without an error message",
            )
            messages_by_index[index] = f"{door_id} 因 T3 失败跳过 T4"
            continue

        context = t3_run.ifc_context
        t3_resolution = t3_run.resolution
        bundle = (
            t3_resolution.evidence_bundle
            if t3_resolution is not None
            else None
        )
        if (
            context is None
            or t3_resolution is None
            or bundle is None
            or not t3_resolution.actual_clear_width_calculation_ready
            or not t3_resolution.required_clear_width_calculation_ready
        ):
            runs_by_index[index] = T4DoorRun(
                t3_run=t3_run,
                status="skipped_insufficient_evidence",
                detail=(
                    "T3 did not provide a reusable evidence bundle with "
                    "both calculation-readiness judgments"
                ),
            )
            messages_by_index[index] = f"{door_id} 因证据不足跳过 T4"
            continue

        try:
            key = build_t4_result_cache_key(
                evidence_bundle=bundle,
                ifc_context=context,
            )
        except Exception as exc:
            runs_by_index[index] = T4DoorRun(
                t3_run=t3_run,
                status="error",
                detail=f"{type(exc).__name__}: {exc}",
            )
            messages_by_index[index] = f"{door_id} 的 T4 分组失败"
            continue
        groups.setdefault(key, []).append((index, t3_run, bundle, context))

    completed = 0
    for index in sorted(runs_by_index):
        completed += 1
        _emit_progress(
            progress,
            current=completed,
            total=total,
            door_id=t3_result.door_runs[index].review_input.candidate.door_id,
            message=messages_by_index[index],
        )

    if groups:
        futures: dict[
            Future[list[tuple[int, T4DoorRun, str]]], T4ResultCacheKey
        ] = {}
        with ThreadPoolExecutor(
            max_workers=min(max_workers, len(groups)),
            thread_name_prefix="t4-rule",
        ) as executor:
            for key, group in groups.items():
                future = executor.submit(
                    _run_t4_group,
                    group=group,
                    cache=cache,
                    rule_resolver=rule_resolver,
                    client=client,
                    python_executable=python_executable,
                    timeout_seconds=timeout_seconds,
                )
                futures[future] = key
            for future in as_completed(futures):
                for index, run, message in future.result():
                    runs_by_index[index] = run
                    completed += 1
                    _emit_progress(
                        progress,
                        current=completed,
                        total=total,
                        door_id=(
                            run.t3_run.review_input.candidate.door_id
                        ),
                        message=message,
                    )

    return T4BatchResult(
        project_id=t3_result.project_id,
        door_runs=[runs_by_index[index] for index in range(total)],
    )


def _run_t4_group(
    *,
    group: list[
        tuple[int, T3DoorRun, BuildingEvidenceBundle, IFCContext]
    ],
    cache: T4ResultCache,
    rule_resolver: RuleResolver | None,
    client: StructuredLLMClient | None,
    python_executable: str | Path,
    timeout_seconds: float,
) -> list[tuple[int, T4DoorRun, str]]:
    """Run one exact-input group serially so only its representative calls LLM."""

    outcomes: list[tuple[int, T4DoorRun, str]] = []
    for index, t3_run, bundle, context in group:
        door_id = t3_run.review_input.candidate.door_id
        try:
            resolution = _resolve_rule(
                evidence_bundle=bundle,
                ifc_context=context,
                cache=cache,
                rule_resolver=rule_resolver,
                client=client,
                python_executable=python_executable,
                timeout_seconds=timeout_seconds,
            )
            run = T4DoorRun(
                t3_run=t3_run,
                status=resolution.status,
                resolution=resolution,
            )
            message = (
                f"{door_id} 已复用 T4 计算结果"
                if resolution.status == "cache_hit"
                else f"{door_id} 已完成 T4 规则执行"
            )
        except Exception as exc:
            run = T4DoorRun(
                t3_run=t3_run,
                status="error",
                detail=f"{type(exc).__name__}: {exc}",
            )
            message = f"{door_id} 的 T4 处理失败"
        outcomes.append((index, run, message))
    return outcomes


def _resolve_rule(
    *,
    evidence_bundle: BuildingEvidenceBundle,
    ifc_context: IFCContext,
    cache: T4ResultCache,
    rule_resolver: RuleResolver | None,
    client: StructuredLLMClient | None,
    python_executable: str | Path,
    timeout_seconds: float,
) -> T4ResultResolution:
    if rule_resolver is not None:
        return rule_resolver(
            evidence_bundle=evidence_bundle,
            ifc_context=ifc_context,
            cache=cache,
        )
    return execute_or_reuse_evacuation_door_rule(
        evidence_bundle=evidence_bundle,
        ifc_context=ifc_context,
        cache=cache,
        client=client,
        python_executable=python_executable,
        timeout_seconds=timeout_seconds,
    )


def _validate_max_workers(value: int) -> None:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise ValueError("max_workers must be a positive integer")


def _emit_progress(
    callback: ProgressCallback | None,
    *,
    current: int,
    total: int,
    message: str,
    door_id: str | None = None,
) -> None:
    if callback is None:
        return
    callback(
        ReviewProgressEvent(
            stage=ReviewStage.T4,
            current=current,
            total=total,
            door_id=door_id,
            message=message,
        )
    )
