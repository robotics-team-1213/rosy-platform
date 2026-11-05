---
module: console_source
owner: console_source
last_verified: {commit: 721b59a094, date: 2026-11-03}
gates:
  SOURCE:
    state: GO
    cmd: python tools/harness/rosy_harness.py lint
    evidence: "D-637 independent source review, committed remote regression and local main FF; see dated result. D-962 independent image and identity backup scope at 5f02d723d1: remote 335 backend/signing/image/backup cases plus 71 opted-in identity TLS/browser cases passed, 0 skipped, 0 NEW. Full Account tables including HTTP audit preserved; stale/corrupt backup refusal, strict signed legacy/new groups, reused image pins, branding, login/profile/admin and first-password flows verified. Prior e81af2d7c3 closure also passed 320 cases including Fleet header browser/Node compatibility. OCI construction and live independent-image/timer acceptance remain pending. D-962 canonical scope closure at 59dbc2136b: 581 remote shared-web/component/registry/ownership/identity/header/Node/image cases passed, 1 unrelated Android export opt-in skipped, 0 NEW; exact title whole-file isolation completed. Original FULL stopped on stale consumers; replacement FULL and live artifact/field acceptance remain pending. D-963 Account-cookie USB approval at 721b59a094: scoped remote USB/Node/receiver/actual TLS identity consumers passed64, skipped0, NEW0; official light-host peak642MiB. Backend grants/CSRF unchanged; existing FULL, artifact and live gates remain separate."
  LOCAL:
    state: GO
    cmd: python tools/remote/remote_pytest.py --log-dir X:/DevTemp/d637-check -- test/test_remaining_platform_installed.py -q
    evidence: "D-637 independent source review, committed remote regression and local main FF; see dated result. D-962 independent image and identity backup scope at 5f02d723d1: remote 335 backend/signing/image/backup cases plus 71 opted-in identity TLS/browser cases passed, 0 skipped, 0 NEW. Full Account tables including HTTP audit preserved; stale/corrupt backup refusal, strict signed legacy/new groups, reused image pins, branding, login/profile/admin and first-password flows verified. Prior e81af2d7c3 closure also passed 320 cases including Fleet header browser/Node compatibility. OCI construction and live independent-image/timer acceptance remain pending. D-962 canonical scope closure at 59dbc2136b: 581 remote shared-web/component/registry/ownership/identity/header/Node/image cases passed, 1 unrelated Android export opt-in skipped, 0 NEW; exact title whole-file isolation completed. Original FULL stopped on stale consumers; replacement FULL and live artifact/field acceptance remain pending. D-963 Account-cookie USB approval at 721b59a094: scoped remote USB/Node/receiver/actual TLS identity consumers passed64, skipped0, NEW0; official light-host peak642MiB. Backend grants/CSRF unchanged; existing FULL, artifact and live gates remain separate."
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
- D-961
- D-892
- D-775
- D-801
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

## 2026-10-16 충전 운행 주체 오류 안내

TRIP_OWNER_KIND_INVALID의 안내를 추가했다. 영향 Console Chromium 457개가 통과했으며 UI source는 이후 바뀌지 않았다. 혼합 실행에 포함된 비브라우저 label 검사 1개는 당시 parser 문제로 실패했고, 수정 후 39f94f151의 계약/회귀 486개에 포함되어 통과했다. 원 실행 종료 코드는 1이며 browser 결과와 구분한다. 운영 충전 화면 전체와 현장 수용을 뜻하지 않는다.

## 2026-11-06 선택 로봇의 저속 수동 조종

`manual-control.js`가 선택한 로봇의 홀드 조종과 해제 정지를 소유한다. 기존 Fleet
`POST /api/fleet/do`의 move intent와 공용 hold ticker를 재사용하며, CORE가 최종 명령을
판정한다. 기본 요청은 선속도0.03m/s·각속도0.10rad/s 이하, 한 번에2초 이하다.
상태·권한·수동 모드·관측 freshness·작업 점유 검사가 막으면 사유를 표시한다.
선택 변경이나 페이지 종료 때에도 원래 기체로 최종0을 보낸다.

패드는 재생성되는 로봇 카드 밖에서 수명을 유지하며 모바일에서도 선택한 로봇의 상태 뒤에
놓인다. 현재 수동 모드 전환은 로봇 운용 화면에서 한다. 이 변경만으로 관제의 모드 전환,
자동 위치 추정, 지도 목표 도착이나 실제 배포가 완료된 것은 아니다.

관련 source·원격 브라우저·HTTP 계약·모바일 회귀의 증거와 현장 시험 범위는
[검증 기록](logs.md#2026-11-06--a9210f10f9--선택-로봇-홀드-조종과-모바일-상태-우선-배치)에 구분했다.
