---
module: omx_agent
logical_modules: []
owner: OMX workcell
last_verified: { commit: "uncommitted", date: 2026-10-27 }
gates:
  SOURCE:
    state: GO
    evidence: "Registered as a harness module 2026-10-27 (concern: control wheel). test/test_platform_workcell_coordinator.py test/test_platform_owner_barriers.py: 44 passed, 0 skipped on the remote test PC at main 908c8a00f8 plus the registration change."
    cmd: 'python tools/remote/remote_pytest.py --log-dir "${ROSY_SCRATCH:-${TMPDIR:-/tmp}}/omx_agent" -- test/test_platform_workcell_coordinator.py test/test_platform_owner_barriers.py -q'
  LOCAL:
    state: PARKED
  ROS-SIM:
    state: PARKED
  ARTIFACT:
    state: PARKED
  DEVICE:
    state: PARKED
  FIELD:
    state: PARKED
adrs: [D-61, D-168, D-427]
plans: []
---
