---
module: fleet_decision
owner: fleet_decision
last_verified:
  commit: 8036d90c09
  date: 2026-10-12
gates:
  SOURCE:
    state: GO
    cmd: python tools/harness/rosy_harness.py lint
    evidence: D-640 independent source review and remote integration 210 passed NEW0; docs/validation/decision-deliberation-2026-10-12/result.md. Live provider activation remains HOLD.
  LOCAL:
    state: GO
    cmd: python tools/remote/remote_pytest.py --log-dir X:/DevTemp/d637-check -- test/test_remaining_platform_installed.py -q
    evidence: D-640 installed wheel/sdist imports and remote integration 210 passed NEW0; docs/validation/decision-deliberation-2026-10-12/result.md. Fake providers only.
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
---

Existing implementation holder; shared regression suite as registered in harness.yaml.
