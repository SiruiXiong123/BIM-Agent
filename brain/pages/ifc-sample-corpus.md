---
id: ifc-sample-corpus
title: Real IFC sample corpus
category: reference
status: active
tags: [ifc, testing, fixtures]
created: "2026-07-17T12:36:09"
updated: "2026-07-17T12:58:51"
---

## compiled_truth

- Real IFC fixtures live in the project-root `./test_sampe/` directory (the directory name intentionally retains its current spelling).
- The directory currently contains three `.ifc` models: `00 - Primary school project (IFC).ifc`, `20160414office_model_CV2_fordesign.ifc`, and `Duplex_A_with_fire_exit (1).ifc`.
- T2 parser verification and later end-to-end checks should cover all three models because together they exercise IFC2X3 and IFC4, metre and millimetre project units, `IfcDoorStyle` and `IfcDoorType`, present and absent space boundaries, vendor quantity sets, and explicit fire-exit classification.
- Treat these large binary fixtures as read-only test inputs; parsing and tests must not modify them.


## timeline

- time: 2026-07-17T12:36:09
  kind: decision
  summary: "Created this page: Real IFC sample corpus"
  source: project root test_sampe directory
  affects: [ifc-sample-corpus]

- time: 2026-07-17T12:36:09
  kind: decision
  summary: Recorded the location and handling rules for real IFC fixtures
  source: AGENTS.md and spec.md
  affects: [ifc-sample-corpus]

- time: 2026-07-17T12:46:07
  kind: evidence
  summary: "The IFC2X3 office fixture exposes 9 doors across Ground Floor and Levels 1-3, with type, host wall, space boundaries, nominal dimensions, and vendor Egress Width; fire-rating fields are present but empty"
  source: IfcOpenShell 0.8.5 read-only audit
  affects: [ifc-parser, door-schema]

- time: 2026-07-17T12:52:57
  kind: evidence
  summary: "The IFC4 school fixture has 57 doors, all with storey, host wall, IfcDoorType, operation, and nominal dimensions, but no IfcRelSpaceBoundary adjacency, no quantity sets, no explicit clear-width field, and no populated fire rating; project lengths are already metres"
  source: IfcOpenShell 0.8.5 read-only audit
  affects: [ifc-parser, door-schema]

- time: 2026-07-17T12:58:51
  kind: decision
  summary: Added the duplex fire-exit IFC fixture and expanded the cross-model coverage contract
  source: "test_sampe/Duplex_A_with_fire_exit (1).ifc"
  affects: [ifc-sample-corpus]

- time: 2026-07-17T12:58:51
  kind: evidence
  summary: "The duplex IFC2X3 fixture has 14 doors across Levels 1-2; all expose storey, unique space boundaries, host wall, IfcDoorStyle, operation, tag, dimensions, Revit properties, material fields, and explicit IsFireExit/IsExternal booleans, with 4 true fire exits"
  source: IfcOpenShell 0.8.5 read-only audit
  affects: [ifc-parser, door-schema]
