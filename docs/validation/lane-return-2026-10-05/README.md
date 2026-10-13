# D-468 local lane return source evidence

This is SOURCE evidence. No automatic-return command has been activated or field-tested.

## Decision and initial integration

- User accepted local-first recovery, sensor search fallback and Fleet-last escalation in D-468.
- Initial source commit `b91e3de37`; merged into local main at `6d2fda10d`.
- After the main merge: core policy/contract/bridge/schema 93 PASS and producer/keeper 62 PASS; each known-failures comparison 0 NEW. Harness/protocol checks 104 PASS, 21 existing warnings; lint 0 errors.
- Independent reviewer approved only unwired source building blocks (83 core and 62 producer tests, 0 NEW). This is not deployment or motion-activation approval.

## Actual-pose admission increment

The ROS odometry callback now feeds original frame/timestamp and validated quaternion to a measured-pose ledger. Camera containment is interpolated on its image timestamp and transformed into the latest body pose. Receipt time serves freshness only. Pose reset increments a continuity epoch, replay cannot refresh admission, unknown projection uncertainty and excessive extrapolation produce unknown corridor evidence.

New tests first failed because the module/adapter did not exist. Quaternion regressions reproduced three false admissions before finite/unit-norm validation was added. No issued twist is used to reconstruct this path. The manager exposes this evidence internally; command integration is still pending.

## Package-size judgment

The architecture guard detected a real growth regression missed by the initial narrow feature checks. Removing the unused schemas re-export restores that leaf file to 1315 lines. The new contract stays in its dedicated leaf module, directly imported by consumers.

Using the guard's own `_files`/`_lines` rules, independent reviewer measured core_features 13718 versus verdict baseline 13202. Delta 516: peer `command/bounded_trial.py` +22; D-468 `lane_return.py` 308, `lane_return_evidence.py` 138, `lane_return_wiring.py` 29, `manager.py` +9, `model.py` +10. Subsequent frame-type validation and removal of the invalid mixed-clock comparison yield final 13717, delta 515: peer +22 and D-468 +493. The final manager is 611 lines, within its existing recorded file allowance.

Independent verdict: accept/re-judge this aggregate because line-follow retains one owner, each new source is below 600 lines, pure policy and evidence admission are separate, the mixin keeps the manager lock, dependencies stay within line_follow/core_common, and there is no publisher, process or deployment unit. Creating another ROS package solely to reduce an aggregate count would add ownership and deployment without resolving coupling. The existing feature subpackages are already the structural split. File thresholds (600/800/1000), zero-growth rules and package +150 allowance remain unchanged. The prior verdict history is retained.

## Remaining proof

Actual command arbitration, observed support/uncertainty admission through that arbitration, verified swept-motion/floor clearance, signed release installation/readback and real departure recovery remain pending. The original incident lacks a complete synchronized trace; this work cannot establish its exact cause.

The first architecture regression run found a missing namespace dependency in the host environment; the rerun supplies the existing motion/skill package source paths. The combined evidence/bridge/legacy line-follow/bounded-trial/architecture check then passed 109 tests, 0 NEW. That run is host source verification, not ROS or field proof. A pinned read-only device SSH probe timed out; no device state change or installed-readback proof was obtained.

## Local fallback closed loop increment

The controller now counts distinct original camera stamps and invalidates a previous return reference on continuity-epoch changes. The current-corridor candidate approaches at at most 0.03 m/s, respects lower live limits, and measures its own accumulated travel and yaw. It ends after 0.15 m, 1.4 rad or 8 s; stationary translation ends that candidate after 1 s. The overall local sequence remains bounded at 12 s.

A continuous steering disturbance reproduced a real policy failure: refreshing the checkpoint at every contained pose left the frozen target only 2 mm behind a boundary invasion, inside the 8 mm waypoint tolerance. A normal checkpoint now requires 25 mm body margin and heading error at most 0.12 rad. The closed loop then retraces the measured path and reacquires the heading before verifying containment on three distinct source frames.

Host results: 30 controller/closed-loop tests pass, including 20 percent slip, nonmoving wheels, stale proof, normal checkpoint retention and both search directions before Fleet. The broader controller/evidence/odometry/legacy/architecture/contract run passes 130 tests with 0 NEW after merging current main. Logs are under `X:/DevTemp/lane-return-20261005/` (`policy-review-fixed.txt`, `approach-merged.txt`). Initial collection-path mistakes ran no tests and are not counted as verification. All output commands move only synthetic planar poses in these tests; the physical robot has received no motion from this increment.

Independent review approved this source increment after 45 PASS, 0 NEW (`X:/DevTemp/lane-return-review/tests-controller-final.txt`). The review found a second checkpoint write in the recovery-success branch that lacked the 25 mm guard; its regression now permits recovery at 20 mm but leaves the normal checkpoint unset until the stricter margin is reached. Review approval covers source only.

Read-only device access recovered. CORE, I/O, camera and Host Agent services are active on installed release `2026.10.05-042`; boot readback reports MANUAL/IDLE. These service/status observations do not prove live lane-return capability, sensor freshness or field recovery. No release or motion was changed.

## Manager arbitration increment

The real LineFollowManager now selects the D-468 proposal before ordinary following/D-407 for opted-in CAMERA_LINE with typed containment. A departure inhibits the ordinary forward proposal. A qualified internal motion provider is queried for floor validity, straight candidates, both turn directions and the final actual curved candidate. It is checked again when submitting a moving recovery decision. Source pose mutation/invalidation increments the existing evidence revision. No new publisher, command protocol or public mode is introduced.

Independent review reproduced an expired human lease accepted without a new tick and a Fleet RESUME that immediately reopened a new stuck. Submission now rechecks live authority, finite strictly positive caps, pose age and motion proof. Accepted RESUME resets the local timers/candidates and requires three distinct contained frames before normal following. A further pure-turn regression ensures reducing the linear ceiling to zero revokes rotation too. The manager closed loop uses synthetic poses and an explicitly fake provider; no fake permission is bound on the robot.

The initial broad host run passed 163 tests but failed the aggregate package-size guard at 13899. That is a real new failure, even though the known-failures script did not recognize the Windows traceback path and printed 0 NEW. Independent final structural acceptance measured 13933: +216 from 13717 is policy+37, new approach51, arbitration112, wiring+9, manager+5 and stuck wiring+2. Policy346, approach51, evidence138, arbitration112 and wiring39 retain separate responsibilities inside line_follow; manager616 stays within its existing file verdict. The review accepts this existing feature owner and one lock/final CORE route rather than creating another package or process. All file thresholds and the +150 re-review allowance remain unchanged; the exact aggregate verdict is refreshed.

Final independent source approval: 50 policy/manager/loop tests PASS, 0 NEW (`X:/DevTemp/lane-return-review/tests-manager-final-approved.txt`). The supplied motion proof in these tests remains fake and has no operational authority.

After merging current main, controller/manager/source evidence/odometry/legacy line-follow/stuck/IR guard/bounded-trial/architecture/contract checks passed 174 tests with 0 NEW (`X:/DevTemp/lane-return-20261005/manager-merged-final.txt`). Harness lint has 0 errors and 21 existing verification-freshness warnings. These host results restore the actual package guard; the earlier failed run is retained above and is not counted as passing evidence.

Runtime floor/swept-space provider, signed release/readback and physical recovery remain pending. The fallback seam defaults to no moving permission until that provider is connected.

## Positive current floor observation

The existing cliff classifier deliberately reports false for two saturated IR channels. A new internal floor_observed bit starts false and requires three valid raw channels, at least two nonsaturated channels, fresh enabled IR and no classified cliff/tilt/pickup. It is produced by the sensor-only worker and passed through the existing policy lease. It records current observation, not a guarantee about future swept floor or a measured camera/IR calibration acceptance.

The local-return sensor query preserves existing candidate restrictions and requires the exact unchanged candidate and reason allow. Off/shadow/closed adapters, missing streams, callback failures and nonboolean results deny it. Positive floor snapshots add LiDAR/IMU/IR to the original observation deadline calculation even if the configured required set was smaller. A pure producer reproduced stale IMU/LiDAR surviving an IR-only lease; dependency closure fixes that false admission.

Host perception floor/gate/handoff/provider checks: 47 PASS, 0 NEW. Adapter/legacy/architecture checks: 105 PASS, 0 NEW. Independent review: 105 PASS, 0 NEW (`X:/DevTemp/lane-return-review/tests-floor-final-independent.txt`). No size thresholds changed. Runtime motion binding still awaits signed swept-space and floor-path verification; no motor command or release was activated.
