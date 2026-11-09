---
title: A websocket receive with no timeout held a landing for 42 minutes
date: 2026-11-09
category: test-failures
module: middleware/core/gateway/test/test_account_pipeline.py
problem_type: test_failure
component: testing_framework
severity: high
symptoms:
  - "A remote pytest invocation runs far past its usual time with no new output"
  - "The same test passes alone on another host (10 passed, 2 skipped)"
root_cause: missing_timeout
resolution_type: test_fix
tags: [starlette, testclient, websocket, timeout, remote-pytest, landing]
---

# A websocket receive with no timeout held a landing for 42 minutes

## Symptom

On 2026-11-09 `test_login_callback_refresh_revoke_and_core_scope` sat 42 minutes on the model PC inside `ws.receive_json()`. The landing did not fail. It waited. Alone on another host the file passed.

## Cause

Starlette's `TestClient` websocket `receive_json()` blocks until the app sends something; it has no timeout. The test bounded its loop with `while time.monotonic() - started < 20`, but that check only runs between receives. When the server neither sent a frame nor closed, the first receive never returned. Remote runs had no per-test limit either: only `remote_job`'s whole-invocation `timeout` (5,400 s) would end it, as exit 124 without a test id.

## Fix

- The test waits for each receive in a worker thread with `result(timeout=<remaining window>)`. A missing close now fails in 20 s with `TimeoutError`. The assertions (close code 4401 within 15 s) are unchanged.
- Remote venvs install `pytest-timeout==2.4.0`, and `remote_job` exports `PYTEST_TIMEOUT=900`. A hung test fails with its id, so `known_failures.py` and the main-red record name it. `@pytest.mark.timeout(n)` or a leading `ROSY_PER_TEST_TIMEOUT=n` word changes the limit. A venv without the plugin ignores the variable.

## Verification

Remote run on the branch (`aff2bc4f71`): the rebuilt venv installed, the selected tier passed (2,522 passed, 0 new), and `--timeout=900` was accepted on the host (the flag errors when the plugin is missing).

## Apply next time

- A loop condition on the clock does not bound a blocking call inside it. Bound the call itself (`result(timeout=...)`, `asyncio.wait_for`, socket timeout).
- A test that passes alone and hangs under load is a hang to bound, not a flake to rerun.
- The first run after a venv recipe change rebuilds the venv on each host and misses the landing cache once; plan it outside a busy queue when possible.
