"""LLM-assisted evacuation-door classification, separate from IFC parsing."""

from __future__ import annotations

import json
import threading
from pathlib import Path
from time import perf_counter
from typing import Any, Protocol

from prompt.evacuation_door_classification import (
    EVACUATION_DOOR_CLASSIFICATION_PROMPT,
)
from src.schemas.assessment import (
    EvacuationDoorClassification,
    EvacuationDoorClassificationInput,
)
from src.schemas.bim import Door


PROMPT_VERSION = "evacuation-and-fire-door-v3"


SYSTEM_PROMPT = EVACUATION_DOOR_CLASSIFICATION_PROMPT


class StructuredLLMClient(Protocol):
    """Minimal adapter implemented by the configured LLM provider."""

    @property
    def model_name(self) -> str: ...

    def complete_json(
        self,
        *,
        system_prompt: str,
        payload: dict[str, Any],
    ) -> dict[str, Any]: ...

    def complete_json_multimodal(
        self,
        *,
        system_prompt: str,
        content: list[dict[str, Any]],
    ) -> dict[str, Any]: ...


def classify_evacuation_door(
    door: Door,
    client: StructuredLLMClient,
) -> EvacuationDoorClassification:
    """Ask an LLM for a schema-validated, auditable semantic classification."""

    return classify_evacuation_door_input(build_classification_input(door), client)


def classify_evacuation_door_input(
    classifier_input: EvacuationDoorClassificationInput,
    client: StructuredLLMClient,
) -> EvacuationDoorClassification:
    """Classify an already-built LLM input payload."""

    payload = classifier_input.model_dump(mode="json")
    rendered_prompt = SYSTEM_PROMPT
    door_id = classifier_input.door_id
    thread_name = threading.current_thread().name
    start = perf_counter()
    print(
        f"[LLM START] door={door_id} thread={thread_name}",
        flush=True,
    )
    response = client.complete_json(system_prompt=rendered_prompt, payload=payload)
    elapsed = perf_counter() - start
    print(
        f"[LLM END] door={door_id} thread={thread_name} elapsed={elapsed:.2f}s",
        flush=True,
    )
    response.update(
        {
            "ifc_guid": classifier_input.ifc_guid,
            "model_name": client.model_name,
            "prompt_version": PROMPT_VERSION,
        }
    )
    return EvacuationDoorClassification.model_validate(response)


def build_classification_input(door: Door) -> EvacuationDoorClassificationInput:
    """Build the stable, reduced IFC fact view supplied to the LLM."""

    return EvacuationDoorClassificationInput(
        ifc_guid=door.ifc_guid,
        door_id=door.door_id,
        name=door.name,
        door_type=door.door_type,
        type_description=door.type_reference.description,
        operation_type=door.operation_type,
        building=door.building,
        storey=door.storey,
        overall_width=door.overall_width,
        overall_height=door.overall_height,
        occupant_load=door.occupant_load,
        occupant_load_source=door.occupant_load_source,
        fire_resistance_grade=door.fire_resistance_grade,
        fire_resistance_grade_source=door.fire_resistance_grade_source,
        adjacent_spaces=door.adjacent_spaces,
        extra_info=door.extra_info,
        data_quality_warnings=door.parse_warnings,
    )


def write_classification_inputs_jsonl(
    filtered_parser_jsonl: str | Path,
    output_path: str | Path,
) -> Path:
    """Write one exact LLM classification payload per filtered door record."""

    source = Path(filtered_parser_jsonl)
    destination = Path(output_path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    output_lines: list[str] = []

    for line_number, line in enumerate(
        source.read_text(encoding="utf-8-sig").splitlines(), start=1
    ):
        if not line.strip():
            continue
        try:
            record = json.loads(line)
        except json.JSONDecodeError as exc:
            raise ValueError(
                f"Invalid JSON on line {line_number} of {source}: {exc.msg}"
            ) from exc
        if record.get("record_type") != "door":
            continue
        door_data = {
            key: value
            for key, value in record.items()
            if key not in {"record_type", "door_index"}
        }
        classifier_input = build_classification_input(Door.model_validate(door_data))
        output_lines.append(classifier_input.model_dump_json())

    destination.write_text("\n".join(output_lines) + "\n", encoding="utf-8")
    return destination
