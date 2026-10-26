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

## Smooth motion and scenarios (later the same day)

Candidates `a4168ad085` (smooth travel and eased lines) and `ef7c1e50c3` (scenarios). The chunk plan now aims at the box pose the observer reports instead of the recipe's fixed pose, the way the real pipeline aims at the box the top camera locates.

| Run | Box | Grasp yaw | Result |
|---|---|---|---|
| smooth | nominal | site | **PASS**: xy 0.26 mm, lift 102 mm; phases 115 / 34 / 157 / 107 s |
| `pick-place-chunks-offset` | moved 12 mm, −8 mm | site | **PASS**: xy 0.26 mm |
| `pick-place-chunks-yaw-site` | turned 20° | site (not turned) | **FAIL** in grasp: `bounded_readback_step_limit`, the jaws closing 20° off the box's edges stopped on its corners |
| `pick-place-chunks-yaw-box` | turned 20° | turned by the box's true 20° | **PASS**: xy 0.10 mm |

The sim teacher dispatches each short target on its own clock, so the smoother speed profile does not show in phase times. These runs check geometry and success only. The yaw pair shows that turning the jaws with the box is right when the box's yaw is known. The real failure on 2026-10-25 came from a rough top-camera yaw (25° read from a ~30 px box), not from turning as such. That is why the real pipeline keeps the site yaw, caps the turn at 10° until the wrist view is learned, and lets outcomes decide (`cell_choices`). A wrist-camera edge yaw measured right above the box is the candidate that could lift the cap.
