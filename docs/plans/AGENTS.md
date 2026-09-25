<!-- Parent: ../AGENTS.md -->
<!-- Generated: 2026-09-02 | Updated: 2026-09-23 -->

# plans

## Purpose

Dated design and execute plans (2026-08-31 onward). These are the working trail for Pi runtime, motors, power, dashboard, docking, battery integrity, Wi-Fi, ROS graph observability, and OS image/release.

`docs/plan/` 은 2026-09-20 에 폐쇄됐다 — 역사 WBS(`ROSY Implementation Plan.md`)와
Flask parity checklist가 추적용으로 여기에 합류했다. 둘은 실행 근거가 아니라
기록이다.

## Key Files

| File | Description |
|------|-------------|
| `ROSY Implementation Plan.md` | 역사 WBS (ROSY-PLN-001 v2.0): phases P0–P6, Pn-xx tasks, AT/FAT/MAT matrix — 추적용 |
| `ROSY Flask Parity Checklist.md` | 역사 D-3/P0-7: 구 Flask nav server 가 FastAPI 로 커버해야 했던 기능 목록 — 추적용 |
| `2026-08-31-raspberry-pi-runtime.md` | Pi runtime split (core/motor/io) |
| `2026-09-01-raspberry-pi-wifi-deployment.md` (+ `-design`) | Headless Wi-Fi/SSH image |
| `2026-09-01-motor-control-contracts.md` (+ `-design`) | ROS-free MotorController contracts |
| `2026-09-01-pi-motor-commissioning.md` (+ `-design`) | UART / Dynamixel bench |
| `2026-09-01-deep-power-states-design.md` | IDLE/STANDBY duty cycling (D-24/D-25) |
| `2026-09-01-proximity-wake-standby.md` (+ `-design`) | Ultrasonic wake |
| `2026-09-01-rosy-dashboard.md` (+ `-design`) | Embedded FastAPI dashboard (D-23) |
| `2026-09-01-ros-network-observability.md` (+ `-design`) | ROS graph / DDS telemetry |
| `2026-09-01-rosy-os-v1-image-release-design.md` | Signed image + Host Agent |
| `2026-09-02-battery-integrity-low-battery-alert.md` (+ `-design`) | SAF-005 curve, hysteresis, D-27 shutdown sentinel |
| `2026-09-02-docking-station.md` (+ `-design`) | Dock SM; last cm is sensor-closed-loop |
| `2026-09-03-runtime-maintainability-rules.md` | Runtime slice module rules (catalog, launch compose, Nav2 policy) |
| `2026-09-05-vision-accelerator-shield-design.md` | Pi 5 HAT/M.2 AI Kit vision offload (D-29 proposed; compose profile `vision`) |
| `2026-09-08-swarm-formation-slice-design.md` | Fleet-less N-robot formation slice: `rosy_fleet` seed (geometry, slot assignment, relay, FOR-004 session), `gz_multi core:=true`, sim bench; D-35 candidate |
| `2026-09-08-swarm-formation-slice.md` (+ `-results`) | Execution plan for that slice (15 TDD tasks, ROS-free until the sim bench) and the results file that records what the sim bench measured and what it could not |
| `2026-09-13-rosy-os-device-validation-implementation-plan.md` | Rosy OS 기능 구현·자동화 시험·ARM64 artifact·Pi Device 설치/readback·Pinky Pro/OMX 현장 승격 gate |
| `2026-09-14-site-middleware-role-fabric-design.md` | 관제 PC Fleet 서버가 모으고 흩뜨림. 디바이스는 계약 버스만. 역할 단일 (D-59) |
| `2026-09-14-site-middleware-role-fabric.md` | D-59 실행: 역할 가드 + ROS-free SiteHub gather/scatter (UI·영상·outbound·Pi 제외) |
| `2026-09-15-navigation-swarm-split-design.md` | 추종을 navigation에서 분리해 `rosy_core.swarm`으로 (D-60) |
| `2026-09-15-navigation-swarm-split.md` | D-60 실행: poses/manager 이동, navigation import 금지, 동작 불변 |
| `2026-09-15-module-harness-design.md` | 모듈별 progress·logs·생성 index와 `tools/harness` 계약 시험 (D-61 Accepted) |
| `2026-09-16-optional-runtime-slices-design.md` | CORE 필수, motor/io/nav/vision/omx/ai 선택 설치 (D-62) |
| `2026-09-16-optional-runtime-slices.md` | D-62 실행: board 카탈로그, capability 암전, install preset, CORE import 가드 |
| `2026-09-16-modular-middleware-goal-design.md` | 모듈형 미들웨어 끝 상태 (D-63) |
| `2026-09-16-core-control-import-boundary.md` | D-64: rosy_control import는 센서 어댑터만 |
| `2026-09-16-concept-runtime-alignment-design.md` | Concept Node/Device/Capability mapped onto CORE + D-62; apt/rosyctl deferred (D-65) |
| `2026-09-16-concept-runtime-alignment.md` | Execution: identity one plane, inventory API, adapter manifests, TaskKind, Control launch guard |
| `2026-09-17-arm64-artifact-native-pi-plan.md` | D-66 ARM64 after QEMU HOLD: native Pi (or pinned digest), not Hub hollow ros-base |
| `2026-09-17-concept-folder-adr-plan.md` | concept 00–15 → D-67–D-71; 09–12 and apt/rosyctl are not v1 |
| `2026-09-17-remaining-gates-adr-plan.md` | leftover gates → D-78–D-81; G0–G3 reuse Proposed D-41–D-56 |
| `2026-09-17-remaining-runtime-adr-plan.md` | leftover runtime → D-83–D-86; ROS-SIM 묶음, hardware 이미지, dock ESP32, POSIX identity |
| `2026-09-17-remaining-execution-adr-plan.md` | leftover execution → D-87–D-91; Device ADR park, D-54–D-56 source Accepted |
| `2026-09-17-robot-soccer-game-host-design.md` | 실기 Pinky 1v1 푸시볼. 경기는 `rosy_games` 소유, Fleet은 통로, Isaac은 학습 어댑터 (D-90). CORE 모드 없음 |
| `2026-09-18-rosy-games-local-host.md` | rosy_games LOCAL 실행 계획: 스켈레톤 → gate·MatchHost·teleop 클라이언트. Isaac/overhead 제외 |
| `2026-09-18-rosy-games-overhead-plan.md` | 천장 카메라 관측 어댑터. OpenCV는 overhead만. 합성 시험 ≠ DEVICE (D-94, D-95) |
| `2026-09-18-rosy-games-remaining-adr-plan.md` | 남은 games 트랙 → D-95–D-100; 골은 ArUco 20/21+영역, 온보드/Isaac은 FIELD 뒤 |
| `2026-09-20-camera-placement-design.md` | ??? ?? ?? ? Picamera2/CSI ??? host service + least-privilege ????? ?? (Task 5, D-52) |
| `2026-09-20-dock-build-design.md` | ?? ?? ?? ?? ? 1? ?? ??, DNC-007 ?? ??, teach-by-docking ??? (DNC) |
| `2026-09-20-pi-bench-commissioning-design.md` | Pi ?? ???? ? artifact ???readback ?? ??? (D-66) |
| `2026-09-21-pinky-device-commissioning-design.md` (+ implementation plan) | Fail-closed G0-G5 first physical Pinky Pro session and evidence workflow |
| `2026-09-21-hardware-mapping-g5-design.md` (+ implementation plan) | D-144 hardware SLAM backend, writable map output, and MCAP/hash-bound G5 evidence |
| `2026-09-21-ubuntu-native-ros-runtime-design.md` | D-161 immediate transition to Ubuntu Server 24.04 arm64 + native ROS 2 Jazzy product runtime |
| `2026-09-21-ubuntu-native-ros-runtime.md` | Test-first execution plan for native image, services, payload, SD and device evidence |
| `2026-09-22-pinky-pro-flashable-image-design.md` | D-164: signed `.img.xz` product artifact, native image customization, trust and gate design |
| `2026-09-22-pinky-pro-flashable-image.md` | Test-first implementation plan from Canonical Pi image through SD readback and Pinky acceptance |
| `2026-09-22-pinky-first-boot-fixes.md` | D-174: first-boot defects (recovery import, live hostname, operator key, ROS home, reflash identity, card diagnostics) and boot status indicator T0 |
| `2026-09-22-rosy-debug-log-system.md` | D-175: layered debug logs outside CORE — journald ledger, FAT32 boot black box, SSH/card collector, native readback, later API |
| `2026-09-23-boot-config-and-fallback-ap.md` | D-176: editable boot-partition `rosy-config.yaml` (applied then scrubbed) and per-card fallback AP |
| `2026-09-21-traffic-light-controller-research.md` | 알리 신호등(접점 스위치)을 ESP32+릴레이로 관제 제어하는 조사 보고서 — 제품/릴레이/보드/펌웨어/통신/안전 비교와 ROSY-SIGNAL-001 근거 |
| `2026-09-21-fleet-signals-integration-design.md` | G-S3 설계: Fleet 콘솔이 ROSY-SIGNAL-001 장치를 gather/scatter — signals.yaml, SignalConsole(재단언·all_red scatter), snapshot/UI 통합 |
| `2026-09-22-fleet-signals-integration.md` | G-S3 실행 계획: T-S3-1~6. 상시 폴링 루프를 throttled refresh 로 바꾼 변경 기록 |
| `2026-09-22-signals-acceptance-plan.md` | 신호등 실물 수용 계획 — 증거 등급(E1–E3), 수용 기준 AC-01~26(정량 합격선, AC-24~26은 속도 설계에서 승격), 고장 주입 S-01~12, 벤치 절차 B0–B7, 구조적 약점 W1–W9, 버튼 맵핑 갈래·특성화 시트(방전 조건·cross-talk·분리비 ≥3배 포함) |
| `2026-09-22-signals-button-contract-v2-proposal.md` | ROSY-SIGNAL-001 v2 제안 — 모드 사이클 버튼용 펄스 프리미티브, 피드백 등급 F0/F1/F2/F-EXT 결정 대기, 페일세이프 재정의 |
| `2026-09-22-signal-observer-vision-design.md` | 신호등 관측 평면 설계 — 카메라+OpenCV(고전 분할 v1)/YOLO(선택 v2)를 제어와 분리한 읽기 전용 관측 서비스, 명령↔컨트롤러↔실측 3자 교차 검증 |
| `2026-09-22-signal-speed-pi-design.md` | 속도 평면 설계 — 라즈베리파이 배치(picamera2 소스), 오도메트리 1차+카메라 검증의 과속 판정, 감속 루프(Fleet 판정·신호 표시), AC-24~26(2026-09-22 수용 계획 §3 으로 승격 완료 — 판정의 기록 위치는 거기), D-166(과속 반응 기록 전용) |
| `2026-09-22-scene-context-road-design.md` | D-162 장면 상황 프로파일 설계 — 닫힌 context 집합, 오프라인 리비전 프로파일, 제네릭 보수 폴백, 첫 소비자는 도로 인식 파라미터 |
| `2026-09-22-scene-context-road.md` | D-162 실행 플랜 T1–T5 — 순수 로직(T1/T2 착지), 노드 wiring(T3), CORE 수용(T5) |
| `2026-09-23-core-dev-overlay-design.md` | D-179 설계: 벤치 CORE는 `/var/lib/rosy-dev` 읽기 전용 바인드. `/opt/rosy`·서명 릴리스·GitHub 설치와 분리 |
| `2026-09-23-core-dev-overlay.md` | D-179 실행: 허용 목록·해시 성공·readback HOLD·네이티브 drop-in·Windows 호출. 두 번째부터는 재시작만, 재부팅은 이미지로 복귀, compose 프로젝트는 `rosy-runtime` |
| `2026-09-24-folder-layout.md` | D-186 실행: 루트는 `env.sh`만, 벤치·설치 셸은 `tools/`와 `deploy/`, 텔레옵·주행 기록은 `data/` |
| `2026-09-25-ownership-naming-control-plane.md` | D-227: 여섯 책임은 지금 트리의 이름. 목표 루트·명령 봉투·AI 워커는 열지 않는다 |
| `2026-09-25-decision-lane-recovery.md` | D-228 실행: 차선 판단은 FOLLOW/STOP id. 속도는 line_follow 에 남긴다 |
| `2026-09-25-ownership-naming-input-v0.2.md` | 입력 노트. D-227이 채택한 범위만 실행 기준이다 |
| `2026-09-25-decision-fabric-input-v0.8.md` | 입력 노트. 판단 경계는 D-228·D-229다. `src/runtime` 트리는 폴더가 아니다 |
| `2026-09-25-folder-map.md` | D-229 이후의 현재 폴더를 읽는 지도 |
| `2026-09-25-d231-layered-move.md` | D-231 실행: 영역 하나당 커밋 하나로 `contracts/runtime/devices/<계열>/products/hmi` + `firmware/`로 옮긴다. D-196 Task 6–8을 대체. 미실행 |
| D-73 | `tools/harness/harness.yaml` `functional` + `test/test_module_functional_surface.py` |

## Subdirectories

None.

## For AI Agents

### Working In This Directory

- Read the matching `-design.md` before changing power, docking, battery, or release code.
- Do not treat these as the API contract; that remains `docs/reference/`.
- Branch `feat/swarm-formation-slice` maps to `2026-09-08-swarm-formation-slice-design.md`.

### Testing Requirements

Each execute plan names pytest modules (usually `src/core/core/test/test_power.py`, `test_battery.py`, `test_docking.py`, or repo `test/`).

### Common Patterns

Filename `YYYY-MM-DD-kebab.md`; design and execute are separate files.

## Dependencies

### Internal

- Code under `src/runtime/core`, `src/devices/pinky_pro/bringup`, `deploy/`

### External

None.

<!-- MANUAL: -->
