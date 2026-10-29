---
module: isaac_sim
owner: sim
last_verified: { commit: "5c89f3d1f3", date: 2026-10-29 }
gates:
  SOURCE:
    state: GO
    cmd: "python tools/remote/remote_pytest.py --log-dir X:/DevTemp/isaac-source -- learning/envs/isaac/test"
    evidence: "5c89f3d1f3 remote terminal/lift/retention/near-arm/reference regression:32 passed,0NEW. edbf49d6e0 broad checks:807 passed,1 skip,1 public-checksum entropy finding; metadata972f2ae2d1 fixed its integrity label and all80release-boundary checks then passed0NEW. Latest accepted runtime record c1786ef9d6/254a87c630f8581dbdc53a5218438a36 has SDKexit0 and confirmed owned cleanup but physicalFAILED on third-bar envelope. New bias physics is pending GPU admission. See docs/validation/omx-cube-stacking-2026-10-29/result.md. Source checks do not establish physical, learned-policy or hardware acceptance. Earlier CORE/Drive evidence remains in docs/validation/isaac-map-rl-2026-10-11/result.md."
  LOCAL:
    state: GO
    cmd: "python tools/remote/remote_pytest.py --log-dir X:/DevTemp/isaac-core -- learning/envs/isaac/test middleware/core/gateway/test middleware/core/services/test test/test_structure_installed_packages.py"
    evidence: "a759f1e6f full remote: 4361 passed, 11 skipped, 0 NEW. D-638 dc25401e61 relevant CORE/Drive/Isaac/harness regression and e0e5b38d78 Isaac regression exit 0, 0 NEW. b6a8d0d2e8 recording/restore and Drive/CORE cycle/harness regression exit 0, 0 NEW; 764b591ed6 placement/Isaac/architecture/release/harness remote regression exit 0, 0 NEW. Jazzy URDF preflight remains separate."
  ROS-SIM:
    state: HOLD
    blocker: "Full ROS-SIM rotation tracking remains failed (0.3 target versus 0.19396 measured). D-638 native one-Pinky CPU Q-learning completed ordered 9.342m curved-map route; R8 full post-shutdown-fix retraining at 57ad87993f had SDK exit 0/error 0. R9 b6a8d0d2e8 frozen evaluations at four initial headings completed with native Camera recordings and physical stop, SDK exit 0/error 0. These are not ROS/Fleet or Isaac Lab acceptance. Sensors/localization, Nav2, two-robot Fleet/signals and device acceptance remain unverified. See docs/validation/isaac-map-rl-2026-10-11/result.md."
  ARTIFACT: { state: N/A }
  DEVICE: { state: N/A }
  FIELD: { state: N/A }
adrs: [D-322, D-434, D-638, D-708]
plans:
  - docs/plans/2026-10-12-map-drive-diagnosis.md
  - docs/plans/2026-10-12-observed-path-gap-implementation.md
  - docs/plans/2026-10-04-isaac-navigation-integration-review.md
  - docs/plans/2026-10-11-isaac-map-rl.md
  - docs/plans/2026-10-11-isaac-direction-video.md
---
## 2026-09-30 initial marker

Package marker landed so the D-168 structure scan sees `src/sim/isaac_sim`. Host tests exist and run (D-322 검증 절: URI·namespace·초기 wheel 계약); the earlier "no own tests" note here was wrong and is corrected in the same tree.
