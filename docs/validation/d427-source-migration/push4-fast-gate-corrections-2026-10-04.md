# D-427 integrated push4 fast gate corrections — 2026-10-04

Enforced push4 for 4e31b0619 stopped at the fast tier: 2 failed, 457 passed, 2 existing skips, 11 freshness warnings (92.03 s). No remote landing occurred. Failures were external behavior test ownership and the new Pinky binding name in the robot-literal guard.

Split U1 tests by ownership: service admission/expiry/stop/commit-race cases now live in middleware/core/services/test/test_manual_ownership.py and construct actual service components. Gateway cases keep the HTTP navigation/Fleet/swarm/line-follow admission scenario, enter MANUAL and teleop through real APIs, and establish host live-velocity evidence required by the existing write gate. The original frozen external behavior set is unchanged; imports were not hidden or routed through aliases.

D-442 explicitly requires PinkyTwistPort in the existing writer module. The robot-literal scan therefore exempts only that exact type name in cmd_vel.py, not the file or arbitrary robot configuration. Three regressions prove the exact class name is representable while DEFAULT_MODEL=pinky_pro and a pinky-containing revision remain forbidden. The internal stage-(b) revision marker is device-neutral command-manager-b-v1. No robot-literal backlog entry or known failure was added; writer behavior and admission rules are unchanged.

Focused existing ownership/literal guards plus split U1 and Pinky cases: **30 passed**, 2.37 s, flake8 zero findings. Log: X:/DevTemp/rosy-d427/resume/push4-corrections-green.txt. Initial literal guard remained RED until the revision marker was corrected. Actual API fixture setup initially failed because live-velocity evidence was absent; that prerequisite was added, and cancel observation begins after MANUAL setup so the test measures refusal side effects only.

Source/host corrections only. Final enforced candidate gate, CI, ARM64/SD/final Docker, release parity and device acceptance are still required. Earlier failed push4 is never relabeled green.

Independent reviewer /root/d427_safety_review: **APPROVE source/host corrections**. Installed-wheel literal/manual/Pinky subset **29 passed**, 3.26 s; exact token/path exception, unchanged backlog/frozen set, five service cases and five HTTP cases, unchanged execution authority and clean diff verified. Final enforced SHA gate remains separate.
