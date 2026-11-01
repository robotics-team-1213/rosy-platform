---
module: isaac_sim
owner: sim
last_verified: { commit: "bb39f438a5", date: 2026-10-30 }
gates:
  SOURCE:
    state: GO
    cmd: "python tools/remote/remote_pytest.py --log-dir X:/DevTemp/isaac-source -- learning/envs/isaac/test"
    evidence: "bb39f438a5 remote Isaac596tests594passed2skip0fail; remote_isaac/admission160passed. Actual CAD13205531 Stage1 workcell. Run2cdbdd56df3851aeb9ff2701e2014bdd SUCCEEDED: nine90x30x30mm containers packed3x3x3 with D-929 row gaps (target3.5mm, measured3.22-4.00mm, band2-5mm, envelope90x97x90mm), arms0/1, physical tabletop leveling/regrasp, original support/position/stability limits with speed taken from the pose change per0.1s sample (Isaac instantaneous cargo velocity is solver chatter, run b326). SDKexit0/import/video11674frames/owned shutdown/GPU return confirmed; hashes in docs/validation/omx-cube-stacking-2026-10-29/result.md. Earlier: column42 3x1x3 run8858 accepted at4f63cd5992. Single seed42 nominal IK-reference only: offset/reverse, varied infeed, ACT/RL, hardware and field acceptance are not established. SOURCE GO does not change separate ROS-SIM/HIL gates."
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
