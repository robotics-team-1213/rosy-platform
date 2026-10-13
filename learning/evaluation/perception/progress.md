---
module: perception_evaluation
owner: perception_evaluation
last_verified:
  commit: 0b14fa02b0
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
- D-666
- D-667
- D-665
- D-637
- D-662
---

Existing implementation holder; shared regression suite as registered in harness.yaml.

D-666/D-667 paired replay and shared observation contracts: offline CLI emits diagnostic HOLD, never model admission. Immutable approvals, paired source images, declared training source/image disjointness and pre/post content checks are implemented. Real independent truth, physical calibration, upstream closure, acceptance profile and device evidence remain HOLD.

D-662 Pinky judgment checker: remote 8 synthetic cases plus 3 installed-delivery checks passed, NEW0. Required abstention and duplicate physical windows independently reviewed. Team labels/profile limits, actual notifications and FIELD receipts remain HOLD; PASS_OFFLINE_ONLY never activates a model.
