---
title: A contract-version bump is three pins, not one
date: 2026-09-30
category: workflow-issues
module: core_api_web
problem_type: workflow_issue
component: development_workflow
severity: major
applies_when:
  - "bumping the API Reference MINOR version (PRT-006) after an additive change"
  - "touching docs/reference/ROSY API & Protocol Reference.md's **Version:** header"
  - "adding an API surface that lands as a new changelog row"
symptoms:
  - "test_app_description_names_the_live_contract_version fails after a doc bump"
  - "test_api_reference_documents_line_follow_endpoints_and_snapshot fails with 'API Ref header version moved'"
  - "the pre-push fast gate rejects a push whose real work was already correct"
root_cause: split_verification_surface
resolution_type: checklist
related_components:
  - documentation
  - testing_framework
  - release_gates
tags:
  - version-pins
  - api-contract
  - d-18
  - pre-push-gate
  - same-change-unit
---

# A contract-version bump is three pins, not one

> **Track: knowledge.** The version string that names the live contract lives
> in three places, and a bump session that touches only the document ships a
> red gate. This happened three bumps in a row (v1.57, v1.59, v1.60,
> 2026-09-23..30) before this note existed.

## The invariant

D-347 fixed the pin set: when `docs/reference/ROSY API & Protocol
Reference.md` gains a MINOR, the same change must move

1. the reference header (`**Version:** vN.NN`),
2. `core_api_web/api/app.py` — both the module docstring and the FastAPI
   `description=` (guarded by `test_protocol_version_alignment.py`), and
3. the literal in `test_line_follow_contract_docs.py` (a deliberate tripwire
   so a silent version freeze fails: it pins the header itself).

One bump, one commit, three pins. The tests are the net: the pre-push fast
gate runs them, which is how the v1.60 miss died at push time instead of
turning `main` red.

## Why sessions keep missing it

The bump usually happens at the end of an API-surface session, as a
documentation tail. The author's attention is on the endpoint they added,
not on the two code-level mirrors of a number they just changed. The
checklist is easy to know and easy to skip — which is why the gate, not the
memory, is the control.

## Procedure

Before committing an API Reference MINOR bump, run the two tripwires:

```
python -m pytest src/runtime/gateway/test/test_protocol_version_alignment.py \
  test/test_line_follow_contract_docs.py -q
```

Green means the three pins agree. If only these two fail after a doc bump,
the fix is mechanical: update `app.py` (docstring + description) and the
line-follow literal to the new version. Do not "fix" them by reverting the
header — the header is the source the tests read.

## Related

- D-18 (schemas + reference move together), D-347 (the three-pin rule),
  PRT-006 (additive = MINOR).
- The hook that caught it: `tools/hooks/` pre-push fast gate (D-346).
