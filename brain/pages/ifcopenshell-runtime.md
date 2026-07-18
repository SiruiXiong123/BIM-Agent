---
id: ifcopenshell-runtime
title: IfcOpenShell runtime dependency
category: decision
status: active
tags: [ifc, dependency, runtime]
created: "2026-07-17T12:38:41"
updated: "2026-07-17T14:43:21"
---

## compiled_truth

- The project Python environment `C:\Application\Anaconda\envs\llm_env\python.exe` uses IfcOpenShell 0.8.5 for deterministic IFC parsing.
- Installation was explicitly approved by the user for T2.
- The runtime successfully parses all three read-only fixtures in `./test_sampe/`: IFC4 school (57 doors), IFC2X3 office (9 doors), and IFC2X3 duplex (14 doors).
- T2 supports both observed schemas and metre/millimetre source units while normalizing all linear outputs to millimetres.
- Parsing must never modify fixtures, classify evacuation doors, or treat OverallWidth as clear width.


## timeline

- time: 2026-07-17T12:38:41
  kind: decision
  summary: "Created this page: IfcOpenShell runtime dependency"
  source: User-approved T2 dependency installation
  affects: [ifcopenshell-runtime]

- time: 2026-07-17T12:38:41
  kind: decision
  summary: Recorded the approved parser dependency and real-fixture compatibility evidence
  source: pip installation and IFC smoke test
  affects: [ifcopenshell-runtime]

- time: 2026-07-17T14:34:19
  kind: decision
  summary: Updated runtime evidence for all three fixtures and millimetre normalization
  source: src/ifc_parser.py integration tests
  affects: [ifcopenshell-runtime]

- time: 2026-07-17T14:43:21
  kind: decision
  summary: "IFC parser results may be exported as UTF-8 JSONL with one metadata record followed by one record per door; the primary-school fixture produces 58 lines"
  source: src/ifc_parser.py and tests/test_ifc_parser.py
  affects: [ifc-parser, reporting]
