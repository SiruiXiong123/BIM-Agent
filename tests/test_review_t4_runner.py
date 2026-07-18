"""Tests for T6 batch T4 execution, gating, caching, and failure isolation."""

from __future__ import annotations

import threading
import time

import pytest

from src.review.context_builder import build_ifc_context
from src.review.models import (
    ClassificationSource,
    DoorReviewCandidate,
    DoorReviewInput,
    ReviewProgressEvent,
    ReviewStage,
)
from src.review.t3_runner import T3BatchResult, T3DoorRun
from src.review.t4_runner import T4BatchResult, run_t4_batch
from src.rule_engine import evaluate_clear_width_rule
from src.rules.evidence_groups import build_t4_evidence_package
from src.rules.result_cache import (
    T4ResultCache,
    T4ResultResolution,
    build_t4_result_cache_key,
)
from src.rules.service import RuleServiceResult
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
from src.schemas.rule import RuleCalculationOutput
from src.search.iterative.building_evidence_cache import (
    BuildingEvidenceBundle,
    BuildingEvidenceCacheKey,
    BuildingEvidenceResolution,
)
from src.search.iterative.models import EvidenceHistoryItem, QueryHistoryItem
from src.search.models import DEFAULT_RETRIEVAL_TASK


def make_review_input(
    *,
    index: int,
    door_id: str,
    overall_width: float,
) -> DoorReviewInput:
    ifc_guid = f"guid-{index}"
    assessment = EvacuationDoorClassification(
        ifc_guid=ifc_guid,
        classification=EvacuationDoorClass.EVACUATION_DOOR,
        is_fire_door=False,
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
        building="primary_school",
        storey=SpatialElementReference(
            ifc_class="IfcBuildingStorey",
            name="Ground Floor",
            elevation=0,
        ),
        overall_width=overall_width,
        overall_height=2100,
        occupant_load=100,
        occupant_load_source=InputValueSource.DEFAULT,
        assessment=assessment,
    )
    return DoorReviewInput(
        candidate=DoorReviewCandidate(index=index, record=record),
        classification_source=ClassificationSource.LLM,
        is_fire_door=False,
        occupant_load=100,
        occupant_load_source=InputValueSource.DEFAULT,
        fire_resistance_grade=DEFAULT_FIRE_RESISTANCE_GRADE,
        fire_resistance_grade_source=InputValueSource.DEFAULT,
    )


def make_bundle() -> BuildingEvidenceBundle:
    actual = EvidenceHistoryItem(
        evidence_id="doc:text_actual",
        document_id="doc",
        content_id="text_actual",
        modality="text",
        content="The clear width is calculated from the opening width.",
        score=1,
        iter=1,
    )
    required = EvidenceHistoryItem(
        evidence_id="doc:text_required",
        document_id="doc",
        content_id="text_required",
        modality="text",
        content="The required clear width is specified by the table.",
        score=1,
        iter=1,
    )
    query = QueryHistoryItem(
        hop=1,
        query="疏散门净宽计算规则和阈值是什么？",
        dense_query="What are the calculation rule and threshold?",
        target_document="doc",
        result_count=2,
        evidence_ids=[actual.evidence_id, required.evidence_id],
    )
    return BuildingEvidenceBundle(
        key=BuildingEvidenceCacheKey(
            project_id="project-school",
            building_type="primary_school",
            task=DEFAULT_RETRIEVAL_TASK,
            available_documents=("doc",),
        ),
        source_ifc_guid="guid-1",
        source_door_id="Door 1",
        evidence_history=(actual, required),
        query_history=(query,),
        actual_clear_width_calculation_ready=True,
        actual_clear_width_evidence_ids=(actual.evidence_id,),
        required_clear_width_calculation_ready=True,
        required_clear_width_evidence_ids=(required.evidence_id,),
    )


def make_t3_run(
    review_input: DoorReviewInput,
    *,
    ready: bool = True,
    status: str = "cache_hit",
) -> T3DoorRun:
    context = build_ifc_context(review_input)
    bundle = make_bundle()
    resolution = BuildingEvidenceResolution(
        status=status,
        requested_ifc_guid=context.subject.ifc_guid,
        requested_door_id=context.subject.door_id,
        llm_skipped=status == "cache_hit",
        actual_clear_width_calculation_ready=ready,
        required_clear_width_calculation_ready=ready,
        evidence_bundle=bundle,
    )
    return T3DoorRun(
        review_input=review_input,
        ifc_context=context,
        status=status,
        resolution=resolution,
    )


def make_t3_batch(runs: list[T3DoorRun]) -> T3BatchResult:
    door_ids = [item.review_input.candidate.door_id for item in runs]
    return T3BatchResult(
        project_id="project-school",
        task=DEFAULT_RETRIEVAL_TASK,
        original_query="检查疏散门净宽。",
        execution_order_door_ids=door_ids,
        door_runs=runs,
    )


class FakeRuleResolver:
    def __init__(self, *, fail_door_ids: set[str] | None = None) -> None:
        self.fail_door_ids = fail_door_ids or set()
        self.calls: list[str] = []

    def __call__(self, *, evidence_bundle, ifc_context, cache):
        door_id = ifc_context.subject.door_id
        self.calls.append(door_id)
        if door_id in self.fail_door_ids:
            raise RuntimeError(f"rule execution failed for {door_id}")
        key = build_t4_result_cache_key(
            evidence_bundle=evidence_bundle,
            ifc_context=ifc_context,
        )
        cached = cache.get(key)
        if cached is not None:
            check_result = evaluate_clear_width_rule(
                rule_id=cached.rule_id,
                door_id=door_id,
                calculation=cached.calculation,
            )
            return T4ResultResolution(
                status="cache_hit",
                requested_door_id=door_id,
                llm_skipped=True,
                sandbox_skipped=True,
                cache_key=key,
                result=cached.model_copy(
                    update={"check_result": check_result},
                    deep=True,
                ),
            )

        calculation = RuleCalculationOutput(
            actual_clear_width_mm=max(
                ifc_context.door_facts.overall_width - 100,
                0,
            ),
            required_clear_width_mm=700,
        )
        rule_id = "primary_school_evacuation_door_clear_width"
        result = RuleServiceResult(
            rule_id=rule_id,
            evidence_package=build_t4_evidence_package(evidence_bundle),
            calculation=calculation,
            check_result=evaluate_clear_width_rule(
                rule_id=rule_id,
                door_id=door_id,
                calculation=calculation,
            ),
        )
        stored = cache.put(key, result)
        return T4ResultResolution(
            status="executed_and_cached" if stored else "executed_not_cached",
            requested_door_id=door_id,
            llm_skipped=False,
            sandbox_skipped=False,
            cache_key=key,
            result=result,
        )


def test_batch_executes_once_and_reuses_identical_t4_inputs() -> None:
    first = make_t3_run(
        make_review_input(index=1, door_id="Door 1", overall_width=1200),
        status="retrieved_and_cached",
    )
    second = make_t3_run(
        make_review_input(index=2, door_id="Door 2", overall_width=1200)
    )
    resolver = FakeRuleResolver()
    progress: list[ReviewProgressEvent] = []

    result = run_t4_batch(
        t3_result=make_t3_batch([first, second]),
        cache=T4ResultCache(),
        rule_resolver=resolver,
        progress=progress.append,
    )

    assert resolver.calls == ["Door 1", "Door 2"]
    assert [item.status for item in result.door_runs] == [
        "executed_and_cached",
        "cache_hit",
    ]
    assert result.executed_count == 1
    assert result.cache_hit_count == 1
    assert result.skipped_count == 0
    assert result.error_count == 0
    assert (
        result.door_runs[1].resolution.result.check_result.element_id
        == "Door 2"
    )
    assert [event.stage for event in progress] == [ReviewStage.T4] * 3
    assert progress[-1].current == progress[-1].total == 2
    assert T4BatchResult.model_validate_json(result.model_dump_json()) == result


def test_batch_skips_t3_error_and_insufficient_evidence() -> None:
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
    eligible = make_t3_run(
        make_review_input(
            index=3,
            door_id="Door eligible",
            overall_width=1200,
        )
    )
    resolver = FakeRuleResolver()

    result = run_t4_batch(
        t3_result=make_t3_batch([t3_error, insufficient, eligible]),
        cache=T4ResultCache(),
        rule_resolver=resolver,
    )

    assert [item.status for item in result.door_runs] == [
        "skipped_t3_error",
        "skipped_insufficient_evidence",
        "executed_and_cached",
    ]
    assert resolver.calls == ["Door eligible"]
    assert result.skipped_count == 2


def test_batch_isolates_t4_error_and_continues() -> None:
    failed = make_t3_run(
        make_review_input(index=1, door_id="Door fails", overall_width=900)
    )
    succeeds = make_t3_run(
        make_review_input(index=2, door_id="Door succeeds", overall_width=1100)
    )
    resolver = FakeRuleResolver(fail_door_ids={"Door fails"})

    result = run_t4_batch(
        t3_result=make_t3_batch([failed, succeeds]),
        cache=T4ResultCache(),
        rule_resolver=resolver,
    )

    assert result.door_runs[0].status == "error"
    assert "rule execution failed" in str(result.door_runs[0].detail)
    assert result.door_runs[1].status == "executed_and_cached"
    assert result.error_count == 1
    assert result.executed_count == 1


def test_distinct_exact_input_groups_run_in_parallel() -> None:
    lock = threading.Lock()
    active = 0
    peak_active = 0

    class ParallelResolver(FakeRuleResolver):
        def __call__(self, *, evidence_bundle, ifc_context, cache):
            nonlocal active, peak_active
            with lock:
                active += 1
                peak_active = max(peak_active, active)
            time.sleep(0.05)
            try:
                return super().__call__(
                    evidence_bundle=evidence_bundle,
                    ifc_context=ifc_context,
                    cache=cache,
                )
            finally:
                with lock:
                    active -= 1

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
    result = run_t4_batch(
        t3_result=make_t3_batch(runs),
        cache=T4ResultCache(),
        rule_resolver=ParallelResolver(),
        max_workers=4,
    )

    assert peak_active == 4
    assert [item.t3_run.review_input.candidate.door_id for item in result.door_runs] == [
        f"Door {index}" for index in range(1, 6)
    ]


@pytest.mark.parametrize("value", [0, -1, True, 1.5])
def test_batch_rejects_invalid_max_workers(value) -> None:
    with pytest.raises(ValueError, match="max_workers"):
        run_t4_batch(
            t3_result=make_t3_batch([]),
            cache=T4ResultCache(),
            max_workers=value,
        )
