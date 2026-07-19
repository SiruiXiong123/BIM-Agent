"""Batch classification CLI that enriches evacuation-door input JSONL."""

from __future__ import annotations

import argparse
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from src.ai.evacuation_door_classifier import (
    StructuredLLMClient,
    classify_evacuation_door_input,
)
from src.ai.openai_compatible_client import OpenAICompatibleJSONClient
from src.schemas.assessment import (
    ClassifiedEvacuationDoorRecord,
    EvacuationDoorClassificationInput,
)


def classify_jsonl(
    input_path: str | Path,
    output_path: str | Path | None = None,
    *,
    limit: int | None = 20,
    workers: int = 5,
    client: StructuredLLMClient | None = None,
) -> Path:
    """Classify rows and write complete records with nested assessments.

    When ``output_path`` is omitted, the input file is atomically updated in
    place. Supplying an output path writes a complete enriched copy instead.
    """

    if limit is not None and limit <= 0:
        raise ValueError("limit must be greater than zero or None")
    if workers <= 0:
        raise ValueError("workers must be greater than zero")

    source = Path(input_path)
    destination = Path(output_path) if output_path is not None else source
    records = _read_records(source)
    pending = [record for record in records if record.assessment is None]
    if limit is not None:
        pending = pending[:limit]

    if not pending:
        if destination != source:
            _write_records(destination, records)
        return destination

    records_by_guid = {record.ifc_guid: record for record in records}
    if len(records_by_guid) != len(records):
        raise ValueError("Classification input contains duplicate ifc_guid values")

    llm_client = client or OpenAICompatibleJSONClient.from_env(
        model_env_key="evacuation_door_model_name",
        timeout_env_key="evacuation_door_timeout_seconds",
        max_output_tokens_env_key="evacuation_door_max_output_tokens",
        enable_thinking_env_key="evacuation_door_enable_thinking",
        default_max_output_tokens=768,
        default_enable_thinking=False,
    )
    errors: list[str] = []
    with ThreadPoolExecutor(max_workers=min(workers, len(pending))) as executor:
        futures = {
            executor.submit(
                classify_evacuation_door_input,
                EvacuationDoorClassificationInput.model_validate(
                    record.model_dump(exclude={"assessment"})
                ),
                llm_client,
            ): record.ifc_guid
            for record in pending
        }
        for completed_count, future in enumerate(as_completed(futures), start=1):
            ifc_guid = futures[future]
            try:
                result = future.result()
            except Exception as exc:
                errors.append(f"{ifc_guid}: {exc}")
                print(
                    f"[{completed_count}/{len(pending)}] ERROR {ifc_guid}: {exc}",
                    file=sys.stderr,
                )
                continue
            records_by_guid[ifc_guid].assessment = result
            _write_records(destination, records)
            print(
                f"[{completed_count}/{len(pending)}] "
                f"{ifc_guid} -> {result.classification}"
            )

    if errors:
        raise RuntimeError(
            f"{len(errors)} classification request(s) failed; successful results were saved."
        )
    return destination


def _read_records(path: Path) -> list[ClassifiedEvacuationDoorRecord]:
    records: list[ClassifiedEvacuationDoorRecord] = []
    with path.open("r", encoding="utf-8-sig") as input_file:
        for line in input_file:
            if line.strip():
                records.append(ClassifiedEvacuationDoorRecord.model_validate_json(line))
    return records


def _write_records(
    destination: Path,
    records: list[ClassifiedEvacuationDoorRecord],
) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_suffix(destination.suffix + ".tmp")
    temporary.write_text(
        "".join(record.model_dump_json() + "\n" for record in records),
        encoding="utf-8",
    )
    temporary.replace(destination)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", type=Path)
    parser.add_argument(
        "output",
        type=Path,
        nargs="?",
        help="optional enriched output; omit to update input atomically",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=20,
        help="maximum number of unclassified input rows (default: 20)",
    )
    parser.add_argument(
        "--workers",
        type=int,
        default=5,
        help="number of concurrent model requests (default: 5)",
    )
    args = parser.parse_args()
    classify_jsonl(
        args.input,
        args.output,
        limit=args.limit,
        workers=args.workers,
    )


if __name__ == "__main__":
    main()
