---
module: signal
logical_modules: []
owner: 사이트 인프라
last_verified: { commit: "uncommitted", date: 2026-09-22 }
gates:
  SOURCE:
    state: GO
    evidence: "ROSY-SIGNAL-001 host source-contract 14 passed. README ↔ 펌웨어 상태/명령, 부팅 페일세이프, 충돌 가드, token fail-closed, helper 정의, Wi-Fi 입력 분리, 자격증명 부재를 대조. Arduino compile/bench는 미실행 (2026-09-21 Windows)"
    cmd: "python -m pytest test/test_signal_contract.py -q"
  LOCAL:
    state: GO
    evidence: "Fleet G-S3 클라이언트·API·UI와 의도 1회 재단언/all_red 병렬 scatter 구현. fleet 362 passed, 5 skipped + ROSY-SIGNAL-001 계약 14 passed (2026-09-22 Windows)"
    cmd: "python -m pytest src/site/fleet/test test/test_signal_contract.py -q"
  ROS-SIM:
    state: PARKED
    blocker: "시뮬레이션 대상 아님(실물 접점 장비). Gazebo 쪽 lamp 플러그인과 무관"
  ARTIFACT:
    state: HOLD
    blocker: "ESP32 Arduino 펌웨어 빌드·플래시 증거 없음. 이 호스트에는 ESP32 toolchain이 없어 실행하지 않았다"
  DEVICE:
    state: HOLD
    blocker: "물리 벤치(G-S1) 미실행 — 수용 기준·절차는 docs/plans/2026-09-22-signals-acceptance-plan.md 로 고정했다. 최초 관문은 B0 신호등 입고 특성화(전압/배선/색당 전류), 이후 B2 부팅 글리치 10회(AC-02), B3 침묵→점멸 12 s(AC-11), B4 공유기 재시작 자기 복귀(AC-12, W1 위험)"
  FIELD:
    state: PARKED
adrs: [D-163]
plans:
  - docs/plans/2026-09-21-traffic-light-controller-research.md
  - docs/plans/2026-09-21-fleet-signals-integration-design.md
  - docs/plans/2026-09-22-fleet-signals-integration.md
  - docs/plans/2026-09-22-signals-acceptance-plan.md
---
## 지금 상태

- ROSY-SIGNAL-001 reference implementation: `firmware/signal/README.md` 의 `/status`·`/command` 예시와
  `firmware/signal/firmware/rosy_signal/rosy_signal.ino` 가 계약 시험으로 고정된다.
  `mode`·`lamps` 는 필수(누락은 오류, 기본값 금지).
- 펌웨어의 1차 임무는 제어가 아니라 **신뢰할 수 없음의 표시**다: 부팅·감독자 침묵
  (10 s)·재시작 → 전 기능 적색 점멸, 새 인증 명령 전까지 유지. 마지막 명령은 NVS 에
  저장하지 않는다(되살릴 상태를 없앤 것).
- 명령 경로는 fail-closed다: 토큰(`X-Rosy-Token`)이 없는 장치는 read-only 상태
  조회만 하고 어떤 명령도 수용하지 않는다. 적+녹 동시 명령은 `400 conflict`.
- `all_red`(점등, 명령된 정지)과 `failsafe`(점멸, 고장 표시)는 다른 말이다 —
  관제 화면이 "정지시켰다"와 "장비 고장"을 구별해야 하므로.
- Fleet G-S3 클라이언트·엔드포인트·UI가 구현됐다. 관제는 상태를 모으고, e-stop과
  함께 `all_red`를 병렬 하달하며, failsafe 장치에는 마지막 운영 의도를 한 번만
  재단언한다. 로봇 CORE 는 여전히 신호등을 모른다(site 장비, D-59).

## 다음 gate

1. 신호등 제품 확정(DC 12/24V 권장) + 릴레이 모듈 조달(3.3V 트리거 확인) 후 벤치
   G-S1: 접점 개폐 실측, 부팅 글리치로 접점 닫힘 여부 실측 → DEVICE 증거.
2. ESP32 toolchain 환경에서 펌웨어 빌드·플래시 증거 → ARTIFACT 되돌리기.
3. 물리 장치와 Fleet 콘솔을 같은 LAN에 놓고 status/command/failsafe 복귀를 실측한다.
   이는 host LOCAL GO를 DEVICE GO로 대체하지 않는다.

## 현재 유효한 금지사항

- 이 장치는 스스로 연결을 열지 않는다(서버 전용).
- 명령·토큰·자격증명을 소스에 박지 않는다. NVS + 시리얼 규정만.
- 적과 녹을 함께 켜는 상태는 존재할 수 없다(명령 단계에서 거절).
- 로봇 CORE 가 신호등을 제어하거나, 신호등 보고만으로 로봇 안전 동작을 억제하는
  설계는 하지 않는다.
