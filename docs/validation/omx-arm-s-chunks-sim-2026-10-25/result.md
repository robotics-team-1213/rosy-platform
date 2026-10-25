# Arm S chunk plan in the native SIM — 2026-10-25

Experiment `pick-place-chunks` (D-872 §2.4): the native SIM teacher runs arm S's top-down chunks (`grasp_planner.py`: vertical descend, close with the arm still, vertical lift) and the rise-turn-descend travel (`chunk_runner.transit_path`) aimed at the sim cell's pick and place, in place of `plan_transfer`. Owner, short targets, readback, contact checks, attach/detach and `judge_episode` are unchanged (`sim_chunk_plan.py`). Frames move at the guard's teacher-mode speed (`GUARD_UNITS_PER_S`), so a cycle takes longer than the analytic plan.

Both runs: AI test host, approved isolated native SIM transport (`remote_omx_native.py deploy --host ai --experiment pick-place-chunks`, `start --approve-isolated-simulation --approve-startup-home`), one episode, no actor restarted, no hardware. Candidates were built on branch `feat/omx-arm-s-teacher-cell` while its landing waited in the queue.

| Run | Candidate | Result |
|---|---|---|
| 1 | `46456ab767` | FAIL `bounded_readback_step_no_progress` in release. Approach 113 s, grasp 34 s (contact, attach confirmed), transfer 155 s, detach confirmed (clearance 5.2 mm), then the first release target asked the jaws to close to 0.387 rad while the box held them at 0.420 rad |
| 2 | `bba0b7f43b` | **PASS**: one attempt, one success, cleanup verified. xy error 0.12 mm, z error < 0.001 mm, lift 102 mm, stable 2.25 s; approach 113 s, grasp 33 s, transfer 155 s, release 109 s; 2,060 RGB frames, capture issues none |

Fix between the runs: the release phase opens from the measured jaw position (`sim_chunk_plan.open_from`). The planned release starts at the width-matched close, which the box does not let the jaws reach; the analytic plan already opens from the hold. Test `test_the_release_opens_from_where_the_jaws_stopped_on_the_box` reproduces the run-1 values.

On the real arm this case does not stop the cell (the guard has no following-error bound on the current-limited gripper), but the same rule applies: a release opens from where the jaws are.

Not shown here: the real arm under the guard's teacher mode, real S cell coordinates (the sim cell is not the S cell), the B leg (belt → Pinky) and the decision seat. Evidence archives and receipts are kept outside the repository with the session scratch (`sim-chunks-2`, `sim-chunks-3`).
