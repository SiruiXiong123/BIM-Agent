"""Filter parser JSONL door properties to evacuation-relevant evidence."""

import argparse
import json
from pathlib import Path
from typing import Any

from src.schemas.bim import Door, ExtraInfoItem


# Keep this list close to the filtering logic while it remains small and
# project-owned. Matching ignores surrounding whitespace and letter case, but
# output retains the source model's original names and values.
EXTRA_INFO_WHITELIST: dict[str, frozenset[str]] = {
    "PSet_Revit_Type_Other": frozenset({"IsFireExit"}),
    "Pset_DoorCommon": frozenset({"FireRating"}),
    "PSet_Revit_Type_Identity Data": frozenset({"Fire Rating"}),
    "ArchiCADProperties": frozenset(
        {
            "Egress Dimensions",
            "From Zone",
            "To Zone",
            "Zone Name",
        }
    ),
    "AC_Equantity_Door_19": frozenset(
        {
            "Egress Width",
            "Egress Height",
        }
    ),
}


def _normalized_whitelist() -> dict[str, frozenset[str]]:
    """Return normalized names used only for safe exact matching."""

    return {
        source.strip().casefold(): frozenset(
            field.strip().casefold() for field in fields
        )
        for source, fields in EXTRA_INFO_WHITELIST.items()
    }


def _is_meaningful(value: Any) -> bool:
    """Reject absent values while retaining valid values such as False and 0."""

    if value is None:
        return False
    if isinstance(value, str):
        return bool(value.strip())
    if isinstance(value, (list, tuple, set, dict)):
        return bool(value)
    return True


def filter_extra_info(
    extra_info: list[ExtraInfoItem],
) -> list[ExtraInfoItem]:
    """Return only evacuation-relevant properties from ``extra_info``.

    The input list and its items are not mutated. A source item is omitted when
    none of its fields are both whitelisted and meaningful.
    """

    whitelist = _normalized_whitelist()
    filtered_items: list[ExtraInfoItem] = []

    for item in extra_info:
        allowed_fields = whitelist.get(item.source.strip().casefold())
        if allowed_fields is None:
            continue

        filtered_data = {
            key: value
            for key, value in item.data.items()
            if key.strip().casefold() in allowed_fields and _is_meaningful(value)
        }
        if filtered_data:
            filtered_items.append(
                ExtraInfoItem(source=item.source, data=filtered_data)
            )

    return filtered_items


def filter_door_extra_info(door: Door) -> Door:
    """Return a copy of a door with its ``extra_info`` filtered."""

    return door.model_copy(
        update={"extra_info": filter_extra_info(door.extra_info)},
        deep=True,
    )


def filter_jsonl(
    input_path: str | Path,
    output_path: str | Path,
) -> Path:
    """Filter ``extra_info`` in parser JSONL while preserving all other data.

    Metadata and any other non-door records are copied unchanged. For door
    records, only ``extra_info`` is replaced; every other top-level field keeps
    its original value and order.
    """

    source = Path(input_path)
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

        if record.get("record_type") == "door":
            raw_extra_info = record.get("extra_info", [])
            if not isinstance(raw_extra_info, list):
                raise ValueError(
                    f"Door record on line {line_number} has non-list extra_info"
                )
            items = [ExtraInfoItem.model_validate(item) for item in raw_extra_info]
            record["extra_info"] = [
                item.model_dump(mode="json") for item in filter_extra_info(items)
            ]

        output_lines.append(json.dumps(record, ensure_ascii=False, sort_keys=False))

    destination.write_text("\n".join(output_lines) + "\n", encoding="utf-8")
    return destination


def main() -> None:
    """Run the JSONL filter from the command line."""

    parser = argparse.ArgumentParser(
        description="Filter evacuation-relevant fields in IFC parser JSONL output."
    )
    parser.add_argument("input", type=Path, help="IFC parser JSONL input path")
    parser.add_argument("output", type=Path, help="Filtered JSONL output path")
    args = parser.parse_args()
    filter_jsonl(args.input, args.output)


if __name__ == "__main__":
    main()
