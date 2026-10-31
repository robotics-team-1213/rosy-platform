---
title: caplog on a uvicorn logger is empty in CI after a browser test builds uvicorn.Config, and the test PCs cannot see it
date: 2026-10-31
category: workflow-issues
module: operations/fleet/test
problem_type: workflow_issue
component: testing_framework
severity: medium
root_cause: test_isolation
resolution_type: test_fix
symptoms:
  - "GitHub CI: assert '\"input_tokens\": 100' in '' — caplog.text empty for a log written to 'uvicorn.error'"
  - "the same test passed in the previous publish PR and passes on every test PC and on a rerun of the landing"
  - "a CI job rerun fails the same way (the shard order is fixed)"
applies_when:
  - "a test reads caplog for a record logged through 'uvicorn', 'uvicorn.error' or 'uvicorn.access'"
  - "a test starts a live server with uvicorn.Config(...) or uvicorn.run(...) and no log_config=None"
  - "a test is green on the test PCs and red only in GitHub CI"
tags: [caplog, uvicorn, logging, propagate, pytest-version, ci-only, test-order]
---

# caplog on a uvicorn logger is empty in CI after a browser test builds uvicorn.Config, and the test PCs cannot see it

## Problem

Publish PR 223 failed `fleet-2of5` twice (job rerun included):
`test_fleet_checks_usage_binding_and_logs_no_original_text_or_identity[False-console|False-discord]` found no
`operator_inference`/`conversation_inference` line in `caplog.text`. The code logs through
`logging.getLogger('uvicorn.error')`. The test passed in PR 222, where it ran in another shard, and on the test PC.

## Root cause

Two facts together:

1. `uvicorn.Config(...)` applies uvicorn's default `LOGGING_CONFIG` when `log_config` is not `None`. That config sets the
   `uvicorn` logger to `propagate: False`, so records from `uvicorn.error` stop before the root logger. The first file
   in that shard, `operations/fleet/test/test_account_admin_browser.py`, builds such a live server.
2. CI runs Ubuntu's pytest 7.4.4 (`/usr/bin/python3`). Its `caplog` handler sits only on the root logger. The test PCs
   and this laptop run pytest 9.1, where `caplog.at_level(logger=...)` still received the record with propagation off.
   So no landing, however full, could reproduce it.

## Fix

The test attaches `caplog.handler` to `uvicorn.error` itself for the call and removes it afterwards
(`operations/fleet/test/test_assistant_preprocessing.py`). Verified in a venv with pytest 7.4.4: a plugin that only
builds `uvicorn.Config(app, log_level="error")` at configure time fails the old test in exactly the two CI cases and
passes the new one.

The 35 test files that build `uvicorn.Config` without `log_config=None` were left as they are; changing them was
outside the publish fix.

## Prevention

- A new live server in a test passes `log_config=None`, so it does not reconfigure process logging for later tests.
- A test that reads a uvicorn logger record attaches `caplog.handler` to that logger rather than relying on root
  propagation.
- To reproduce a CI-only logging failure locally, use pytest 7.4.4 and set up the earlier test's logging state in a
  `-p` plugin; the test PCs' pytest 9 hides this class.
