---
module: perception_curation
owner: perception_curation
last_verified:
  commit: d4988bffba
  date: 2026-10-11
gates:
  SOURCE:
    state: GO
    cmd: python tools/harness/rosy_harness.py lint
    evidence: D-637 independent source review, committed remote regression and local main FF; see dated result.
  LOCAL:
    state: GO
    cmd: python tools/remote/remote_pytest.py --log-dir X:/DevTemp/d637-check -- test/learning/perception/ -q
    evidence: D-637 independent source review, committed remote regression and local main FF; see dated result.
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
- D-663
- D-637
---

Existing implementation holder; shared regression suite as registered in harness.yaml.
