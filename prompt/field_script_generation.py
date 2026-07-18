"""Prompt for one evidence-grounded field resolution for the current door."""

FIELD_CALCULATION_PROMPT = r"""
Resolve one target_field for the current door.

You receive only:
- initial_query: the retrieval intent that produced the evidence;
- target_field;
- current_door_context: structured current-door facts selected for target_field;
- assigned_evidence_ids and their text or original table/image evidence.

Use current_door_context as the source of current-door facts. Use initial_query
only to understand the requested calculation and evidence scope. Do not infer or
replace structured facts from prose in initial_query.
First decide whether the final value for the current door can be read directly
from current_door_context and the assigned evidence. If it can, return
resolution=direct_value and value_mm. If arithmetic is required, return
resolution=python_script and a no-argument Python calculation. Do not return a
script for a value that is already directly available.

Do not build a reusable cross-storey or cross-fire-grade lookup rule. For a
table, select only the cell applicable to the current door. Do not combine an
independent minimum, exception or separate clause unless initial_query asks for
that combined calculation. Do not make a PASS/FAIL judgment.

For actual_clear_width_mm:
- Return direct_value when explicit_clear_width_mm is present, or when an item
  in ifc_extra_info clearly represents the door's passable/clear/egress width.
- Do not treat OverallWidth itself as clear width. A generic or ambiguous width
  property is not enough for direct_value.
- When no unambiguous direct clear-width value exists, use overall_width_mm,
  is_fire_door and the assigned conversion evidence to generate python_script.

For required_clear_width_mm:
- Return direct_value when the assigned regulation evidence directly states the
  final applicable threshold for the current door. Converting a stated metre
  value to millimetres is allowed in direct_value.
- If the evidence provides a coefficient, formula, per-person/per-100-person
  value, or other parameters that require arithmetic with current_door_context,
  return python_script.
- Use the current storey, fire-resistance grade and occupant load in
  current_door_context to select the applicable evidence. Do not output a full
  regulation table.

Never invent a direct value. A direct required value must cite assigned
regulation evidence. A direct actual value read only from current_door_context
may use an empty evidence_ids list. Every python_script must cite the assigned
evidence used by the calculation.

When resolution=python_script, source must define exactly this no-argument
function:

def calculate_value() -> dict:

It must return exactly:
{
  "value_mm": number
}

The script must contain all current-case values needed for the calculation.
It must not read inputs, files, environment variables or external state.
Use Python None rather than JSON null. No imports, network, subprocesses,
eval/exec, loops, comprehensions, exceptions, classes, lambdas or nested
functions.

Return only JSON. For a directly available value:
{
  "target_field": "copied from target_field",
  "resolution": "direct_value",
  "value_mm": 900,
  "language": null,
  "entrypoint": null,
  "source": null,
  "evidence_ids": ["assigned evidence IDs actually used"]
}

For a value that requires arithmetic:
{
  "target_field": "copied from target_field",
  "resolution": "python_script",
  "value_mm": null,
  "language": "python",
  "entrypoint": "calculate_value",
  "source": "def calculate_value() -> dict:\n    ...",
  "evidence_ids": ["assigned evidence IDs used by the calculation"]
}
""".strip()
