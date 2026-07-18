---
slug: architecture
title: System architecture
role: system architecture
updated: "2026-07-17T22:54:36"
---

# System architecture

## Overview

??? IFC ????????????????????????????????????? FAISS + BM25 ???????? RRF ???

## Compliance module graph

```mermaid
graph LR
  IFC["IFC files"] --> P["src/ifc_parser.py"]
  P --> D["Door facts in mm"]
  D --> F["src/extra_info_filter.py"]
  F --> L["src/ai/evacuation_door_classifier.py"]
  F --> W["src/clear_width_resolver.py"]
  L --> A["EvacuationDoorAssessment"]
  W --> A
  A --> E["Deterministic rule engine"]
  E --> O["PASS / FAIL / UNKNOWN"]
```

## Regulation retrieval graph

```mermaid
graph LR
  M["references/assets/indexes/*/*_metadata.jsonl"] --> BI["src/search/indexes/bm25.py"]
  M --> FI["Existing FAISS indexes"]
  BI --> B["src/search/retrievers/bm25.py"]
  FI --> V["src/search/retrievers/vector.py"]
  Q["query_builder + query_translator"] --> B
  Q --> V
  B --> H["src/search/retrievers/hybrid.py"]
  V --> H
  H --> R["Traceable SearchHit evidence"]
```

## Search package boundaries

- `tokenization`: ???????????
- `indexes`: ?? BM25/FAISS ????????????????
- `retrievers`: ?? BM25?????? RRF ???
- `cli`: ????????????????
- `SearchConfig` ?????????????
- metadata ????????????????????????

## Constraints

- IFC parsing extracts facts only and normalizes linear values to millimetres.
- `IfcDoor.OverallWidth` is overall door width, never clear width.
- The LLM may classify or translate semantic input, but deterministic width resolution, compliance checks and RRF fusion remain programmatic.
- Regulation retrieval returns evidence and never makes the final compliance decision.
