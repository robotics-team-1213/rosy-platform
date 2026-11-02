---
module: monitoring
owner: MONITORING
last_verified: {commit: 6b0f7568f5, date: 2026-10-26}
gates:
  SOURCE:
    state: GO
    evidence: "독립 수집·집계·읽기 API와 POSIX CLI의 원격98시험 및247구조검사 통과. UI와 native 배포는 별도 gate다."
    cmd: python tools/remote/remote_pytest.py --log-dir "$env:TEMP/rosy-monitoring-launcher-accepted-green" -- operations/monitoring/test -q
  LOCAL:
    state: GO
    evidence: "실제 backend Chromium16+G1 총151 PASS, scope 거부 상태6 PASS, G2 40셀 캡처와 G3 대표 검토 차단 없음. docs/validation/uiux-surfaces-2026-10-26/monitoring/README.md 참조."
    cmd: python tools/remote/remote_pytest.py --log-dir "$env:TEMP/rosy-monitoring-ui-canonical-green" -- ROSY_RUN_BROWSER_TESTS=1 test/test_monitoring_browser.py shared/web/test/test_surface_registry.py shared/web/test/test_shared_controls.py shared/web/test/test_surface_typography_focus_contracts.py shared/web/test/test_ui_token_contracts.py shared/web/test/test_palette_gates.py -q
  ROS-SIM:
    state: N/A
  ARTIFACT:
    state: GO
    evidence: "overlay 쌍(monitoring·account)을 포함한 서명 후보 site-2ba97ac2c346(PR #224 merge)가 2026-11-01 발행·설치됐다. 관제 PC 자동 업데이트 수용."
    cmd: gh release view site-2ba97ac2c346 -R robotics-team-1213/rosy-platform --json name,assets
  DEVICE:
    state: GO
    evidence: "관제(사이트) 호스트 입력 완료·Fleet viewer 'monitoring' 등록·overlay 활성(2026-11-01). rosy-site-monitoring-1 healthy. 현장 수용 기록 참조."
    cmd: ssh <site-host> "docker ps --format '{{.Names}} {{.Status}}' | grep monitoring"
  FIELD:
    state: GO
    evidence: "실제 단절·거부·TLS 수용 2026-11-01 — 401(무자격·용도 불일치 키)·403(범위 밖)·Fleet 정지 중 수집기 독립(200)과 fleet 노드 신선도 구별(age_s 9.19/valid 15s)·모니터링 정지 시 Fleet 무영향(502/200)·원격 클라이언트 CA 신뢰 TLS 200(콘솔 로그인 포함). 한계: 로봇 오프라인(2026-10-10~)으로 로봇 원천 단절 관측은 연결 뒤 보강. [현장 수용 기록](../../docs/validation/monitoring-site-overlay-2026-11-01/result.md)"
    cmd: ssh <site-host> "curl -sk -o /dev/null -w '%{http_code}' https://localhost:8443/api/monitoring/v1/snapshot"  # 401 without reader key; see the validation record for the full scenario set
adrs: [D-876, D-936]
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
