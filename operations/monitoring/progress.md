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
    state: GO
    evidence: 실제 backend Chromium16+G1 총151 PASS, scope 거부 상태6 PASS, G2 40셀 캡처와 G3 대표 검토 차단 없음. docs/validation/uiux-surfaces-2026-10-26/monitoring/README.md 참조.
    cmd: python tools/remote/remote_pytest.py --log-dir "$env:TEMP/rosy-monitoring-ui-canonical-green" -- ROSY_RUN_BROWSER_TESTS=1 test/test_monitoring_browser.py shared/web/test/test_surface_registry.py shared/web/test/test_shared_controls.py shared/web/test/test_surface_typography_focus_contracts.py shared/web/test/test_ui_token_contracts.py shared/web/test/test_palette_gates.py -q
  ROS-SIM:
    state: N/A
  ARTIFACT:
    state: HOLD
    blocker: CLI wheel·UI 묶음·3프로필·시험 PC unit 파서와 실제 Caddy 격리 HTTPS 검증은 통과했다. 배포 대상 PC 고정 경로·계정·권한 확인은 미수행이며 실제 설치·LAN/TLS 수용은 별도다.
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
독립 재검토에서 기존 지적 해결·추가 차단 없음이 확인됐다. 상태 화면의 LOCAL 수용은 완료했으며 native 배포와 실제 PC 수용은 별도다.

ROS-free HTTP 감시 프로필이므로 ROS-SIM은 N/A다. 로봇·호스트의 제어·안전·복구 권한은 기존 소유자에게 남긴다.

## 다음 gate

1. source/wheel/test 기반과 이 등록을 먼저 착지한다.
2. 상태 화면 LOCAL 검증과 배포 입력 SOURCE 검증을 공식 절차로 착지한다.
3. 대상 OS에서 unit 검사와 실제 PC 설치·LAN/TLS·중앙/사이트 단절·복구를 수용한다.

## 현재 유효한 금지사항

- Monitoring으로 재시작·재부팅·네트워크 변경·안전 해제를 실행하지 않는다.
- 수집기 자체의 정상 보고, host 시험이나 화면만으로 현장 가용성을 GO로 올리지 않는다.
