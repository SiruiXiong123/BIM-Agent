"""Tests for the unified T6 ReviewService.run_review pipeline."""

from __future__ import annotations

from typing import Any

from src.review.models import (
    ReviewPreparation,
    ReviewProgressEvent,
    ReviewSelection,
    ReviewStage,
)
from src.review.service import ReviewService
from src.review.t4_runner import run_t4_batch
from src.review.t5_runner import run_t5_batch
from src.rules.result_cache import T4ResultCache
from src.schemas.result import CheckStatus
from src.search.iterative.building_evidence_cache import BuildingEvidenceCache
from tests.test_review_service import (
    FakeClassificationClient,
    make_selection_preparation,
)
from tests.test_review_t4_runner import (
    FakeRuleResolver,
    make_t3_batch,
    make_t3_run,
)
from tests.test_review_t5_runner import FakeReasonGenerator


def test_run_review_connects_selection_t3_t4_t5_and_complete_progress() -> None:
    preparation = make_selection_preparation()
    selection = ReviewSelection(
        included_uncertain_door_ids=["Door uncertain"],
        occupant_load_overrides={"Door exit": 120},
    )
    classification_client = FakeClassificationClient()
    review_client = FakeClassificationClient()
    evidence_cache = BuildingEvidenceCache()
    t4_cache = T4ResultCache()
    stage_calls: list[dict[str, Any]] = []

    def fake_t3_runner(
        *,
        project_id,
        review_inputs,
        cache,
        task,
        original_query,
        progress,
        client,
    ):
        stage_calls.append(
            {
                "stage": "t3",
                "project_id": project_id,
                "door_ids": [item.candidate.door_id for item in review_inputs],
                "cache": cache,
                "task": task,
                "original_query": original_query,
                "client": client,
            }
        )
        if progress is not None:
            progress(
                ReviewProgressEvent(
                    stage=ReviewStage.T3,
                    current=len(review_inputs),
                    total=len(review_inputs),
                    message="T3 test batch complete",
                )
            )
        runs = [
            make_t3_run(
                item,
                status="retrieved_and_cached" if index == 0 else "cache_hit",
            )
            for index, item in enumerate(review_inputs)
        ]
        result = make_t3_batch(runs)
        return result.model_copy(
            update={
                "project_id": project_id,
                "task": task,
                "original_query": original_query,
            }
        )

    def fake_t4_runner(*, t3_result, cache, progress, client):
        stage_calls.append(
            {
                "stage": "t4",
                "cache": cache,
                "client": client,
            }
        )
        return run_t4_batch(
            t3_result=t3_result,
            cache=cache,
            progress=progress,
            rule_resolver=FakeRuleResolver(),
        )

    reason_generator = FakeReasonGenerator()

    def fake_t5_runner(
        *,
        t4_result,
        source_filename,
        progress,
        client,
    ):
        stage_calls.append(
            {
                "stage": "t5",
                "source_filename": source_filename,
                "client": client,
            }
        )
        return run_t5_batch(
            t4_result=t4_result,
            source_filename=source_filename,
            progress=progress,
            reason_generator=reason_generator,
        )

    progress = []
    service = ReviewService(
        classification_client,
        review_client=review_client,
        t3_runner=fake_t3_runner,
        t4_runner=fake_t4_runner,
        t5_runner=fake_t5_runner,
    )
    result = service.run_review(
        preparation,
        selection,
        evidence_cache=evidence_cache,
        t4_cache=t4_cache,
        original_query="Find the applicable clear-width evidence.",
        progress=progress.append,
    )

    assert [item["stage"] for item in stage_calls] == ["t3", "t4", "t5"]
    assert stage_calls[0]["project_id"] == preparation.project_id
    assert stage_calls[0]["door_ids"] == ["Door uncertain", "Door exit"]
    assert stage_calls[0]["cache"] is evidence_cache
    assert stage_calls[1]["cache"] is t4_cache
    assert all(item["client"] is review_client for item in stage_calls)
    assert stage_calls[2]["source_filename"] == "school.ifc"
    assert [item.door_id for item in result.results] == [
        "Door uncertain",
        "Door exit",
    ]
    assert [item.machine_result for item in result.results] == [
        CheckStatus.FAIL,
        CheckStatus.PASS,
    ]
    assert result.results[0].classification_source.value == "user_confirmation"
    assert result.results[1].t3_cache_hit is True
    assert reason_generator.calls == ["Door uncertain", "Door exit"]
    assert list(dict.fromkeys(event.stage for event in progress)) == [
        ReviewStage.T3,
        ReviewStage.T4,
        ReviewStage.T5,
        ReviewStage.COMPLETE,
    ]
    assert progress[-1].current == progress[-1].total == 2


def test_run_review_returns_empty_batch_when_no_door_is_selected() -> None:
    base = make_selection_preparation()
    preparation = ReviewPreparation(
        project_id=base.project_id,
        source_filename=base.source_filename,
        source_sha256=base.source_sha256,
        ifc_schema=base.ifc_schema,
        unit_scale_to_mm=base.unit_scale_to_mm,
        total_ifc_door_count=1,
        requested_max_doors=None,
        door_count=1,
        candidates=[base.candidates[0]],
    )
    stage_order: list[str] = []

    def empty_t3_runner(
        *,
        project_id,
        review_inputs,
        cache,
        task,
        original_query,
        progress,
        client,
    ):
        del cache, progress, client
        stage_order.append("t3")
        assert review_inputs == []
        result = make_t3_batch([])
        return result.model_copy(
            update={
                "project_id": project_id,
                "task": task,
                "original_query": original_query,
            }
        )

    def empty_t4_runner(*, t3_result, cache, progress, client):
        del client
        stage_order.append("t4")
        return run_t4_batch(
            t3_result=t3_result,
            cache=cache,
            progress=progress,
        )

    def empty_t5_runner(
        *,
        t4_result,
        source_filename,
        progress,
        client,
    ):
        del client
        stage_order.append("t5")
        return run_t5_batch(
            t4_result=t4_result,
            source_filename=source_filename,
            progress=progress,
        )

    progress = []
    service = ReviewService(
        FakeClassificationClient(),
        t3_runner=empty_t3_runner,
        t4_runner=empty_t4_runner,
        t5_runner=empty_t5_runner,
    )
    result = service.run_review(
        preparation,
        ReviewSelection(),
        evidence_cache=BuildingEvidenceCache(),
        t4_cache=T4ResultCache(),
        progress=progress.append,
    )

    assert stage_order == ["t3", "t4", "t5"]
    assert result.total_doors == 0
    assert result.results == []
    assert progress[-1].stage is ReviewStage.COMPLETE
    assert progress[-1].current == progress[-1].total == 0
