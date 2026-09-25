---
module: dock
logical_modules: [M07, M11]
owner: 도킹
last_verified: { commit: "dc89264", date: 2026-09-17 }
gates:
  SOURCE:
    state: GO
    evidence: "ROSY-DOCK-001 계약 시험 통과 (README ↔ rosy_core.docking.agent 파서 일치, 필수 필드, Wi-Fi 자격증명 부재) 7 passed"
    cmd: "PYTHONPATH=src/rosy_core:src/rosy_control:src python3 -m pytest test/test_dock_contract.py -q"
  LOCAL:
    state: GO
    evidence: "도크 계약 + 로봇측 DockingManager 상태기계·재시도·인터록 시험 107 passed (2026-09-15 Windows, 미커밋 WIP가 있는 src/rosy_core를 import)"
    cmd: "python3 -m pytest test/test_dock_contract.py src/runtime/features/test/test_docking.py -q"
  ROS-SIM:
    state: HOLD
    blocker: "코스트맵 충돌 면제(docking/collision_exemption)는 실제 costmap 통합 시험 전까지 intent-only (Device 검증 계획 P1 §7). ROS 2 Jazzy 환경에서 도킹 시퀀스 시뮬레이션 미실행"
  ARTIFACT:
    state: HOLD
    blocker: "ESP32 Arduino 펌웨어 빌드·플래시 증거 없음. 이 호스트에는 ESP32 toolchain이 없어 실행하지 않았다"
  DEVICE:
    state: HOLD
    blocker: "물리 도크 벤치 설치와 device-readback류 증거 없음. `dock/firmware/rosy_dock/rosy_dock.ino` 참조 구현만 존재하고 실기 조립·통전 시험 기록이 없다"
  FIELD:
    state: PARKED
adrs: [D-27, D-28]
plans:
  - docs/plans/2026-09-02-docking-station-design.md
  - docs/plans/2026-09-15-module-harness-design.md
---
## 지금 상태

- ROSY-DOCK-001 계약: `firmware/dock/README.md`의 `/status` 예시와 `rosy_core.docking.agent`의 파서가 일치함을 시험이 고정한다. `load_present`·`charging`은 필수(누락은 오류, `false` 기본값 금지).
- 도크는 부하를 감지한 뒤에만 통전하고 제거 시 즉시 차단한다(감전·단락 방지가 MCU를 두는 1차 이유이며 전류 보고는 부차적).
- 충전 확인은 도크 보고 전류 **와** 로봇 필터링 팩 전압(하강하지 않음) 두 소스를 모두 요구한다(D-28). 이 판정이 D-27 deep-discharge 셧다운 억제의 입력이다.
- 코스트맵 충돌 면제는 approach 구간 전용으로 설계되었으나 실제 costmap 통합 시험은 아직 없다 — intent-only.
- 실물 도크 조립·통전·접근 성공률·접촉 저항 등은 하드웨어에서만 확정 가능하며 아직 기록이 없다(설계 문서 `## Verification` 절 "hardware-only" 목록 참조).
- Wi-Fi 자격증명이 소스에 없음을 `test_dock_contract.py`가 강제한다.

## 다음 gate

1. ROS 2 Jazzy 환경에서 도킹 시퀀스(정지/재시도/코스트맵 면제) 실제 costmap 통합 시험을 실행해 ROS-SIM을 되돌린다.
2. ESP32 toolchain이 있는 환경에서 펌웨어 빌드·플래시 증거를 남겨 ARTIFACT를 되돌린다.
3. 물리 도크를 조립하고 접근·접촉·통전 시험을 벤치에서 실행해 DEVICE 증거(readback류)를 남긴다.

## 현재 유효한 금지사항

- 도크는 로봇 API에 인바운드 연결을 열지 않는다(로봇만 폴링).
- 도크 firmware 소스에 Wi-Fi 자격증명을 넣지 않는다.
- `charging: true` 단일 소스(도크 보고)만으로 D-27 셧다운 억제를 판정하지 않는다 — 팩 전압 비하강 확인이 함께 필요하다.
- 부하 미검출 상태에서 접점을 통전하지 않는다.
