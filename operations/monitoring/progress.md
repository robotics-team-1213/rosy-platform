---
module: monitoring
owner: MONITORING
last_verified: {commit: 6b0f7568f5, date: 2026-10-26}
gates:
  SOURCE:
    state: GO
    evidence: 독립 수집·집계·읽기 API와 POSIX CLI의 원격98시험 및247구조검사 통과. UI와 native 배포는 별도 gate다.
    cmd: python tools/remote/remote_pytest.py --log-dir "$env:TEMP/rosy-monitoring-launcher-accepted-green" -- operations/monitoring/test -q
  LOCAL:
    state: HOLD
    blocker: 개별·중앙·중앙 단독 프로세스와 프로세스 간 lease는 검증했으며 실제 backend 상태 화면의 브라우저 수용이 남아 있다.
  ROS-SIM:
    state: N/A
  ARTIFACT:
    state: HOLD
    blocker: CLI 포함 wheel 설치는 검증했으며 화면·native 서비스·TLS 프록시 배포 묶음이 남아 있다.
  DEVICE:
    state: HOLD
    blocker: 실제 관제 PC의 네이티브 설치·프로세스 수명 검증을 수행하지 않았다.
  FIELD:
    state: HOLD
    blocker: 실 PC 배치·LAN/TLS 단절 및 복구·시각·제어 영향 수용이 남아 있다.
adrs: [D-876]
---

## 지금 상태

이름은 **ROSY Monitoring**, 한국어는 **ROSY 시스템 모니터링**이다.
독립 wheel `rosy-monitoring`, import `rosy.monitoring`의 관측·설정·자격·durable 캐시,
기존 원천의 읽기 전용 수집, scoped HTTP API와 독립 CLI가 있다. 계약은 [Monitoring API](../../docs/reference/rosy-monitoring-api.md)다.
`6b0f7568f5` 원격98시험(설치 wheel·실제 독립 프로세스 포함)과 구조/harness/affected247시험이 통과했으며 두 비교는 NEW/KNOWN/FLAKY0이다.
개별·peer 통합·peer 없는 중앙 직접 수집, 중앙 종료 후 현장 수집 지속, 별도 프로세스 writer 거부를 검증했다.
독립 재검토에서 기존 지적 해결·추가 차단 없음이 확인됐다. 상태 화면·native 배포와 실제 PC 수용은 남아 있다.

ROS-free HTTP 감시 프로필이므로 ROS-SIM은 N/A다. 로봇·호스트의 제어·안전·복구 권한은 기존 소유자에게 남긴다.

## 다음 gate

1. source/wheel/test 기반과 이 등록을 먼저 착지한다.
2. 별도 상태 화면과 기존 관제 진입점을 실제 backend·브라우저로 검증한다.
3. native·TLS 프록시 배포 묶음을 검증하고 실제 PC/네트워크 수용을 구분한다.

## 현재 유효한 금지사항

- Monitoring으로 재시작·재부팅·네트워크 변경·안전 해제를 실행하지 않는다.
- 수집기 자체의 정상 보고, host 시험이나 화면만으로 현장 가용성을 GO로 올리지 않는다.
