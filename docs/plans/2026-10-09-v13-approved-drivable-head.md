# V13 Approved Drivable Head Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Train a frozen lane model's drivable head only from current human-approved indexed review, and retain verifiable parent and dataset lineage before any model can reach intake or driving.

**Architecture:** Reuse `IndexedReview.open/check` as the authority boundary in `train_job.py`; the existing `drivable_head.py` supplies the frozen model and head. Keep v13 artifacts as candidates until their parent ONNX/TorchScript equivalence, immutable review snapshot, replay thresholds, and field safety gates are verified. `intake.py` and `deliver.py` continue rejecting direct v13 admission.

**Tech Stack:** Python, PyTorch, ONNX, pytest, D-464/D-475/D-532.

---

### Diagnostic decision before driving integration

The current 10/7 candidate marks more than half the lower image drivable on all 96 STOP frames. A drivable fraction therefore cannot grant steering. D-520 curve SIM still exceeds its radial error gate; the frozen head cannot alter its parent lane argmax or choose which side of a circle/spoke is the route boundary. Keep these as separate hypotheses:

1. **Pixels:** On identical recorded SIM frames, compare map/ground-truth projected paint, current threshold paint, and frozen lane-model paint. Record point coverage and wall/spoke false positives. Projection is a SIM oracle, not real-camera truth.
2. **Geometry:** Feed each paint source into the same fixed-radius outer-circle fit with GT pose, then repeat with odometry pose. Record outer-boundary ID, residual, radial/heading error, and invalid/HOLD count. If even oracle+GT fails, fix association/fit; if oracle succeeds but model fails, improve paint perception; if GT succeeds and odometry fails, fix localization/entry.
3. **Real video:** Use only human-approved 10/6–10/7 same-boundary IDs and visible-floor/unknown masks for flicker, consecutive miss, corridor-target error, wall/junction negatives and STOP delay. D-475 separates the evaluation-only reviewed `255` path from D-464's training-mask rejection; verify the sealed evaluation companion and actual approved pixels before scoring occlusions.

No outcome above turns a drivable mask into motion authority. CORE retains final `cmd_vel` and uncertain boundaries STOP.

---

### Task 1: Make the v13 manifest lineage mandatory

**Files:** `learning/training/perception/training/export_cell.py`, `middleware/perception/control/sensing/perception/learned/manifest.py`, `learning/training/perception/test/test_training_contract.py`, plus v13 fixtures in `test_model_intake.py` and `test_model_deliver.py`.

1. Add a failing test: a v13 export without parent revision/hash or a 64-hex dataset revision is refused; a valid export preserves these fields; the robot loader refuses deletion or corruption.
2. Run the focused contract test and observe failure.
3. Require `parent_lane_model` `{model_revision, onnx_sha256}` and a 64-hex dataset revision only for v13. Validate ordered output has one appended drivable channel; preserve legacy lane-seg behavior.
4. Run focused contract/intake/delivery tests, compare known failures, commit exact files.

### Task 2: Bind a parent model to trusted admission

**Files:** `learning/training/perception/training/train_job.py`, `learning/training/perception/training/review_admission.py` only if its existing file binding cannot cover parent artifacts, `learning/training/perception/test/test_review_admission.py`.

1. Add failing tests that a v13 recipe cannot run outside `IndexedReview`, cannot use an unaccepted CameraProfile, and cannot continue after parent manifest/ONNX/TorchScript or review authority changes.
2. Run focused test and observe failure.
3. Validate parent manifest and hashes before GPU, bind all parent files to admission rechecks, and include hashes in job inputs and run record. Verify parent TorchScript and delivered ONNX output equivalence on fixed inputs.
4. Run focused tests, compare known failures, commit exact files.

### Task 3: Train and export a candidate only

**Files:** `learning/training/perception/training/train_job.py`, `learning/training/perception/training/learning_cycle.py`, `learning/training/perception/test/test_training_job.py`, `learning/training/perception/test/test_learning_cycle.py`, training README.

1. Add failing tests for frozen lane weights, ignored pixels, positive/negative drivable data, parent logit parity, and candidate state distinct from READY.
2. Run tests and observe failure.
3. Call `drivable_head.load_frozen_lane/train_head`, export v13 with lineage, and write a candidate receipt; leave intake and delivery guards closed. `learning_cycle` must report candidate rather than ready.
4. Run GPU and ROS-free focused tests on model PC, compare known failures, commit exact files.

### Task 4: Earn release and driving eligibility separately

**Files:** D-356/D-373 gates and focused tests, plus field validation records after human review exists.

1. Human reviewer approves same-boundary IDs, occlusion, reappearance and 255-ignore on 10/6 and 10/7 video. Freeze session-disjoint evaluation truth.
2. Evaluate lane and drivable IoU, flicker, consecutive miss, latency, parent lane parity, and uncertainty STOP on straight/curve/one-side-loss/wall/junction.
3. Only after evidence passes, implement the explicit intake release gate; keep CORE the sole final `cmd_vel` publisher.
4. Verify replay, SIM and physical robot separately. Do not report driving acceptance from host pytest or shadow inference.
