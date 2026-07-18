from __future__ import annotations

from collections.abc import Callable
from typing import Any

import pytest

from src.rules.result_cache import (
    T4ResultCache,
    build_t4_result_cache_key,
    execute_or_reuse_evacuation_door_rule,
)
from src.schemas.result import CheckStatus
from src.search.iterative.models import IFCContext
from tests.test_iterative_models import _ifc_context
from tests.test_t4_pipeline import (
    FailIfCalledClient,
    FakeDirectScriptClient,
    _bundle,
)


def _context_for(
    door_id: str,
    ifc_guid: str,
    *,
    mutate: Callable[[dict[str, Any]], None] | None = None,
) -> IFCContext:
    data = _ifc_context().model_dump(mode="json")
    data["subject"]["door_id"] = door_id
    data["subject"]["ifc_guid"] = ifc_guid
    data["clear_width_resolution"]["ifc_guid"] = ifc_guid
    if mutate is not None:
        mutate(data)
    return IFCContext.model_validate(data)


def test_same_t3_evidence_and_calculation_context_reuses_t4_result() -> None:
    cache = T4ResultCache()
    first_client = FakeDirectScriptClient()
    first_context = _context_for("Door 15600", "guid-15600")
    first = execute_or_reuse_evacuation_door_rule(
        evidence_bundle=_bundle(),
        ifc_context=first_context,
        cache=cache,
        client=first_client,
    )

    def add_different_extra_info(data: dict[str, Any]) -> None:
        data["door_facts"]["extra_info"] = [{
            "source": "VendorPropertySet",
            "data": {"IgnoredForT4Reuse": "different"},
        }]

    second_context = _context_for(
        "Door 16000",
        "guid-16000",
        mutate=add_different_extra_info,
    )
    second = execute_or_reuse_evacuation_door_rule(
        evidence_bundle=_bundle(),
        ifc_context=second_context,
        cache=cache,
        client=FailIfCalledClient(),
    )

    assert first.status == "executed_and_cached"
    assert first.llm_skipped is False
    assert first.sandbox_skipped is False
    assert len(first_client.contexts) == 2
    assert len(cache) == 1

    assert second.status == "cache_hit"
    assert second.llm_skipped is True
    assert second.sandbox_skipped is True
    assert second.result.check_result.element_id == "Door 16000"
    assert second.result.calculation == first.result.calculation
    assert second.result.check_result.result is CheckStatus.PASS
    assert second.result.check_result.element_id != (
        first.result.check_result.element_id
    )


def test_changed_calculation_field_runs_t4_again() -> None:
    cache = T4ResultCache()
    execute_or_reuse_evacuation_door_rule(
        evidence_bundle=_bundle(),
        ifc_context=_context_for("Door 15600", "guid-15600"),
        cache=cache,
        client=FakeDirectScriptClient(),
    )

    def change_width(data: dict[str, Any]) -> None:
        data["door_facts"]["overall_width"] = 2800.0

    second_client = FakeDirectScriptClient()
    second = execute_or_reuse_evacuation_door_rule(
        evidence_bundle=_bundle(),
        ifc_context=_context_for(
            "Door 16000",
            "guid-16000",
            mutate=change_width,
        ),
        cache=cache,
        client=second_client,
    )

    assert second.status == "executed_and_cached"
    assert second.llm_skipped is False
    assert second.sandbox_skipped is False
    assert len(second_client.contexts) == 2
    assert len(cache) == 2


@pytest.mark.parametrize(
    "mutate",
    [
        lambda data: data["door_facts"].update(overall_width=2800.0),
        lambda data: data["clear_width_resolution"].update(
            clear_width=1200.0,
            source="explicit_ifc_property",
            method="explicit",
        ),
        lambda data: data["assessment"].update(is_fire_door=True),
        lambda data: data["building_context"].update(
            building_type="office"
        ),
        lambda data: data["building_context"].update(
            storey_name="Third Floor"
        ),
        lambda data: data["building_context"].update(
            storey_band="above_ground_3"
        ),
        lambda data: data["building_context"].update(
            fire_resistance_grade="三级"
        ),
        lambda data: data["building_context"].update(
            fire_resistance_grade_source="user"
        ),
        lambda data: data["door_facts"].update(occupant_load=200),
        lambda data: data["door_facts"].update(
            occupant_load_source="user"
        ),
    ],
)
def test_each_relevant_calculation_field_changes_cache_key(
    mutate: Callable[[dict[str, Any]], None],
) -> None:
    base = build_t4_result_cache_key(
        evidence_bundle=_bundle(),
        ifc_context=_context_for("Door 15600", "guid-15600"),
    )
    changed = build_t4_result_cache_key(
        evidence_bundle=_bundle(),
        ifc_context=_context_for(
            "Door 16000",
            "guid-16000",
            mutate=mutate,
        ),
    )

    assert changed != base


def test_door_identity_and_ifc_extra_info_do_not_change_cache_key() -> None:
    base = build_t4_result_cache_key(
        evidence_bundle=_bundle(),
        ifc_context=_context_for("Door 15600", "guid-15600"),
    )

    def change_only_extra_info(data: dict[str, Any]) -> None:
        data["door_facts"]["extra_info"] = [{
            "source": "AnotherVendorPropertySet",
            "data": {"Anything": 123},
        }]

    other = build_t4_result_cache_key(
        evidence_bundle=_bundle(),
        ifc_context=_context_for(
            "Door 16000",
            "guid-16000",
            mutate=change_only_extra_info,
        ),
    )

    assert other == base
