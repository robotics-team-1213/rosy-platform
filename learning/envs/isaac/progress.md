---
module: isaac_sim
owner: sim
last_verified: { commit: "a759f1e6f", date: 2026-10-11 }
gates:
  SOURCE:
    state: GO
    cmd: "python tools/remote/remote_pytest.py --log-dir X:/DevTemp/isaac-source -- learning/envs/isaac/test"
    evidence: "Latest main holder paths retained; SDK importer/headless/force-drive regression tests pass. Runtime source a759f1e6f includes main ea6d4c0a2."
  LOCAL:
    state: GO
    cmd: "python tools/remote/remote_pytest.py --log-dir X:/DevTemp/isaac-core -- learning/envs/isaac/test middleware/core/gateway/test middleware/core/services/test test/test_structure_installed_packages.py"
    evidence: "a759f1e6f remote: 4361 passed, 11 skipped, 0 NEW. Separate Jazzy render/preflight verified Pinky 17 joints/10 meshes."
  ROS-SIM:
    state: HOLD
    blocker: "Latest-main source a759f1e6f verified before/after headless 2400-frame run; SDK exit 0 without SDK Error/Traceback. Single CORE publisher, forward tracking, command-expiry physical stop and owned CORE-loss watchdog stop observed. Rotation target 0.3 rad/s measured 0.19396: tracking failed, observer/scenario exit 1. Map/STL, sensors, Nav2, two-robot Fleet and RL remain unverified; see docs/validation/isaac-latest-core-main-2026-10-11/result.md."
  ARTIFACT: { state: N/A }
  DEVICE: { state: N/A }
  FIELD: { state: N/A }
adrs: [D-322, D-434]
plans:
  - docs/plans/2026-10-04-isaac-navigation-integration-review.md
---
## 2026-09-30 initial marker

Package marker landed so the D-168 structure scan sees `src/sim/isaac_sim`. Host tests exist and run (D-322 검증 절: URI·namespace·초기 wheel 계약); the earlier "no own tests" note here was wrong and is corrected in the same tree.
