---
module: fleet_decision
owner: fleet_decision
last_verified:
  commit: 587c0b4c8c
  date: 2026-10-29
gates:
  SOURCE:
    state: GO
    cmd: python tools/harness/rosy_harness.py lint
    evidence: D-913 independent source review through 587c0b4c8c and remote candidate regressions NEW0; docs/validation/conditional-model-cooperation-2026-10-29/result.md. Live provider and GPU admission activation remain HOLD.
  LOCAL:
    state: GO
    cmd: python tools/remote/remote_pytest.py --log-dir <external-log-dir>/model-cooperation -- test/test_remaining_platform_installed.py -q
    evidence: D-913 remote wheel/sdist and source regression invocation passed at 587c0b4c8c, NEW0; docs/validation/conditional-model-cooperation-2026-10-29/result.md. Fake providers/admission only.
  ROS-SIM:
    state: HOLD
    blocker: D-637 is source-only; no corresponding ROS-SIM, ARM64 artifact, deployment, device or field proof.
  ARTIFACT:
    state: HOLD
    blocker: D-637 is source-only; no corresponding ROS-SIM, ARM64 artifact, deployment, device or field proof.
  DEVICE:
    state: HOLD
    blocker: D-637 is source-only; no corresponding ROS-SIM, ARM64 artifact, deployment, device or field proof.
  FIELD:
    state: HOLD
    blocker: D-637 is source-only; no corresponding ROS-SIM, ARM64 artifact, deployment, device or field proof.
adrs:
- D-637
- D-640
- D-679
- D-681
- D-684
- D-913
---

Existing implementation holder; shared regression suite as registered in harness.yaml.
