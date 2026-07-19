"""Tests for the T6 T1/T2 preparation orchestration."""

from __future__ import annotations

import hashlib
import threading
import time
from pathlib import Path
from typing import Any

import pytest

from src.ifc_parser import IFCParseResult
from src.review.models import (
    ClassificationSource,
    DoorReviewCandidate,
    ReviewPreparation,
    ReviewProgressEvent,
    ReviewSelection,
    ReviewStage,
)
from src.ai.evacuation_door_classifier import (
    build_classification_input,
    classify_evacuation_door_input,
)
from src.review.service import (
    ReviewPreparationError,
    ReviewSelectionError,
    ReviewService,
)
from src.schemas.assessment import (
    ClassifiedEvacuationDoorRecord,
    EvacuationDoorClass,
    EvacuationDoorClassification,
)
from src.schemas.bim import (
    DEFAULT_FIRE_RESISTANCE_GRADE,
    Door,
    ElementPlacement,
    IfcEntityReference,
    InputValueSource,
    SpatialElementReference,
)


def make_door(
    *,
    ifc_id: int,
    ifc_guid: str,
    door_id: str,
    width: float,
) -> Door:
    return Door(
        ifc_schema="IFC4",
        ifc_id=ifc_id,
        ifc_guid=ifc_guid,
        door_id=door_id,
        name=door_id,
        door_type="single swing",
        type_reference=IfcEntityReference(ifc_class="IfcDoorType"),
        operation_type="SINGLE_SWING_LEFT",
        overall_width=width,
        overall_height=2100,
        building="primary_school",
        storey=SpatialElementReference(
            ifc_class="IfcBuildingStorey",
            name="Ground Floor",
            elevation=0,
        ),
        host_element=IfcEntityReference(ifc_class="IfcWall"),
        opening_element=IfcEntityReference(ifc_class="IfcOpeningElement"),
        placement=ElementPlacement(
            x=0,
            y=0,
            z=0,
            matrix=[
                [1, 0, 0, 0],
                [0, 1, 0, 0],
                [0, 0, 1, 0],
                [0, 0, 0, 1],
            ],
        ),
        parse_warnings=["No direct space boundary was available."],
    )


class FakeClassificationClient:
    model_name = "fake-classifier"

    def __init__(self) -> None:
        self.door_ids: list[str] = []

    def complete_json(
        self,
        *,
        system_prompt: str,
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        del system_prompt
        door_id = str(payload["door_id"])
        self.door_ids.append(door_id)
        is_exit = door_id == "Door exit"
        return {
            "classification": "evacuation_door" if is_exit else "uncertain",
            "is_fire_door": False if is_exit else None,
            "evidence": [],
            "reasoning": "fixture classification",
            "missing_information": [] if is_exit else ["spatial topology"],
            "evacuation_door_confidence": 0.95 if is_exit else 0.25,
            "fire_door_confidence": 0.8 if is_exit else None,
        }


def test_prepare_ifc_parses_classifies_and_emits_progress(tmp_path: Path) -> None:
    source = tmp_path / "school.ifc"
    source.write_bytes(b"test IFC content")
    doors = [
        make_door(ifc_id=1, ifc_guid="guid-1", door_id="Door ordinary", width=700),
        make_door(ifc_id=2, ifc_guid="guid-2", door_id="Door exit", width=1600),
    ]
    parser_calls: list[tuple[Path, bool, int | None]] = []

    def fake_parser(
        path: str | Path,
        *,
        strict: bool = False,
        max_doors: int | None = None,
    ) -> IFCParseResult:
        parser_calls.append((Path(path), strict, max_doors))
        return IFCParseResult(
            source_file=str(path),
            ifc_schema="IFC4",
            unit_scale_to_mm=1000,
            total_ifc_door_count=2,
            requested_max_doors=max_doors,
            door_count=2,
            doors=doors,
            warnings=["fixture warning"],
        )

    client = FakeClassificationClient()
    progress: list[ReviewProgressEvent] = []
    preparation = ReviewService(client, parser=fake_parser).prepare_ifc(
        source,
        strict=True,
        max_doors=2,
        progress=progress.append,
    )

    expected_hash = hashlib.sha256(source.read_bytes()).hexdigest()
    assert parser_calls == [(source, True, 2)]
    assert client.door_ids == ["Door ordinary", "Door exit"]
    assert preparation.source_filename == "school.ifc"
    assert preparation.source_sha256 == expected_hash
    assert preparation.project_id == f"ifc-{expected_hash[:16]}"
    assert preparation.total_ifc_door_count == 2
    assert preparation.requested_max_doors == 2
    assert preparation.door_count == 2
    assert preparation.confirmed_evacuation_door_count == 1
    assert preparation.uncertain_door_count == 1
    assert preparation.candidates[0].requires_user_confirmation is True
    assert preparation.candidates[1].raw_is_fire_door is False
    assert preparation.candidates[1].raw_fire_door_confidence == 0.8
    assert preparation.candidates[1].overall_width_mm == 1600
    assert preparation.parser_warnings == ["fixture warning"]
    assert [event.stage for event in progress] == [
        ReviewStage.PARSE,
        ReviewStage.PARSE,
        ReviewStage.CLASSIFY,
        ReviewStage.CLASSIFY,
        ReviewStage.CLASSIFY,
        ReviewStage.AWAITING_CONFIRMATION,
    ]
    assert progress[-1].current == progress[-1].total == 2


def test_prepare_ifc_emits_perf_logs(capsys: pytest.CaptureFixture[str], tmp_path: Path) -> None:
    source = tmp_path / "school.ifc"
    source.write_bytes(b"test IFC content")
    doors = [make_door(ifc_id=1, ifc_guid="guid-1", door_id="Door 1", width=900)]

    def fake_parser(
        path: str | Path,
        *,
        strict: bool = False,
        max_doors: int | None = None,
    ) -> IFCParseResult:
        del strict
        return IFCParseResult(
            source_file=str(path),
            ifc_schema="IFC4",
            unit_scale_to_mm=1000,
            total_ifc_door_count=1,
            requested_max_doors=max_doors,
            door_count=1,
            doors=doors,
        )

    client = FakeClassificationClient()
    ReviewService(client, parser=fake_parser).prepare_ifc(source)

    captured = capsys.readouterr()
    assert "[PERF] IFC parsing finished:" in captured.out
    assert "[PERF] Door classification finished:" in captured.out


def test_classify_evacuation_door_input_emits_llm_timing_logs(
    capsys: pytest.CaptureFixture[str],
) -> None:
    door = make_door(ifc_id=1, ifc_guid="guid-1", door_id="Door 1", width=900)
    classifier_input = build_classification_input(door)

    classify_evacuation_door_input(classifier_input, FakeClassificationClient())

    captured = capsys.readouterr()
    assert "[LLM START]" in captured.out
    assert "[LLM END]" in captured.out
    assert "door=Door 1" in captured.out


def test_prepare_ifc_rejects_classifier_identity_mismatch(tmp_path: Path) -> None:
    source = tmp_path / "school.ifc"
    source.write_bytes(b"test IFC content")
    door = make_door(ifc_id=1, ifc_guid="guid-1", door_id="Door 1", width=900)

    def fake_parser(
        path: str | Path,
        *,
        strict: bool = False,
        max_doors: int | None = None,
    ) -> IFCParseResult:
        del strict
        return IFCParseResult(
            source_file=str(path),
            ifc_schema="IFC4",
            unit_scale_to_mm=1000,
            total_ifc_door_count=1,
            requested_max_doors=max_doors,
            door_count=1,
            doors=[door],
        )

    def mismatched_classifier(
        door: Door,
        client: FakeClassificationClient,
    ) -> EvacuationDoorClassification:
        del door, client
        return EvacuationDoorClassification(
            ifc_guid="another-guid",
            classification=EvacuationDoorClass.UNCERTAIN,
            reasoning="invalid identity fixture",
            model_name="fake-classifier",
            prompt_version="test",
        )

    with pytest.raises(ReviewPreparationError, match="ifc_guid"):
        ReviewService(
            FakeClassificationClient(),
            parser=fake_parser,
            classifier=mismatched_classifier,
        ).prepare_ifc(source)


def test_prepare_ifc_classifies_with_four_workers_and_preserves_door_order(
    tmp_path: Path,
) -> None:
    source = tmp_path / "school.ifc"
    source.write_bytes(b"parallel classification fixture")
    doors = [
        make_door(
            ifc_id=index,
            ifc_guid=f"guid-{index}",
            door_id=f"Door {index}",
            width=700 + index,
        )
        for index in range(1, 9)
    ]

    def fake_parser(
        path: str | Path,
        *,
        strict: bool = False,
        max_doors: int | None = None,
    ) -> IFCParseResult:
        del strict
        return IFCParseResult(
            source_file=str(path),
            ifc_schema="IFC4",
            unit_scale_to_mm=1000,
            total_ifc_door_count=len(doors),
            requested_max_doors=max_doors,
            door_count=len(doors),
            doors=doors,
        )

    lock = threading.Lock()
    active = 0
    peak_active = 0

    def concurrent_classifier(
        door: Door,
        client: FakeClassificationClient,
    ) -> EvacuationDoorClassification:
        nonlocal active, peak_active
        del client
        with lock:
            active += 1
            peak_active = max(peak_active, active)
        time.sleep(0.04)
        with lock:
            active -= 1
        return EvacuationDoorClassification(
            ifc_guid=door.ifc_guid,
            classification=EvacuationDoorClass.UNCERTAIN,
            reasoning="parallel fixture",
            evacuation_door_confidence=0.5,
            model_name="fixture-model",
            prompt_version="fixture-prompt",
        )

    preparation = ReviewService(
        FakeClassificationClient(),
        parser=fake_parser,
        classifier=concurrent_classifier,
        classification_max_workers=4,
    ).prepare_ifc(source)

    assert peak_active == 4
    assert [candidate.door_id for candidate in preparation.candidates] == [
        door.door_id for door in doors
    ]


@pytest.mark.parametrize("invalid", [0, -1, True, 1.5, "4"])
def test_review_service_rejects_invalid_classification_worker_count(
    invalid: object,
) -> None:
    with pytest.raises(ValueError, match="classification_max_workers"):
        ReviewService(
            FakeClassificationClient(),
            classification_max_workers=invalid,  # type: ignore[arg-type]
        )


@pytest.mark.parametrize("invalid", [0, -1, True, 1.5, "all"])
def test_prepare_ifc_rejects_invalid_max_doors(
    tmp_path: Path,
    invalid: object,
) -> None:
    source = tmp_path / "school.ifc"
    source.write_bytes(b"test IFC content")

    def parser_must_not_run(
        path: str | Path,
        *,
        strict: bool = False,
        max_doors: int | None = None,
    ) -> IFCParseResult:
        del path, strict, max_doors
        raise AssertionError("parser must not run for an invalid max_doors")

    with pytest.raises(ValueError, match="max_doors"):
        ReviewService(
            FakeClassificationClient(),
            parser=parser_must_not_run,
        ).prepare_ifc(source, max_doors=invalid)  # type: ignore[arg-type]


def make_selection_preparation() -> ReviewPreparation:
    candidates = [
        make_review_candidate(
            index=1,
            door_id="Door uncertain",
            ifc_guid="guid-uncertain",
            width=700,
            classification=EvacuationDoorClass.UNCERTAIN,
            confidence=0.3,
            is_fire_door=None,
        ),
        make_review_candidate(
            index=2,
            door_id="Door exit",
            ifc_guid="guid-exit",
            width=1600,
            classification=EvacuationDoorClass.EVACUATION_DOOR,
            confidence=0.95,
            is_fire_door=None,
        ),
        make_review_candidate(
            index=3,
            door_id="Door interior",
            ifc_guid="guid-interior",
            width=900,
            classification=EvacuationDoorClass.NON_EVACUATION_DOOR,
            confidence=0.9,
            is_fire_door=False,
        ),
    ]
    return ReviewPreparation(
        project_id="project-school",
        source_filename="school.ifc",
        source_sha256="a" * 64,
        ifc_schema="IFC4",
        unit_scale_to_mm=1000,
        total_ifc_door_count=3,
        requested_max_doors=None,
        door_count=3,
        candidates=candidates,
    )


def make_review_candidate(
    *,
    index: int,
    door_id: str,
    ifc_guid: str,
    width: float,
    classification: EvacuationDoorClass,
    confidence: float,
    is_fire_door: bool | None,
) -> DoorReviewCandidate:
    assessment = EvacuationDoorClassification(
        ifc_guid=ifc_guid,
        classification=classification,
        is_fire_door=is_fire_door,
        reasoning="test classification",
        evacuation_door_confidence=confidence,
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
        overall_width=width,
        overall_height=2100,
        occupant_load=100,
        occupant_load_source=InputValueSource.DEFAULT,
        assessment=assessment,
    )
    return DoorReviewCandidate(index=index, record=record)


def test_build_review_inputs_merges_confirmed_and_user_selected_doors() -> None:
    preparation = make_selection_preparation()
    selection = ReviewSelection(
        included_uncertain_door_ids=["Door uncertain"],
        occupant_load_overrides={
            "Door uncertain": 80,
            "Door exit": 120,
        },
        fire_resistance_grade_overrides={
            "Door uncertain": DEFAULT_FIRE_RESISTANCE_GRADE,
        },
    )

    inputs = ReviewService(FakeClassificationClient()).build_review_inputs(
        preparation,
        selection,
    )

    assert [item.candidate.door_id for item in inputs] == [
        "Door uncertain",
        "Door exit",
    ]
    uncertain, confirmed = inputs
    assert uncertain.classification_source is ClassificationSource.USER_CONFIRMATION
    assert uncertain.occupant_load == 80
    assert uncertain.occupant_load_source is InputValueSource.USER
    assert uncertain.fire_resistance_grade == DEFAULT_FIRE_RESISTANCE_GRADE
    assert uncertain.fire_resistance_grade_source is InputValueSource.USER
    assert uncertain.is_fire_door is False
    assert confirmed.classification_source is ClassificationSource.LLM
    assert confirmed.occupant_load == 120
    assert confirmed.occupant_load_source is InputValueSource.USER
    assert confirmed.fire_resistance_grade == DEFAULT_FIRE_RESISTANCE_GRADE
    assert confirmed.fire_resistance_grade_source is InputValueSource.DEFAULT
    assert confirmed.is_fire_door is False
    assert preparation.candidates[0].occupant_load == 100


def test_build_review_inputs_without_user_actions_keeps_confirmed_doors() -> None:
    inputs = ReviewService(FakeClassificationClient()).build_review_inputs(
        make_selection_preparation(),
        ReviewSelection(),
    )

    assert [item.candidate.door_id for item in inputs] == ["Door exit"]
    assert inputs[0].occupant_load == 100
    assert inputs[0].occupant_load_source is InputValueSource.DEFAULT


@pytest.mark.parametrize(
    ("selection", "message"),
    [
        (
            ReviewSelection(included_uncertain_door_ids=["Door missing"]),
            "not present",
        ),
        (
            ReviewSelection(included_uncertain_door_ids=["Door exit"]),
            "only contain uncertain",
        ),
        (
            ReviewSelection(occupant_load_overrides={"Door uncertain": 80}),
            "entering the review",
        ),
        (
            ReviewSelection(occupant_load_overrides={"Door interior": 80}),
            "entering the review",
        ),
        (
            ReviewSelection(occupant_load_overrides={"Door missing": 80}),
            "not present",
        ),
    ],
)
def test_build_review_inputs_rejects_invalid_cross_object_choices(
    selection: ReviewSelection,
    message: str,
) -> None:
    with pytest.raises(ReviewSelectionError, match=message):
        ReviewService(FakeClassificationClient()).build_review_inputs(
            make_selection_preparation(),
            selection,
        )
