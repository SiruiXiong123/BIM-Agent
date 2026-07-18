---
id: github-publication-boundary
title: "GitHub 公开发布边界"
category: decision
status: active
tags: [github, release, git-lfs]
created: "2026-07-19T01:36:18"
updated: "2026-07-19T01:41:30"
---

## compiled_truth

- The public repository is `https://github.com/SiruiXiong123/BIM-Agent`; the default branch is `main`.
- Public release scope includes application code, README, tests, examples, `eval/primary_school_door_width_eval.ifc`, and all `references/` indexes, metadata, table images, source images, and the two regulation PDFs required by offline retrieval.
- `*.ifc` and `*.pdf` are tracked by Git LFS through the committed `.gitattributes`; fresh clones must run `git lfs pull`.
- `.env`, runtime caches, temporary downloads, index cleanup backups, real-project IFC fixtures under `test_sampe/`, and the nested `brain-standard-source/` repository remain excluded.
- Run `python -m src.main --check` before `python -m src.main` to validate indexes, media, model manifests, and the eval fixture.
- On 2026-07-19, the repository owner explicitly confirmed that the two regulation PDFs and their derived table/image materials may be publicly uploaded and redistributed in this repository.


## timeline

- time: 2026-07-19T01:36:18
  kind: decision
  summary: "Created this page: GitHub 公开发布边界"
  source: 2026-07-19 GitHub publication
  affects: [github-publication-boundary]

- time: 2026-07-19T01:36:18
  kind: decision
  summary: "记录公开仓库、LFS 资产范围与禁止发布的本地数据"
  source: commit 25706274495839ac19fffcac76bff0017bb0321d
  affects: [github-publication-boundary]

- time: 2026-07-19T01:41:30
  kind: decision
  summary: Record owner confirmation that regulation PDFs and derived media may be public
  source: User confirmation on 2026-07-19
  affects: [github-publication-boundary]
