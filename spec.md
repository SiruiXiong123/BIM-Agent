# BIM_Agent

## Why

Evacuation door clear-width inspection requires both BIM model data extraction and regulatory interpretation. The current process relies mainly on manual model verification and code comparison, which struggles with complex models and diverse requirements. Converting regulation clauses into machine-executable rules and applying automated IFC checks can improve fire compliance review efficiency and reliability during the design phase.

## What

Deliver a runnable web BIM compliance review agent prototype. The prototype should automatically extract evacuation door information from IFC models, convert building regulations into executable rules, perform automated evacuation door clear-width compliance checks, and generate interpretable inspection reports that locate non-compliant elements.
The final output should include structured check results, a list of non-compliant doors, regulatory references, root causes, and remediation suggestions, presented through a web page.

## Constraints

### Architecture
- Hybrid AI architecture: combine LLM-driven regulation reasoning with a deterministic rule engine for compliance checking.
- Clear AI roles: the T3 LLM rewrites retrieval queries and judges only whether evidence is sufficient for actual clear-width and required clear-width calculation. Rule construction belongs to T4, while calculation, validation, comparison, and result output remain deterministic.
- Schema-driven design: use Pydantic to unify building entities, audit rules, and inspection result models.
- Configurable rule engine: execute configurable rule entries and avoid hard-coded compliance logic.
- Modular decoupling: keep BIM parsing, rule management, check logic, and AI interaction physically separated.

### Tech Stack
- IFC parsing: use IfcOpenShell to extract structured BIM element information accurately.
- Lightweight dependencies: prefer mature, lightweight libraries (such as IfcOpenShell, Pydantic, FastAPI) to ensure reproducibility and reduce complexity.

### Must Not

- Avoid introducing non-essential libraries. Prefer mature, lightweight dependencies to ensure reproducibility and reduce complexity.
- Limit changes strictly to modules related to the BIM compliance review workflow. Avoid modifying unrelated modules or unnecessary refactoring to maintain code stability and maintainability.
- Do not install new dependencies without approval.

### Out of Scope

- Scope limit: this prototype focuses only on evacuation door clear-width compliance checks and does not cover the full BIM review workflow.
- IFC limit: only extract the necessary IFC entities and attributes; comprehensive BIM semantic analysis and geometric processing are out of scope.
- Rule limit: support only selected regulatory clauses and do not implement automated extraction for all building codes.
- Analysis limit: do not include advanced geometry analysis, simulation calculations, or BIM model modifications.
- Usage limit: this system provides only preliminary AI-assisted review and is not intended to replace professional construction drawing review.

## Current State

- `./src/schemas/bim.py` structured representation after IFC parsing
- `./src/schemas/rule.py` rule definitions derived from regulatory text
- `./src/schemas/result.py` inspection output
- `./src/schemas/assessment.py` LLM classification and derived assessment models
- `./src/ifc_parser.py` deterministic IFC door extraction with millimetre normalization
- `./src/ai/evacuation_door_classifier.py` schema-validated LLM classification boundary
- `./src/clear_width_resolver.py` deterministic clear-width resolution
- `./references/南京地方标准建筑工程施工图信息模型智能审查规范.pdf` regulatory reference
- `./test_sampe/` real IFC sample models used for parser and end-to-end verification
- Relevant files: `./spec.md` ， `./AGENTS.md` 

## Tasks

### T1: Define domain data models

What: define IFC model data, rule data, and inspection results
Files: `./src/schemas/bim.py`, `./src/schemas/rule.py`, `./src/schemas/result.py`
Verify: create sample objects and validate serialization/deserialization to ensure BIM data, rule data, and inspection results can be represented and transferred correctly according to the schema.

### T2: Implement IFC parsing module

What: extract evacuation door information from IFC files
Files: `src/ifc_parser.py`, `src/schemas/bim.py`
Verify: use all real IFC files from the project-root `./test_sampe/` directory
and confirm correct extraction of door ID, door type, overall width, overall
height, location, floor, host, opening, placement, and model-specific
`extra_info`. All linear values must be normalized to millimetres. The parser
must not interpret `IfcDoor.OverallWidth` as clear width, classify evacuation
doors, or modify test fixtures.

### T3: Implement iterative evidence retrieval and sufficiency judgment

What: retrieve and accumulate regulation evidence until the system can determine whether two independent evidence groups are sufficient: evidence for calculating the door's actual clear width and evidence for calculating the applicable required clear width. The T3 VLM may rewrite the next Chinese BM25 query and equivalent English dense query when evidence is insufficient. It must not classify threshold value types, extract regulation parameters, declare rule inputs, generate Python, calculate width values, or make a compliance judgment.

Files: `src/search/iterative/controller.py`, `src/search/iterative/models.py`, `src/search/iterative/service.py`, `src/search/iterative/building_evidence_cache.py`, `src/ai/multimodal_evidence.py`

Output: the accumulated evidence and query history, `actual_clear_width_calculation_ready`, `required_clear_width_calculation_ready`, and the real evidence IDs supporting each judgment. Every evidence item exposes `iter` for the retrieval round in which it first entered the pool. Each retrieval round contributes only its final Top 3 results. The terminal contract does not expose the controller's generated `found_evidence` conclusions. A successful T3 result requires both readiness values to be true; reaching `max_hops` first returns `insufficient_evidence`.

Verify: run Door 15600 through the real hybrid retrieval and ReACT loop. Confirm that incomplete evidence causes a new non-duplicate query, cited tables or images are supplied as original media, and the run finishes only when both evidence groups are sufficient. Confirm that the T3 output contains no extracted threshold, regulation parameter, generated Python, calculated width, or PASS/FAIL result. Confirm that a building evidence cache hit returns the same evidence and readiness judgments without another LLM or retrieval call.

### T4: Implement rule construction, clear-width computation and rule engine

What: consume only a sufficient T3 evidence bundle while keeping the current door's IFC facts separate from building-shared evidence. At the T4 service boundary, deterministically convert the current `IFCContext` into a minimal typed calculation context. For each target field, send the T3 initial query, that field's relevant current-door facts, and that field's assigned evidence to a multimodal VLM. For both `actual_clear_width_mm` and `required_clear_width_mm`, the VLM first decides whether the final current-door value is directly available: if so it returns `value_mm`; otherwise it returns one no-argument Python calculation. Actual-width context also exposes raw IFC `extra_info` so the MVP can recognize model-specific clear-width property names while still forbidding `OverallWidth` from being treated directly as clear width. Validate generated scripts structurally, execute only those scripts in isolated processes, and compare the two resolved millimetre values deterministically. The VLM must not make the PASS/FAIL decision. Within one IFC upload or batch, reuse a complete successful T4 result when the T3 evidence fingerprint and all configured calculation fields match. The reuse signature excludes `door_id` and, by product decision, `ifc_extra_info`; a hit skips the T4 VLM and script sandbox, then deterministically rebuilds `CheckResult` for the current door ID.

Files: `src/schemas/rule.py`, `src/rules/`, `src/rules/result_cache.py`, `src/rule_engine.py`, `src/schemas/result.py`

Verify: reject a T3 bundle when either readiness value is false or the executed initial query is unavailable. Assert that each VLM request contains `initial_query`, `target_field`, only the current-door facts needed by that target, assigned evidence IDs and the assigned evidence media/content. Confirm that the shared evidence bundle contains no per-door context. Verify direct-value responses for both fields and script responses for both fields; validate and isolate only script responses. Confirm that the deterministic comparator receives `2900 mm` and `700 mm` and returns PASS in the Door 15600 script case. Confirm that another door with the same T3 evidence and calculation fields hits the T4 cache without an LLM or sandbox call, receives its own `element_id`, and that changing any configured calculation field causes a miss while changing only `door_id` or `ifc_extra_info` does not. The broader acceptance matrix of at least 3 door types and 5 width combinations remains a later T4 acceptance task and is intentionally deferred.

### T5: Implement agent report generation

What: generate one evidence-grounded Chinese `detailed_reason` from a completed T4 result. The VLM receives the task and door ID, the converted current-door IFC calculation context, the authoritative T4 values/result, each field's resolution mode and generated script when present, and only the original T3 evidence IDs/media actually used by T4. It must explain the actual-width derivation, required-threshold derivation and fixed comparison result without recalculating, changing values, selecting another threshold, adding an independent clause or generating Markdown.
Files: `src/report_generator.py`, `prompt/report_generation.py`
Output: JSON containing T4's deterministic result mapped for presentation (`PASS` -> `合格`, `FAIL` -> `不合格`), the VLM-generated `detailed_reason`, and the real `evidence_ids` cited by that reason. The program performs the fixed mapping from `T4.check_result.result`; the VLM does not recalculate or author it.
Verify: reject incomplete or execution-error T4 results and any VLM citation outside T4's exact field provenance. Confirm that text evidence is sent as text, table/image evidence is sent as original media, the authoritative T4 values and result remain unchanged, and no Markdown field is produced.

### T6: Web demo integration

What: provide a complete user flow for IFC upload(s), check execution, and result table display
Files: `app/main.py`, `app/static` or `app/templates`
Verify: by uploading IFC model(s) and running the complete inspection flow, verify users can complete the end-to-end process from model input to automatic review result display; the results table should render successfully and the report should be downloadable.

## Validation

### End-to-end Verification
Run:
```bash
python -m src.main --ifc ./examples/sample.ifc
```

Expected after T1-T6 are complete:

- The command exits successfully after loading the sample IFC file.
- Structured door-check results include PASS/FAIL status and regulatory references.
- Non-compliant doors include issue causes and remediation suggestions.
- The web interface can display the results and download the generated report.

The current scaffold does not yet contain `src/main.py`; this verification becomes
executable when the end-to-end entry point is implemented.
