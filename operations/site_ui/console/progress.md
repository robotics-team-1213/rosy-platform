---
module: console_source
owner: console_source
last_verified:
  commit: d4988bffba
  date: 2026-10-11
gates:
  SOURCE:
    state: GO
    cmd: python tools/harness/rosy_harness.py lint
    evidence: D-637 independent source review, committed remote regression and local main FF; see dated result.
  LOCAL:
    state: GO
    cmd: python tools/remote/remote_pytest.py --log-dir X:/DevTemp/d637-check -- test/test_remaining_platform_installed.py -q
    evidence: D-637 independent source review, committed remote regression and local main FF; see dated result.
  ROS-SIM:
    state: HOLD
    blocker: D-637 is source-only; no corresponding ROS-SIM, ARM64 artifact, deployment, device or field proof.
  ARTIFACT:
    state: HOLD
    blocker: D-637 is source-only; no corresponding ROS-SIM, ARM64 artifact, deployment, device or field proof.
  DEVICE:
    state: HOLD
    blocker: D-637 is source-only; no corresponding ROS-SIM, ARM64 artifact, deployment, device or field proof.
  FIELD:
    state: HOLD
    blocker: D-637 is source-only; no corresponding ROS-SIM, ARM64 artifact, deployment, device or field proof.
adrs:
- D-637
- D-655
plans:
- docs/plans/2026-10-11-mapless-fleet-control.md
---

Existing implementation holder; shared regression suite as registered in harness.yaml.

## 2026-10-16 충전 운행 주체 오류 안내

TRIP_OWNER_KIND_INVALID의 안내를 추가했다. 영향 Console Chromium 457개가 통과했으며 UI source는 이후 바뀌지 않았다. 혼합 실행에 포함된 비브라우저 label 검사 1개는 당시 parser 문제로 실패했고, 수정 후 39f94f151의 계약/회귀 486개에 포함되어 통과했다. 원 실행 종료 코드는 1이며 browser 결과와 구분한다. 운영 충전 화면 전체와 현장 수용을 뜻하지 않는다.
