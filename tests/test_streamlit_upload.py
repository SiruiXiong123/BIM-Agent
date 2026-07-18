"""Tests for the Streamlit upload-and-preparation page module."""

from __future__ import annotations

from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

from app.main import (
    build_candidate_editor_rows,
    build_result_table_rows,
    build_review_selection,
    initialize_session_state,
    parse_sample_limit,
    register_uploaded_ifc,
    reset_project_state,
)
from src.review.models import (
    ClassificationSource,
    DoorReviewCandidate,
    DoorReviewResult,
    DoorReviewStatus,
    ReviewBatchResult,
    ReviewPreparation,
    ReviewSelection,
)
from src.rules.result_cache import T4ResultCache
from src.schemas.assessment import (
    ClassifiedEvacuationDoorRecord,
    EvacuationDoorClass,
    EvacuationDoorClassification,
)
from src.schemas.bim import InputValueSource, SpatialElementReference
from src.schemas.result import CheckStatus
from src.search.iterative.building_evidence_cache import BuildingEvidenceCache


@pytest.mark.parametrize(
    ("raw", "expected"),
    [("10", 10), (" 3 ", 3), ("all", None), ("ALL", None)],
)
def test_parse_sample_limit_accepts_positive_integer_or_all(
    raw: str,
    expected: int | None,
) -> None:
    assert parse_sample_limit(raw) == expected


@pytest.mark.parametrize("raw", ["", "0", "-1", "1.5", "ten"])
def test_parse_sample_limit_rejects_invalid_values(raw: str) -> None:
    with pytest.raises(ValueError):
        parse_sample_limit(raw)


def test_new_upload_clears_project_state_but_same_upload_does_not() -> None:
    state: dict[str, object] = {}
    initialize_session_state(state)
    original_evidence_cache = state["evidence_cache"]
    original_t4_cache = state["t4_cache"]

    first_path = register_uploaded_ifc(
        state,
        filename="school.ifc",
        content=b"first IFC fixture",
    )
    state["preparation"] = "prepared"
    same_path = register_uploaded_ifc(
        state,
        filename="school.ifc",
        content=b"first IFC fixture",
    )

    assert same_path == first_path
    assert state["preparation"] == "prepared"
    assert state["evidence_cache"] is not original_evidence_cache
    assert state["t4_cache"] is not original_t4_cache

    evidence_cache_after_first = state["evidence_cache"]
    t4_cache_after_first = state["t4_cache"]
    second_path = register_uploaded_ifc(
        state,
        filename="school-eval.ifc",
        content=b"second IFC fixture",
    )

    assert second_path != first_path
    assert not first_path.exists()
    assert state["preparation"] is None
    assert isinstance(state["evidence_cache"], BuildingEvidenceCache)
    assert isinstance(state["t4_cache"], T4ResultCache)
    assert state["evidence_cache"] is not evidence_cache_after_first
    assert state["t4_cache"] is not t4_cache_after_first

    reset_project_state(state)
    assert not second_path.exists()


def test_upload_rejects_empty_or_non_ifc_file() -> None:
    state: dict[str, object] = {}
    initialize_session_state(state)
    with pytest.raises(ValueError, match=r"\.ifc"):
        register_uploaded_ifc(
            state,
            filename="model.txt",
            content=b"not IFC",
        )
    with pytest.raises(ValueError, match="为空"):
        register_uploaded_ifc(
            state,
            filename="model.ifc",
            content=b"",
        )


def test_streamlit_initial_page_renders_without_connecting_to_llm() -> None:
    app_path = Path(__file__).resolve().parents[1] / "app" / "main.py"
    app = AppTest.from_file(str(app_path), default_timeout=20).run()

    assert not app.exception
    assert [item.value for item in app.subheader] == ["上传 IFC 模型"]
    assert app.text_input[0].label == "处理门数量"
    assert app.text_input[0].value == "10"
    assert "请先上传 IFC 文件" in app.info[0].value


def test_candidate_editor_rows_expose_only_confirmable_ui_fields() -> None:
    preparation = _make_preparation()

    rows = build_candidate_editor_rows(preparation)

    assert list(rows[0]) == [
        "door_id",
        "overall_width_mm",
        "classification",
        "confidence",
        "occupant_load",
        "include_in_review",
    ]
    assert rows == [
        {
            "door_id": "Door exit",
            "overall_width_mm": 1200.0,
            "classification": "疏散门",
            "confidence": 0.96,
            "occupant_load": 100,
            "include_in_review": True,
        },
        {
            "door_id": "Door uncertain",
            "overall_width_mm": 900.0,
            "classification": "待确认",
            "confidence": 0.35,
            "occupant_load": 100,
            "include_in_review": False,
        },
        {
            "door_id": "Door interior",
            "overall_width_mm": 800.0,
            "classification": "非疏散门",
            "confidence": 0.91,
            "occupant_load": 100,
            "include_in_review": False,
        },
    ]


def test_default_editor_selection_keeps_only_confirmed_evacuation_doors() -> None:
    preparation = _make_preparation()

    selection = build_review_selection(
        preparation,
        build_candidate_editor_rows(preparation),
    )

    assert selection == ReviewSelection()


def test_editor_selection_adds_uncertain_and_preserves_only_effective_overrides() -> None:
    preparation = _make_preparation()
    rows = build_candidate_editor_rows(preparation)
    rows[0]["occupant_load"] = 120
    rows[1]["include_in_review"] = True
    rows[1]["occupant_load"] = 80
    rows[2]["occupant_load"] = 50

    selection = build_review_selection(preparation, rows)

    assert selection.included_uncertain_door_ids == ["Door uncertain"]
    assert selection.occupant_load_overrides == {
        "Door exit": 120,
        "Door uncertain": 80,
    }


def test_editor_selection_rejects_non_evacuation_door_and_invalid_load() -> None:
    preparation = _make_preparation()
    rows = build_candidate_editor_rows(preparation)
    rows[2]["include_in_review"] = True
    with pytest.raises(ValueError, match="非疏散门"):
        build_review_selection(preparation, rows)

    rows = build_candidate_editor_rows(preparation)
    rows[0]["occupant_load"] = 1.5
    with pytest.raises(ValueError, match="正整数"):
        build_review_selection(preparation, rows)


def test_streamlit_confirmation_page_builds_default_selection() -> None:
    app_path = Path(__file__).resolve().parents[1] / "app" / "main.py"
    app = AppTest.from_file(str(app_path), default_timeout=20)
    app.session_state["preparation"] = _make_preparation()
    app.run()

    assert not app.exception
    assert [item.value for item in app.subheader] == [
        "模型准备结果",
        "确认参与检查的门",
    ]
    next_button = next(
        button
        for button in app.button
        if button.label == "NEXT · 进入执行阶段"
    )
    next_button.click().run()

    assert not app.exception
    assert app.session_state["review_selection"] == ReviewSelection()
    assert "门确认已完成" in [item.value for item in app.subheader]


def test_visible_result_rows_exclude_machine_result() -> None:
    result = ReviewBatchResult(
        project_id="project-school",
        source_filename="school.ifc",
        total_doors=1,
        results=[
            DoorReviewResult(
                door_id="Door exit",
                ifc_guid="guid-exit",
                raw_classification=EvacuationDoorClass.EVACUATION_DOOR,
                effective_classification=EvacuationDoorClass.EVACUATION_DOOR,
                classification_source=ClassificationSource.LLM,
                overall_width_mm=1200,
                actual_clear_width_mm=1100,
                required_clear_width_mm=700,
                machine_result=CheckStatus.PASS,
                display_result="合格",
                detailed_reason="实际净宽大于规范阈值。",
                evidence_ids=["doc:table_1"],
                status=DoorReviewStatus.COMPLETED,
            )
        ],
    )

    rows = build_result_table_rows(result)

    assert "machine_result" not in rows[0]
    assert rows[0]["result"] == "合格"
    assert rows[0]["actual_clear_width_mm"] == 1100
    assert rows[0]["required_clear_width_mm"] == 700


def _make_preparation() -> ReviewPreparation:
    definitions = (
        (
            "Door exit",
            "guid-exit",
            1200.0,
            EvacuationDoorClass.EVACUATION_DOOR,
            0.96,
        ),
        (
            "Door uncertain",
            "guid-uncertain",
            900.0,
            EvacuationDoorClass.UNCERTAIN,
            0.35,
        ),
        (
            "Door interior",
            "guid-interior",
            800.0,
            EvacuationDoorClass.NON_EVACUATION_DOOR,
            0.91,
        ),
    )
    candidates: list[DoorReviewCandidate] = []
    for index, (door_id, guid, width, classification, confidence) in enumerate(
        definitions,
        start=1,
    ):
        assessment = EvacuationDoorClassification(
            ifc_guid=guid,
            classification=classification,
            is_fire_door=False,
            reasoning="streamlit fixture",
            evacuation_door_confidence=confidence,
            fire_door_confidence=0.8,
            model_name="fixture-model",
            prompt_version="fixture",
        )
        record = ClassifiedEvacuationDoorRecord(
            ifc_guid=guid,
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
        candidates.append(DoorReviewCandidate(index=index, record=record))
    return ReviewPreparation(
        project_id="project-school",
        source_filename="school.ifc",
        source_sha256="a" * 64,
        ifc_schema="IFC4",
        unit_scale_to_mm=1000,
        total_ifc_door_count=3,
        door_count=3,
        candidates=candidates,
    )
