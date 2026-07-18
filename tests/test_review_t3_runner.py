"""Tests for T6 batch T3 orchestration and evidence reuse ordering."""

from __future__ import annotations

import threading
import time
from typing import Any

import pytest

from src.review.models import (
    ClassificationSource,
    DoorReviewCandidate,
    DoorReviewInput,
    ReviewProgressEvent,
    ReviewStage,
)
from src.review.t3_runner import T3BatchResult, run_t3_batch
from src.schemas.assessment import (
    ClassifiedEvacuationDoorRecord,
    EvacuationDoorClass,
    EvacuationDoorClassification,
)
from src.schemas.bim import (
    DEFAULT_FIRE_RESISTANCE_GRADE,
    InputValueSource,
    SpatialElementReference,
)
from src.search.iterative.building_evidence_cache import (
    BuildingEvidenceCache,
    BuildingEvidenceResolution,
)
from src.search.iterative.models import IFCContext


def make_review_input(
    *,
    index: int,
    door_id: str,
    classification_source: ClassificationSource,
    building: str = "primary_school",
) -> DoorReviewInput:
    raw_classification = (
        EvacuationDoorClass.EVACUATION_DOOR
        if classification_source is ClassificationSource.LLM
        else EvacuationDoorClass.UNCERTAIN
    )
    ifc_guid = f"guid-{index}"
    assessment = EvacuationDoorClassification(
        ifc_guid=ifc_guid,
        classification=raw_classification,
        is_fire_door=None,
        reasoning="test classification",
        evacuation_door_confidence=0.9,
        model_name="test-model",
        prompt_version="test",
    )
    record = ClassifiedEvacuationDoorRecord(
        ifc_guid=ifc_guid,
        door_id=door_id,
        name=door_id,
        door_type="test door",
        operation_type="SINGLE_SWING_LEFT",
        building=building,
        storey=SpatialElementReference(
            ifc_class="IfcBuildingStorey",
            name="Ground Floor",
            elevation=0,
        ),
        overall_width=900 + index * 100,
        overall_height=2100,
        occupant_load=100,
        occupant_load_source=InputValueSource.DEFAULT,
        assessment=assessment,
    )
    candidate = DoorReviewCandidate(index=index, record=record)
    return DoorReviewInput(
        candidate=candidate,
        classification_source=classification_source,
        is_fire_door=False,
        occupant_load=100,
        occupant_load_source=InputValueSource.DEFAULT,
        fire_resistance_grade=DEFAULT_FIRE_RESISTANCE_GRADE,
        fire_resistance_grade_source=InputValueSource.DEFAULT,
    )


class FakeEvidenceResolver:
    def __init__(self, *, fail_door_ids: set[str] | None = None) -> None:
        self.fail_door_ids = fail_door_ids or set()
        self.calls: list[str] = []
        self.cache_ids: list[int] = []
        self._has_evidence = False

    def __call__(
        self,
        *,
        project_id: str,
        task: str,
        original_query: str,
        ifc_context: IFCContext,
        cache: BuildingEvidenceCache,
    ) -> BuildingEvidenceResolution:
        assert project_id == "project-school"
        assert task
        assert original_query
        door_id = ifc_context.subject.door_id
        self.calls.append(door_id)
        self.cache_ids.append(id(cache))
        if door_id in self.fail_door_ids:
            raise RuntimeError(f"retrieval failed for {door_id}")
        status = "cache_hit" if self._has_evidence else "retrieved_and_cached"
        self._has_evidence = True
        return BuildingEvidenceResolution(
            status=status,
            requested_ifc_guid=ifc_context.subject.ifc_guid,
            requested_door_id=door_id,
            llm_skipped=status == "cache_hit",
            actual_clear_width_calculation_ready=True,
            required_clear_width_calculation_ready=True,
        )


def test_batch_prioritizes_llm_confirmed_door_and_preserves_ui_order() -> None:
    review_inputs = [
        make_review_input(
            index=1,
            door_id="Door user confirmed",
            classification_source=ClassificationSource.USER_CONFIRMATION,
        ),
        make_review_input(
            index=2,
            door_id="Door representative",
            classification_source=ClassificationSource.LLM,
        ),
        make_review_input(
            index=3,
            door_id="Door confirmed 2",
            classification_source=ClassificationSource.LLM,
        ),
    ]
    resolver = FakeEvidenceResolver()
    progress: list[ReviewProgressEvent] = []

    result = run_t3_batch(
        project_id="project-school",
        review_inputs=review_inputs,
        cache=BuildingEvidenceCache(),
        evidence_resolver=resolver,
        progress=progress.append,
    )

    assert resolver.calls == [
        "Door representative",
        "Door confirmed 2",
        "Door user confirmed",
    ]
    assert len(set(resolver.cache_ids)) == 1
    assert result.execution_order_door_ids == resolver.calls
    assert [item.review_input.candidate.door_id for item in result.door_runs] == [
        "Door user confirmed",
        "Door representative",
        "Door confirmed 2",
    ]
    assert [item.status for item in result.door_runs] == [
        "cache_hit",
        "retrieved_and_cached",
        "cache_hit",
    ]
    assert result.successful_count == 3
    assert result.cache_hit_count == 2
    assert result.error_count == 0
    assert [item.stage for item in progress] == [ReviewStage.T3] * 4
    assert progress[0].current == 0
    assert progress[-1].current == progress[-1].total == 3
    assert T3BatchResult.model_validate_json(result.model_dump_json()) == result


def test_batch_isolates_one_door_failure_and_continues() -> None:
    review_inputs = [
        make_review_input(
            index=1,
            door_id="Door fails",
            classification_source=ClassificationSource.LLM,
        ),
        make_review_input(
            index=2,
            door_id="Door succeeds",
            classification_source=ClassificationSource.LLM,
        ),
    ]
    resolver = FakeEvidenceResolver(fail_door_ids={"Door fails"})

    result = run_t3_batch(
        project_id="project-school",
        review_inputs=review_inputs,
        cache=BuildingEvidenceCache(),
        evidence_resolver=resolver,
    )

    assert resolver.calls == ["Door fails", "Door succeeds"]
    assert result.door_runs[0].status == "error"
    assert "retrieval failed" in str(result.door_runs[0].error)
    assert result.door_runs[1].status == "retrieved_and_cached"
    assert result.successful_count == 1
    assert result.error_count == 1


def test_empty_batch_is_valid_and_does_not_call_resolver() -> None:
    resolver = FakeEvidenceResolver()

    result = run_t3_batch(
        project_id="project-school",
        review_inputs=[],
        cache=BuildingEvidenceCache(),
        evidence_resolver=resolver,
    )

    assert result.door_runs == []
    assert result.execution_order_door_ids == []
    assert resolver.calls == []


def test_distinct_building_groups_run_in_parallel_up_to_four_workers() -> None:
    review_inputs = [
        make_review_input(
            index=index,
            door_id=f"Door {index}",
            classification_source=ClassificationSource.LLM,
            building=f"school_{index}",
        )
        for index in range(1, 6)
    ]
    lock = threading.Lock()
    active = 0
    peak_active = 0

    def resolver(*, project_id, task, original_query, ifc_context, cache):
        nonlocal active, peak_active
        with lock:
            active += 1
            peak_active = max(peak_active, active)
        time.sleep(0.05)
        with lock:
            active -= 1
        return BuildingEvidenceResolution(
            status="retrieved_and_cached",
            requested_ifc_guid=ifc_context.subject.ifc_guid,
            requested_door_id=ifc_context.subject.door_id,
            llm_skipped=False,
            actual_clear_width_calculation_ready=True,
            required_clear_width_calculation_ready=True,
        )

    result = run_t3_batch(
        project_id="project-school",
        review_inputs=review_inputs,
        cache=BuildingEvidenceCache(),
        evidence_resolver=resolver,
        max_workers=4,
    )

    assert peak_active == 4
    assert [item.review_input.candidate.door_id for item in result.door_runs] == [
        f"Door {index}" for index in range(1, 6)
    ]


@pytest.mark.parametrize("value", [0, -1, True, 1.5])
def test_batch_rejects_invalid_max_workers(value: Any) -> None:
    with pytest.raises(ValueError, match="max_workers"):
        run_t3_batch(
            project_id="project-school",
            review_inputs=[],
            cache=BuildingEvidenceCache(),
            evidence_resolver=FakeEvidenceResolver(),
            max_workers=value,
        )


@pytest.mark.parametrize(
    ("overrides", "message"),
    [
        ({"project_id": ""}, "project_id"),
        ({"task": ""}, "task"),
        ({"original_query": ""}, "original_query"),
    ],
)
def test_batch_rejects_empty_required_text(
    overrides: dict[str, Any],
    message: str,
) -> None:
    arguments: dict[str, Any] = {
        "project_id": "project-school",
        "review_inputs": [],
        "cache": BuildingEvidenceCache(),
        "evidence_resolver": FakeEvidenceResolver(),
    }
    arguments.update(overrides)

    with pytest.raises(ValueError, match=message):
        run_t3_batch(**arguments)
