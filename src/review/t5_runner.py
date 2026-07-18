"""Batch T5 explanation generation and final review-result assembly."""

from __future__ import annotations

from collections.abc import Callable
from concurrent.futures import Future, ThreadPoolExecutor, as_completed
from typing import Protocol

from src.ai.evacuation_door_classifier import StructuredLLMClient
from src.report_generator import DetailedReasonReport, generate_detailed_reason
from src.review.models import (
    DoorReviewResult,
    DoorReviewStatus,
    ReviewBatchResult,
    ReviewProgressEvent,
    ReviewStage,
)
from src.review.t4_runner import T4BatchResult, T4DoorRun
from src.rules.service import RuleServiceResult
from src.search.iterative.models import IFCContext


ProgressCallback = Callable[[ReviewProgressEvent], None]
DEFAULT_T5_MAX_WORKERS = 4


class ReasonGenerator(Protocol):
    def __call__(
        self,
        *,
        t4_result: RuleServiceResult,
        ifc_context: IFCContext,
        client: StructuredLLMClient | None = None,
    ) -> DetailedReasonReport: ...


def run_t5_batch(
    *,
    t4_result: T4BatchResult,
    source_filename: str,
    client: StructuredLLMClient | None = None,
    progress: ProgressCallback | None = None,
    reason_generator: ReasonGenerator = generate_detailed_reason,
    max_workers: int = DEFAULT_T5_MAX_WORKERS,
) -> ReviewBatchResult:
    """Generate one final, serializable result for each T4 door outcome."""

    normalized_source = str(source_filename or "").strip()
    if not normalized_source:
        raise ValueError("source_filename cannot be empty")
    _validate_max_workers(max_workers)

    total = len(t4_result.door_runs)
    _emit_progress(
        progress,
        current=0,
        total=total,
        message="Preparing T5 detailed review results",
    )
    results_by_index: dict[int, DoorReviewResult] = {}
    if total:
        futures: dict[
            Future[tuple[DoorReviewResult, str]], tuple[int, str]
        ] = {}
        with ThreadPoolExecutor(
            max_workers=min(max_workers, total),
            thread_name_prefix="t5-reason",
        ) as executor:
            for index, t4_run in enumerate(t4_result.door_runs):
                door_id = t4_run.t3_run.review_input.candidate.door_id
                future = executor.submit(
                    _resolve_door_result,
                    t4_run=t4_run,
                    client=client,
                    reason_generator=reason_generator,
                )
                futures[future] = (index, door_id)
            for current, future in enumerate(as_completed(futures), start=1):
                index, door_id = futures[future]
                result, message = future.result()
                results_by_index[index] = result
                _emit_progress(
                    progress,
                    current=current,
                    total=total,
                    door_id=door_id,
                    message=message,
                )

    return ReviewBatchResult(
        project_id=t4_result.project_id,
        source_filename=normalized_source,
        total_doors=total,
        results=[results_by_index[index] for index in range(total)],
    )


def _validate_max_workers(value: int) -> None:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise ValueError("max_workers must be a positive integer")


def _resolve_door_result(
    *,
    t4_run: T4DoorRun,
    client: StructuredLLMClient | None,
    reason_generator: ReasonGenerator,
) -> tuple[DoorReviewResult, str]:
    t3_run = t4_run.t3_run
    review_input = t3_run.review_input
    candidate = review_input.candidate
    common = {
        "door_id": candidate.door_id,
        "ifc_guid": candidate.ifc_guid,
        "raw_classification": candidate.raw_classification,
        "effective_classification": review_input.effective_classification,
        "classification_source": review_input.classification_source,
        "overall_width_mm": candidate.overall_width_mm,
        "t3_cache_hit": t3_run.status == "cache_hit",
        "t4_cache_hit": t4_run.status == "cache_hit",
    }

    if t4_run.status == "skipped_insufficient_evidence":
        detail = t4_run.detail or "T3 evidence was insufficient"
        return (
            DoorReviewResult(
                **common,
                status=DoorReviewStatus.SKIPPED,
                detailed_reason=detail,
            ),
            f"{candidate.door_id} skipped because evidence is insufficient",
        )

    if t4_run.status in {"skipped_t3_error", "error"}:
        detail = t4_run.detail or "T4 processing failed"
        return (
            DoorReviewResult(
                **common,
                status=DoorReviewStatus.ERROR,
                error=detail,
            ),
            f"{candidate.door_id} could not produce a T5 result",
        )

    resolution = t4_run.resolution
    context = t3_run.ifc_context
    if resolution is None or context is None:
        detail = "A successful T4 outcome is missing its result or IFC context"
        return (
            DoorReviewResult(
                **common,
                status=DoorReviewStatus.ERROR,
                error=detail,
            ),
            f"{candidate.door_id} could not produce a T5 result",
        )

    rule_result = resolution.result
    try:
        report = reason_generator(
            t4_result=rule_result,
            ifc_context=context,
            client=client,
        )
        calculation = rule_result.calculation
        if calculation is None:
            raise ValueError("T4 did not produce both clear-width values")
        return (
            DoorReviewResult(
                **common,
                actual_clear_width_mm=calculation.actual_clear_width_mm,
                required_clear_width_mm=calculation.required_clear_width_mm,
                machine_result=rule_result.check_result.result,
                display_result=report.result,
                detailed_reason=report.detailed_reason,
                evidence_ids=list(report.evidence_ids),
                status=DoorReviewStatus.COMPLETED,
            ),
            f"{candidate.door_id} completed T5 explanation generation",
        )
    except Exception as exc:
        detail = f"{type(exc).__name__}: {exc}"
        return (
            DoorReviewResult(
                **common,
                status=DoorReviewStatus.ERROR,
                error=detail,
            ),
            f"{candidate.door_id} failed during T5 explanation generation",
        )


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
            stage=ReviewStage.T5,
            current=current,
            total=total,
            door_id=door_id,
            message=message,
        )
    )
