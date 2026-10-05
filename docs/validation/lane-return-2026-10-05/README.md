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

Actual command arbitration, observed support/uncertainty admission in the moving controller, verified swept-motion/floor clearance, no-checkpoint approach, closed-loop scenarios, signed release installation/readback and real departure recovery remain pending. The original incident lacks a complete synchronized trace; this work cannot establish its exact cause.

The first architecture regression run found a missing namespace dependency in the host environment; the rerun supplies the existing motion/skill package source paths. The combined evidence/bridge/legacy line-follow/bounded-trial/architecture check then passed 109 tests, 0 NEW. That run is host source verification, not ROS or field proof. A pinned read-only device SSH probe timed out; no device state change or installed-readback proof was obtained.
