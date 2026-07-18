"""Tests for resumable T1/T2 preparation snapshots."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.review.models import DoorReviewCandidate, ReviewPreparation
from src.review.preparation_cache import (
    PreparationSnapshotError,
    PreparationSnapshotStore,
)
from src.schemas.assessment import (
    ClassifiedEvacuationDoorRecord,
    EvacuationDoorClass,
    EvacuationDoorClassification,
)
from src.schemas.bim import InputValueSource, SpatialElementReference


def test_preparation_snapshot_round_trip(tmp_path: Path) -> None:
    store = PreparationSnapshotStore(tmp_path / "snapshots")
    preparation = _make_preparation()

    token = store.save(preparation)
    restored = store.load(token)

    assert restored == preparation
    assert preparation.source_sha256 in token
    assert "-10-" in token


def test_preparation_snapshot_rejects_invalid_or_tampered_data(
    tmp_path: Path,
) -> None:
    store = PreparationSnapshotStore(tmp_path / "snapshots")
    token = store.save(_make_preparation())
    snapshot_path = store.root / f"{token}.json"
    payload = json.loads(snapshot_path.read_text(encoding="utf-8"))
    payload["preparation"]["source_sha256"] = "b" * 64
    snapshot_path.write_text(
        json.dumps(payload, ensure_ascii=False),
        encoding="utf-8",
    )

    with pytest.raises(PreparationSnapshotError, match="校验失败"):
        store.load(token)
    with pytest.raises(PreparationSnapshotError, match="无效"):
        store.load("../../outside")


def _make_preparation() -> ReviewPreparation:
    assessment = EvacuationDoorClassification(
        ifc_guid="guid-exit",
        classification=EvacuationDoorClass.EVACUATION_DOOR,
        is_fire_door=False,
        reasoning="snapshot fixture",
        evacuation_door_confidence=0.95,
        fire_door_confidence=0.8,
        model_name="fixture-model",
        prompt_version="fixture-prompt",
    )
    record = ClassifiedEvacuationDoorRecord(
        ifc_guid="guid-exit",
        door_id="Door exit",
        name="Door exit",
        door_type="test door",
        operation_type="SINGLE_SWING_LEFT",
        building="primary_school",
        storey=SpatialElementReference(
            ifc_class="IfcBuildingStorey",
            name="Ground Floor",
            elevation=0,
        ),
        overall_width=1200,
        overall_height=2100,
        occupant_load=100,
        occupant_load_source=InputValueSource.DEFAULT,
        assessment=assessment,
    )
    return ReviewPreparation(
        project_id="project-school",
        source_filename="school.ifc",
        source_sha256="a" * 64,
        ifc_schema="IFC4",
        unit_scale_to_mm=1000,
        total_ifc_door_count=57,
        requested_max_doors=10,
        door_count=1,
        candidates=[DoorReviewCandidate(index=1, record=record)],
    )
