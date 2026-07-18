"""Tests for T6 batch T5 result assembly and failure isolation."""

from __future__ import annotations

import threading
import time

import pytest

from src.report_generator import DetailedReasonReport, T5_RESULT_LABELS
from src.review.models import (
    DoorReviewStatus,
    ReviewBatchResult,
    ReviewProgressEvent,
    ReviewStage,
)
from src.review.t5_runner import run_t5_batch
from src.rules.result_cache import T4ResultCache
from src.schemas.result import CheckStatus
from tests.test_review_t4_runner import (
    FakeRuleResolver,
    make_review_input,
    make_t3_batch,
    make_t3_run,
)
from src.review.t3_runner import T3DoorRun
from src.review.t4_runner import run_t4_batch


class FakeReasonGenerator:
    def __init__(self, *, fail_door_ids: set[str] | None = None) -> None:
        self.fail_door_ids = fail_door_ids or set()
        self.calls: list[str] = []

    def __call__(self, *, t4_result, ifc_context, client=None):
        door_id = ifc_context.subject.door_id
        self.calls.append(door_id)
        if door_id in self.fail_door_ids:
            raise RuntimeError(f"reason generation failed for {door_id}")
        status = t4_result.check_result.result
        return DetailedReasonReport(
            result=T5_RESULT_LABELS[status],
            detailed_reason=(
                f"{door_id}: actual clear width was compared with the "
                "required clear width."
            ),
            evidence_ids=("doc:text_actual", "doc:text_required"),
        )


def test_batch_builds_ordered_final_results_and_preserves_cache_flags() -> None:
    first = make_t3_run(
        make_review_input(index=1, door_id="Door 1", overall_width=1200),
        status="retrieved_and_cached",
    )
    second = make_t3_run(
        make_review_input(index=2, door_id="Door 2", overall_width=1200),
    )
    t4_result = run_t4_batch(
        t3_result=make_t3_batch([first, second]),
        cache=T4ResultCache(),
        rule_resolver=FakeRuleResolver(),
    )
    reason_generator = FakeReasonGenerator()
    progress: list[ReviewProgressEvent] = []

    result = run_t5_batch(
        t4_result=t4_result,
        source_filename="school.ifc",
        reason_generator=reason_generator,
        progress=progress.append,
    )

    assert reason_generator.calls == ["Door 1", "Door 2"]
    assert [item.door_id for item in result.results] == ["Door 1", "Door 2"]
    assert [item.status for item in result.results] == [
        DoorReviewStatus.COMPLETED,
        DoorReviewStatus.COMPLETED,
    ]
    assert result.results[0].t3_cache_hit is False
    assert result.results[0].t4_cache_hit is False
    assert result.results[1].t3_cache_hit is True
    assert result.results[1].t4_cache_hit is True
    assert result.results[1].actual_clear_width_mm == 1100
    assert result.results[1].required_clear_width_mm == 700
    assert result.results[1].machine_result is CheckStatus.PASS
    assert result.results[1].display_result == T5_RESULT_LABELS[CheckStatus.PASS]
    assert result.reviewed_doors == result.passed_doors == 2
    assert [event.stage for event in progress] == [ReviewStage.T5] * 3
    assert progress[-1].current == progress[-1].total == 2
    assert ReviewBatchResult.model_validate_json(result.model_dump_json()) == result


def test_batch_maps_t3_error_and_insufficient_evidence_without_calling_t5() -> None:
    failed_input = make_review_input(
        index=1,
        door_id="Door T3 error",
        overall_width=900,
    )
    t3_error = T3DoorRun(
        review_input=failed_input,
        status="error",
        error="retrieval failed",
    )
    insufficient = make_t3_run(
        make_review_input(
            index=2,
            door_id="Door insufficient",
            overall_width=1000,
        ),
        ready=False,
    )
    t4_result = run_t4_batch(
        t3_result=make_t3_batch([t3_error, insufficient]),
        cache=T4ResultCache(),
        rule_resolver=FakeRuleResolver(),
    )
    reason_generator = FakeReasonGenerator()

    result = run_t5_batch(
        t4_result=t4_result,
        source_filename="school.ifc",
        reason_generator=reason_generator,
    )

    assert reason_generator.calls == []
    assert [item.status for item in result.results] == [
        DoorReviewStatus.ERROR,
        DoorReviewStatus.SKIPPED,
    ]
    assert result.results[0].error == "retrieval failed"
    assert "both calculation-readiness" in str(
        result.results[1].detailed_reason
    )
    assert result.error_doors == 1
    assert result.skipped_doors == 1


def test_batch_isolates_t5_error_and_continues() -> None:
    first = make_t3_run(
        make_review_input(index=1, door_id="Door fails", overall_width=900)
    )
    second = make_t3_run(
        make_review_input(index=2, door_id="Door succeeds", overall_width=1100)
    )
    t4_result = run_t4_batch(
        t3_result=make_t3_batch([first, second]),
        cache=T4ResultCache(),
        rule_resolver=FakeRuleResolver(),
    )
    reason_generator = FakeReasonGenerator(fail_door_ids={"Door fails"})

    result = run_t5_batch(
        t4_result=t4_result,
        source_filename="school.ifc",
        reason_generator=reason_generator,
    )

    assert reason_generator.calls == ["Door fails", "Door succeeds"]
    assert result.results[0].status is DoorReviewStatus.ERROR
    assert "reason generation failed" in str(result.results[0].error)
    assert result.results[1].status is DoorReviewStatus.COMPLETED
    assert result.error_doors == 1
    assert result.reviewed_doors == 1


def test_t5_reason_generation_runs_in_parallel_and_preserves_order() -> None:
    runs = [
        make_t3_run(
            make_review_input(
                index=index,
                door_id=f"Door {index}",
                overall_width=900 + index * 100,
            )
        )
        for index in range(1, 6)
    ]
    t4_result = run_t4_batch(
        t3_result=make_t3_batch(runs),
        cache=T4ResultCache(),
        rule_resolver=FakeRuleResolver(),
    )
    lock = threading.Lock()
    active = 0
    peak_active = 0

    def reason_generator(*, t4_result, ifc_context, client=None):
        nonlocal active, peak_active
        with lock:
            active += 1
            peak_active = max(peak_active, active)
        time.sleep(0.05)
        with lock:
            active -= 1
        return DetailedReasonReport(
            result=T5_RESULT_LABELS[t4_result.check_result.result],
            detailed_reason="parallel reason",
            evidence_ids=("doc:text_actual", "doc:text_required"),
        )

    result = run_t5_batch(
        t4_result=t4_result,
        source_filename="school.ifc",
        reason_generator=reason_generator,
        max_workers=4,
    )

    assert peak_active == 4
    assert [item.door_id for item in result.results] == [
        f"Door {index}" for index in range(1, 6)
    ]


@pytest.mark.parametrize("value", [0, -1, True, 1.5])
def test_batch_rejects_invalid_max_workers(value) -> None:
    with pytest.raises(ValueError, match="max_workers"):
        run_t5_batch(
            t4_result=make_t3_batch([]),
            source_filename="school.ifc",
            max_workers=value,
        )
