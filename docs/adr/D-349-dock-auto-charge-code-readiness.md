## D-349 도크 자동 충전 — 코드 준비 완료 상태 기록

**상태:** 이 문서는 오늘 세션에서 사용자와 확정한 도크 하드웨어 결정들과 그에 대응하는 코드 준비 상태를 한 장으로 정리한다. 실물 조립은 별도 회차.

## 확정된 결정 (2026-09-30, 사용자 승인)

| 결정 | 내용 |
|---|---|
| 접점 방식 | **자석형** — 자석은 전부 도크 측, 로봇 측은 철판+패드 (액티브 부품 없음) |
| 하중 감지 | **리밋스위치(접촉식)** — ADC 프로브 폐기. 리드스위치 기각(자기 도크의 자석에 자기 반응) |
| 전원 | **전부 시판품** — 일반 USB-C PD 충전기 + PD 트리거(고정 PDO) + 2S 밸런싱 충전기 모듈 + 릴레이 |
| 온도 | **NTC 전면 보류** — GPIO33/36 풋프린트만. 충전IC TS핀 요구 확인 전까지 |
| 만충 후 | **HOLD + Fleet/운영자 판단** — 자동 undock 없음. 실물 이후 구현 |
| 도크 구조 | **무모터** — 홀딩은 자석만, 로봇이 그냥 들어와 그대로 있음 |

## 코드 준비 상태 (전부 존재하고 시험 통과)

| 계층 | 위치 | 상태 |
|---|---|---|
| **트리거** (배터리→도크 오퍼) | `bridge/battery_policy.py` 8단계, DNC-006 | ✅ 구현·시험 |
| **모드 소유** (DOCKING 우선순위 4) | `docking/manager.py`, `test_docking_mode_ownership.py` | ✅ |
| **상태머신** (staging→획득→접근→착좌→충전) | `docking/manager.py` + `parking_phases.py` | ✅ |
| **센서 폐루프** (마지막 cm) | `parking_phases.py` — IR·초음파·오도메트리 | ✅ |
| **충전 확정** (2소스: 도크 전류+팩 전압 비하락, 10s 창, 비대칭) | `docking/charging.py` | ✅ |
| **도크 폴링** (GET /status, 실패 4구분: unreachable/timeout/bad_response/ok) | `docking/agent.py` | ✅ |
| **언도킹** (오도메트리 후진 only, blind) | `parking_phases.py` (DNC-004) | ✅ |
| **도크 데이터베이스** (docks.json, teach-by-docking) | `docking/database.py` | ✅ |
| **펌웨어** (ESP32, 리밋 인터록, 4샘플 평균, 폴트 폴드백) | `firmware/dock/firmware/rosy_dock/rosy_dock.ino` | ✅ 계약시험 통과 |
| **계약** (ROSY-DOCK-001, required 2 + optional) | `firmware/dock/README.md` + `test/test_dock_contract.py` | ✅ 7 passed |
| **호스트 시험 전체** | 도킹 SM·모드·배터리·전력 | ✅ 372 passed |
| **Pinky Pro 활성화** | `capabilities.yaml` `docking.supported: false` | ⏸ 의도적 — 실물 조립 후 true로 |

## 남은 것 (전부 실물·조달)

| 단계 | 내용 |
|---|---|
| 자재 구매 | PD 충전기, PD 트리거, 2S 밸런싱 모듈, 릴레이, 포고핀, 자석(N35 소형), 리밋스위치, 철판, 다이오드+퓨즈 |
| D0–D5 조립 게이트 | `docs/plans/2026-09-20-dock-build-design.md` §2 순서 |
| 자석 분리력 실측 | 스프링 스케일 10회, 목표 ≤2N (D5에서) |
| capabilities true 전환 | `docking.supported: false → true` (D5 통과 후) |
| 만충 HOLD + `docked.full` 이벤트 | 실물 이후 구현 |

## 안전 경계 (이 문서의 핵심 가치)

코드에 이미 박혀 있는 것:
1. **맨접점 통전 금지** — 리밋이 안 눌리면 출력 0V (펌웨어 첫 규칙, `setOutput` 단일 개폐점)
2. **도크 단독 불신** — `charging:true`만으로 D-27 셧다운 억제 불가 (팩 전압 비하락 10s 창 필요)
3. **무충전 시 즉시 폴백** — RETURN_HOME → 발신 불가면 e-stop 승격 (SAF-005)
4. **언도킹 blind** — 오도메트리 후진 only, 센서 의존 없음 (DNC-004)

이 네 가지는 하드웨어가 어떻게 바뀌어도 코드가 지킨다.
