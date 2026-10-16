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
- D-775
- D-637
- D-655
plans:
- docs/plans/2026-10-11-mapless-fleet-control.md
---

Existing implementation holder; shared regression suite as registered in harness.yaml.

## 2026-10-17 · D-775 실측 교정 운영 연결

실측 수치 묶음의 목적별 승인·영속 저장·현재 촬영 session 확인·미리보기·철회 경로를 추가했다.
기존 tracking/sighting 승인과 World/CORE 권한은 유지한다. 원격 시험의 커밋·실행·실패 수정·skipped와
실측 근거의 한계는 [구현 검증 기록](../../../docs/validation/measured-camera-lifecycle-2026-10-16/result.md)에 모은다. 기존 모듈 gate의 물리 수용 범위를
넓히지 않는다. D-598의 현재 현장 readback·로봇별 오차 계수는 아직 확보하지 못했다.
