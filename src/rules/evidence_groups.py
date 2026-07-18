"""Explicit T3-to-T4 evidence grouping and validation."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from src.search.iterative.building_evidence_cache import BuildingEvidenceBundle
from src.search.iterative.models import EvidenceHistoryItem, QueryHistoryItem


class T4EvidenceNotReadyError(ValueError):
    """Raised when T3 has not produced both sufficient evidence groups."""


class T4EvidenceGroup(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    target_field: Literal[
        "actual_clear_width_mm",
        "required_clear_width_mm",
    ]
    evidence_ids: tuple[str, ...] = Field(min_length=1)
    evidence_history: tuple[EvidenceHistoryItem, ...] = Field(min_length=1)
    initial_query: QueryHistoryItem

    @model_validator(mode="after")
    def validate_group(self) -> "T4EvidenceGroup":
        history_ids = tuple(item.evidence_id for item in self.evidence_history)
        if len(history_ids) != len(set(history_ids)):
            raise ValueError("T4 evidence group contains duplicate evidence")
        if set(history_ids) != set(self.evidence_ids):
            raise ValueError("T4 evidence group IDs must match its evidence items")
        return self


class T4EvidencePackage(BaseModel):
    """The only evidence contract accepted by T4 planning."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    project_id: str = Field(min_length=1)
    building_type: str = Field(min_length=1)
    task: str = Field(min_length=1)
    actual_clear_width: T4EvidenceGroup
    required_clear_width: T4EvidenceGroup

    @property
    def evidence_history(self) -> tuple[EvidenceHistoryItem, ...]:
        unique: dict[str, EvidenceHistoryItem] = {}
        for item in (
            *self.actual_clear_width.evidence_history,
            *self.required_clear_width.evidence_history,
        ):
            unique.setdefault(item.evidence_id, item)
        return tuple(unique.values())


def build_t4_evidence_package(
    bundle: BuildingEvidenceBundle,
) -> T4EvidencePackage:
    """Validate readiness and materialize the two T3 evidence groups."""

    if not bundle.actual_clear_width_calculation_ready:
        raise T4EvidenceNotReadyError(
            "T4 requires sufficient actual-clear-width calculation evidence"
        )
    if not bundle.required_clear_width_calculation_ready:
        raise T4EvidenceNotReadyError(
            "T4 requires sufficient required-clear-width calculation evidence"
        )
    if not bundle.query_history:
        raise T4EvidenceNotReadyError(
            "T4 requires the executed T3 query history that produced its evidence"
        )

    evidence_by_id = {
        item.evidence_id: item for item in bundle.evidence_history
    }
    actual = _build_group(
        target_field="actual_clear_width_mm",
        evidence_ids=bundle.actual_clear_width_evidence_ids,
        evidence_by_id=evidence_by_id,
        query_history=bundle.query_history,
    )
    required = _build_group(
        target_field="required_clear_width_mm",
        evidence_ids=bundle.required_clear_width_evidence_ids,
        evidence_by_id=evidence_by_id,
        query_history=bundle.query_history,
    )
    return T4EvidencePackage(
        project_id=bundle.key.project_id,
        building_type=bundle.key.building_type,
        task=bundle.key.task,
        actual_clear_width=actual,
        required_clear_width=required,
    )


def _build_group(
    *,
    target_field: Literal[
        "actual_clear_width_mm",
        "required_clear_width_mm",
    ],
    evidence_ids: tuple[str, ...],
    evidence_by_id: dict[str, EvidenceHistoryItem],
    query_history: tuple[QueryHistoryItem, ...],
) -> T4EvidenceGroup:
    normalized_ids = tuple(dict.fromkeys(evidence_ids))
    if not normalized_ids:
        raise T4EvidenceNotReadyError(
            f"T4 requires evidence IDs for {target_field}"
        )
    unknown = set(normalized_ids) - set(evidence_by_id)
    if unknown:
        raise T4EvidenceNotReadyError(
            f"T4 {target_field} group references unknown evidence IDs: "
            + ", ".join(sorted(unknown))
        )
    return T4EvidenceGroup(
        target_field=target_field,
        evidence_ids=normalized_ids,
        evidence_history=tuple(evidence_by_id[item] for item in normalized_ids),
        initial_query=query_history[0],
    )
