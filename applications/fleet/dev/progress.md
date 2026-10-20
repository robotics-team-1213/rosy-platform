---
module: fleet_app_dev
owner: fleet_app_dev
last_verified:
  commit: c000a57004
  date: 2026-10-21
gates:
  SOURCE:
    state: GO
    cmd: python tools/harness/rosy_harness.py lint
    evidence: D-830 source boundaries and independent review; cancellation and Cell overview follow-up in logs.md.
  LOCAL:
    state: GO
    cmd: python tools/remote/remote_pytest.py --log-dir private/frontend-browser -- ROSY_RUN_BROWSER_TESTS=1 applications/fleet/test
    evidence: f5aab6d2de combined app/browser/installed/CLI regression 264 passed; c000a57004 changed sample authority and representative browser flows 36 passed. Standard landing FULL remains separate.
  ROS-SIM:
    state: HOLD
    blocker: Frontend sample and fake robot transport do not prove simulation behavior.
  ARTIFACT:
    state: HOLD
    blocker: Operational Fleet package verification is recorded by console_source; no new device artifact.
  DEVICE:
    state: HOLD
    blocker: No device access or physical action acceptance performed.
  FIELD:
    state: HOLD
    blocker: No deployment or field acceptance performed.
adrs:
- D-830
plans:
- docs/plans/2026-10-21-fleet-frontend-separation.md
---

Loopback frontend development host: stdlib sample state and verified single-upstream HTTPS adapter. Production keeps the existing Fleet distribution.
