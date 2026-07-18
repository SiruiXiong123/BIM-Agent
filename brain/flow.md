---
slug: flow
title: Key flows
role: key flows
updated: "2026-07-17T22:54:36"
---

# Key flows

## Compliance flow

```mermaid
sequenceDiagram
  participant U as User
  participant P as IFC parser
  participant A as AI classifier
  participant E as Deterministic evaluator
  U->>P: IFC model
  P->>A: filtered door facts
  A->>E: evacuation classification
  P->>E: width evidence in mm
  E-->>U: PASS / FAIL / UNKNOWN
```

## Regulation retrieval flow

```mermaid
sequenceDiagram
  participant Q as Query builder
  participant T as Query translator
  participant B as BM25 retriever
  participant V as FAISS retriever
  participant H as RRF fusion
  Q->>T: Structured original-language request
  T-->>Q: Chinese semantic request with stable limits
  Q->>B: query_text
  Q->>V: query_text
  B->>H: keyword-ranked evidence
  V->>H: semantic-ranked evidence
  H-->>Q: traceable fused SearchHit list
```

BM25 uses existing text, table and image metadata under `references/assets/indexes`; table and image `content`/`summary` fields are indexed without modifying the original assets.
