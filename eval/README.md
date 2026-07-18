# Evaluation IFC fixtures

## `primary_school_door_width_eval.ifc`

Synthetic clear-width failure fixture derived from:

`test_sampe/00 - Primary school project (IFC).ifc`

Only two `IfcDoor.OverallWidth` attributes differ from the source model:

| Door | Source value | Evaluation value | Parsed evaluation value |
| --- | ---: | ---: | ---: |
| Door 2610 | 1.2 m | 0.7 m | 700 mm |
| Door 43970 | 1.2 m | 0.6 m | 600 mm |

The original IFC geometry and all other IFC entities are unchanged. The
evaluation fixture keeps the original 57 `IfcDoor` entities and IFC4 schema.

- Source SHA-256: `81bf3569ee2e57d7ee42394ec35fd33f84c8e4cf95f6ffd468803893efec3136`
- Evaluation SHA-256: `3bca9c0b708d20859e90fed0ccd0559cd9fa0d45a97f0fdffc3a65064d1e2859`
