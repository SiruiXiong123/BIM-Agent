from pathlib import Path
from typing import Any

import pytest

from src.search.document_catalog import DocumentDescriptor
from src.search.iterative.building_evidence_cache import (
    BuildingEvidenceCache,
    BuildingEvidenceCacheError,
    retrieve_or_reuse_building_evidence,
)
from src.search.iterative.models import IFCContext
from src.search.models import DEFAULT_RETRIEVAL_TASK
from tests.test_iterative_models import _ifc_context
from tests.test_iterative_service import (
    FakeRetriever,
    FakeServiceClient,
    _catalog,
    _terminal,
)


class FailIfCalledClient:
    model_name = "must-not-run"

    def complete_json(
        self, *, system_prompt: str, payload: dict[str, Any]
    ) -> dict[str, Any]:
        raise AssertionError("LLM must not be called on a building evidence cache hit")


def _context_for(
    door_id: str,
    ifc_guid: str,
    *,
    building_type: str = "primary_school",
    classification: str = "evacuation_door",
) -> IFCContext:
    data = _ifc_context().model_dump(mode="python")
    data["subject"]["door_id"] = door_id
    data["subject"]["ifc_guid"] = ifc_guid
    data["building_context"]["building_type"] = building_type
    data["assessment"]["classification"] = classification
    data["clear_width_resolution"]["ifc_guid"] = ifc_guid
    data["clear_width_resolution"].update({
        "clear_width": 2900.0,
        "source": "explicit test value",
        "method": "explicit",
    })
    return IFCContext.model_validate(data)


def test_same_project_building_and_evacuation_class_reuses_raw_evidence(
    tmp_path: Path,
) -> None:
    cache = BuildingEvidenceCache()
    catalog = _catalog(tmp_path)
    retrieval_calls: list[tuple[str, str]] = []

    def first_factory(descriptor: DocumentDescriptor) -> FakeRetriever:
        return FakeRetriever(descriptor.document_id, retrieval_calls)

    first = retrieve_or_reuse_building_evidence(
        project_id="primary-school-upload",
        task=DEFAULT_RETRIEVAL_TASK,
        original_query="检查第一扇疏散门净宽。",
        ifc_context=_context_for("Door 15600", "guid-15600"),
        cache=cache,
        catalog=catalog,
        client=FakeServiceClient([_terminal()]),
        retriever_factory=first_factory,
    )

    def fail_factory(descriptor: DocumentDescriptor) -> FakeRetriever:
        raise AssertionError("retriever must not be built on a cache hit")

    second = retrieve_or_reuse_building_evidence(
        project_id="primary-school-upload",
        task=DEFAULT_RETRIEVAL_TASK,
        original_query="检查另一扇疏散门净宽。",
        ifc_context=_context_for("Door 16000", "guid-16000"),
        cache=cache,
        catalog=catalog,
        client=FailIfCalledClient(),
        retriever_factory=fail_factory,
    )

    assert first.status == "retrieved_and_cached"
    assert first.llm_skipped is False
    assert first.retrieval_result is not None
    assert first.actual_clear_width_calculation_ready is True
    assert first.required_clear_width_calculation_ready is True
    assert len(cache) == 1
    assert len(retrieval_calls) == 1

    assert second.status == "cache_hit"
    assert second.llm_skipped is True
    assert second.retrieval_result is None
    assert second.requested_door_id == "Door 16000"
    assert second.evidence_bundle is not None
    assert second.actual_clear_width_calculation_ready is True
    assert second.required_clear_width_calculation_ready is True
    assert second.evidence_bundle.source_door_id == "Door 15600"
    assert second.evidence_bundle.actual_clear_width_calculation_ready is True
    assert second.evidence_bundle.required_clear_width_calculation_ready is True
    assert second.evidence_bundle.evidence_history == (
        tuple(first.retrieval_result.evidence_history)
    )
    assert len(retrieval_calls) == 1


def test_different_building_does_not_reuse_evidence(tmp_path: Path) -> None:
    cache = BuildingEvidenceCache()
    catalog = _catalog(tmp_path)
    retrieval_calls: list[tuple[str, str]] = []

    def factory(descriptor: DocumentDescriptor) -> FakeRetriever:
        return FakeRetriever(descriptor.document_id, retrieval_calls)

    first = retrieve_or_reuse_building_evidence(
        project_id="mixed-use-upload",
        task=DEFAULT_RETRIEVAL_TASK,
        original_query="检查学校疏散门。",
        ifc_context=_context_for("School Door", "school-guid"),
        cache=cache,
        catalog=catalog,
        client=FakeServiceClient([_terminal()]),
        retriever_factory=factory,
    )
    second = retrieve_or_reuse_building_evidence(
        project_id="mixed-use-upload",
        task=DEFAULT_RETRIEVAL_TASK,
        original_query="检查办公楼疏散门。",
        ifc_context=_context_for(
            "Office Door",
            "office-guid",
            building_type="office",
        ),
        cache=cache,
        catalog=catalog,
        client=FakeServiceClient([_terminal()]),
        retriever_factory=factory,
    )

    assert first.status == "retrieved_and_cached"
    assert second.status == "retrieved_and_cached"
    assert second.llm_skipped is False
    assert len(cache) == 2
    assert len(retrieval_calls) == 2


def test_non_evacuation_door_is_rejected_before_llm(tmp_path: Path) -> None:
    with pytest.raises(
        BuildingEvidenceCacheError,
        match="confirmed evacuation door",
    ):
        retrieve_or_reuse_building_evidence(
            project_id="primary-school-upload",
            task=DEFAULT_RETRIEVAL_TASK,
            original_query="检查普通门。",
            ifc_context=_context_for(
                "Internal Door",
                "internal-guid",
                classification="non_evacuation_door",
            ),
            cache=BuildingEvidenceCache(),
            catalog=_catalog(tmp_path),
            client=FailIfCalledClient(),
        )


def test_insufficient_result_does_not_poison_building_cache(
    tmp_path: Path,
) -> None:
    cache = BuildingEvidenceCache()
    calls: list[tuple[str, str]] = []

    def factory(descriptor: DocumentDescriptor) -> FakeRetriever:
        return FakeRetriever(descriptor.document_id, calls)

    resolution = retrieve_or_reuse_building_evidence(
        project_id="primary-school-upload",
        task=DEFAULT_RETRIEVAL_TASK,
        original_query="检查疏散门。",
        ifc_context=_context_for("Door 15600", "guid-15600"),
        cache=cache,
        catalog=_catalog(tmp_path),
        client=FakeServiceClient([_terminal("insufficient_evidence")]),
        retriever_factory=factory,
    )

    assert resolution.status == "retrieved_not_cached"
    assert resolution.actual_clear_width_calculation_ready is True
    assert resolution.required_clear_width_calculation_ready is False
    assert resolution.evidence_bundle is not None
    assert resolution.evidence_bundle.actual_clear_width_calculation_ready is True
    assert resolution.evidence_bundle.required_clear_width_calculation_ready is False
    assert len(cache) == 0
