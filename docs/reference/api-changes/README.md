# API change fragments (D-1061)

This file is also the records cutover marker: lint enforces fragments for PRs whose first own commit is
newer than the main commit that added this file (`tools/harness/records_rules.py`).

A PR that changes the API does not edit the reference `**Version:**` header, the `### v1.N` sections
under it, the `| v1.N |` history rows or `CONTRACT` in
`middleware/core/api/core_api_web/api/contract_version.py`. It adds one file here instead:

```
python tools/new_record.py api --surface core --slug docking-diag-fields \
    --title "도킹 상태 진단 필드" --history "Additive: GET /docking/status 의 last_event" \
    --body-file body.md
python tools/new_record.py api --kind breaking --reason "옛 필드 제거, 소비자 없음(사용자 결정)" \
    --surface fleet --slug drop-legacy-field --title "옛 필드 제거"
```

File `docs/reference/api-changes/<slug>.md` (no number in the name):

```
---
surface: core          # fleet | core | cell
kind: additive         # additive | breaking
slug: docking-diag-fields   # equals the file name
date: 2026-11-21       # first sort key for numbering, then slug
title: 도킹 상태 진단 필드
history: Additive: GET /docking/status 의 last_event   # optional, default title
reason: ...            # required when kind is breaking
---
Section body markdown. Write (v1.next) where the assigned version belongs.
```

The records bot (`.github/workflows/refresh-generated-docs.yml` → `python tools/new_record.py consolidate`,
one run at a time) numbers the fragments in (date, slug) order from the current header, writes
`### v1.N <title> (<Surface>[, breaking])` sections newest first, the history rows
`| v1.N | <day> | [<Surface>[, breaking]] <history> |`, the header and `CONTRACT` in one PR, and deletes
the fragments. A breaking section starts with `**Breaking.** 사유: <reason>`. Body text in the reference
(endpoint tables, §8 events) is still edited in the PR itself.
