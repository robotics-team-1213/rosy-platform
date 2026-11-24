---
title: Site autoupdate deferred forever because /api/fleet/trips returns running=null when idle
date: 2026-11-24
category: runtime-errors
module: deploy/site/site_update_runtime.py
problem_type: runtime_error
component: testing_framework
symptoms:
  - "rosy-site-autoupdate logged deferred-busy with reasons=[\"cannot verify site idle state\"] on every run even when all robots and arms were idle"
  - "Signed site-* candidate releases stayed unapplied after rollout"
root_cause: test_fixture_drift
resolution_type: code_fix
severity: high
tags: [site, autoupdate, idle-gate, api-contract, fixtures]
applies_when: "writing fail-closed runtime health or idle gates that parse Fleet JSON endpoints alongside mocked HTTP test fixtures"
---

# Site autoupdate idle gate must accept Optional[dict] for /api/fleet/trips running

**What happened.** Live `rosy-site-autoupdate` runs deferred every signed candidate rollout with `"cannot verify site idle state"`, even while `state`, `trips`, `dispatch-control`, and `formation` all reported an idle site.

**Cause.** `GET /api/fleet/trips` (`operations/fleet/fleet/server/trips/trip_routes.py`) returns `{"running": runner.running(), "open": runner.open_trips(), "trips": runner.recent()}` where `runner.running()` is `Optional[dict]` (`None` when idle, a trip object `dict` when active). However, `deploy/site/site_update_runtime.py` required `isinstance(trips.get('running'), list)`, raising `ValueError('invalid trips payload')` on every real response. The test suite missed this because `test/test_site_autoupdate.py` and `test/test_site_autoupdate_idle.py` mocked `running: []` instead of `running: None` or a trip `dict`.

**Fix.**
- Updated `site_busy_reasons` in `deploy/site/site_update_runtime.py` to require `'running' in trips`, accept `None`, `dict`, or `list` for `running`, fail closed (`ValueError`) on any other type, and treat any `dict` (including `{}`) or non-empty `list` as busy.
- Aligned `FakeHttp.functional` in `test/test_site_autoupdate.py` to return `'running': None` by default and added fail-closed / busy cases in `test/test_site_autoupdate_idle.py` covering `running: dict`, `running: {}`, missing `running`, invalid type, and legacy `running: []`.

**Rule.** Test fakes for server HTTP endpoints must match the live FastAPI route response schema (`None` vs `dict` vs `list`) verified directly from the server serializer or route handler.
