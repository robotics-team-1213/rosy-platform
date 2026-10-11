---
module: isaac_sim
owner: sim
last_verified: { commit: "e0e5b38d78", date: 2026-10-11 }
gates:
  SOURCE:
    state: GO
    cmd: "python tools/remote/remote_pytest.py --log-dir X:/DevTemp/isaac-source -- learning/envs/isaac/test"
    evidence: "CORE final port and existing Drive reused by D-638 native map diagnostic; e0e5b38d78 Isaac regression exit 0, 0 NEW. Runtime revisions and source hash readback are recorded separately in docs/validation/isaac-map-rl-2026-10-11/result.md."
  LOCAL:
    state: GO
    cmd: "python tools/remote/remote_pytest.py --log-dir X:/DevTemp/isaac-core -- learning/envs/isaac/test middleware/core/gateway/test middleware/core/services/test test/test_structure_installed_packages.py"
    evidence: "a759f1e6f full remote: 4361 passed, 11 skipped, 0 NEW. D-638 dc25401e61 relevant CORE/Drive/Isaac/harness regression exit 0, 0 NEW; e0e5b38d78 complete Isaac regression exit 0, 0 NEW. Jazzy URDF preflight remains separate."
  ROS-SIM:
    state: HOLD
    blocker: "Full ROS-SIM rotation tracking remains failed (0.3 target versus 0.19396 measured). D-638 native one-Pinky CPU Q-learning completed ordered 9.342m curved-map route at frozen eval seeds 202/303 with physical stop; this is not ROS/Fleet or Isaac Lab acceptance. dc25401e61 SDK exit 0 had one asynchronous menu shutdown traceback; e0e5b38d78 shutdown-only SDK probe fixed it, exit 0/error 0. Sensors/localization, Nav2, two-robot Fleet/signals and device acceptance remain unverified. See docs/validation/isaac-map-rl-2026-10-11/result.md."
  ARTIFACT: { state: N/A }
  DEVICE: { state: N/A }
  FIELD: { state: N/A }
adrs: [D-322, D-434, D-638]
plans:
  - docs/plans/2026-10-04-isaac-navigation-integration-review.md
  - docs/plans/2026-10-11-isaac-map-rl.md
---
## 2026-09-30 initial marker

Package marker landed so the D-168 structure scan sees `src/sim/isaac_sim`. Host tests exist and run (D-322 검증 절: URI·namespace·초기 wheel 계약); the earlier "no own tests" note here was wrong and is corrected in the same tree.
