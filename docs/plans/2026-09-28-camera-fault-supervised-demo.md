# Camera Fault Supervised Demo Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Pinky 전면 카메라 고장 시 관제 PC가 현장 전체 영상을 보고, 살아 있는 로컬 센서와 수용된 기능에 맞는 제한된 시연 작업을 지시·확인한다.

**Architecture:** Vision은 천장 카메라의 최신 JPEG를 관제 브라우저에 직접 제공하고 Fleet에는 좌표·상태만 보낸다. CORE는 센서/작업 적격성과 최종 `cmd_vel`·정지를 소유한다. Fleet은 인증된 작업자의 의도를 전달하고 결과 단계와 차단 이유를 보여준다. D-313의 단계별 기능은 기본 비활성으로 시작한다.

**Tech Stack:** ROS 2 Jazzy CORE, Python/FastAPI, ROS-free policy, Fleet 정적 JS, `overhead` WebSocket ingest, Caddy TLS, pytest/Playwright. 실물 Pinky와 현장 폰 수용은 별도 gate.

---

## T0 — 기준선과 계약 고정

**읽을 파일:** `docs/adr/D-313-supervised-camera-fault-demo.md`, `docs/adr/D-257-site-lane-map-and-overhead-sightings.md`, `docs/reference/ROSY API & Protocol Reference.md`, `src/runtime/gateway/core/bridge/control_sensor_adapter.py`, `src/runtime/services/core_features/line_follow/manager.py`, `src/site/overhead/overhead/ingest.py`, `src/site/fleet/fleet/server/app.py`, `deploy/site/Caddyfile`.

1. 현재 worktree·HEAD·변경 경로를 기록하고 다른 작업자의 WIP를 건드리지 않는다. 구현은 저장소 `.worktrees/<짧은이름>`에 `git worktree add --relative-paths`로 격리한다. 임시 로그·스크린샷은 `X:\DevTemp\`에만 둔다.
2. 현재 `IR_LINE` 보정 기본값(false), `motor`/`hardware` capability, G4/G5 및 Vision/Fleet 실제 설치 상태를 별도 표로 확인한다. 소스 계약과 실기 상태를 섞지 않는다.
3. 아래 신규 API/상태 필드는 **제안**이다. T1/T3/T4 착수 시 API Reference와 `src/contracts/foundation/core_common/protocol/schemas.py` 또는 해당 서비스의 공유 schema를 한 커밋에서 고정한다. 기존 계약에 같은 의미가 있으면 재사용하고 새 필드를 늘리지 않는다.

## T1 — CORE가 고장과 정지를 정확히 보고

**파일:** `src/runtime/services/core_features/line_follow/manager.py`, `src/runtime/gateway/core/bridge/ros_bridge.py`, `src/runtime/gateway/core/bridge/control_sensor_adapter.py`, `src/runtime/services/core_features/safety/manager.py`, `src/runtime/sensing/control/control/command_gate.py`, `src/runtime/sensing/control/control/obstacle_risk.py`, `src/contracts/foundation/core_common/protocol/schemas.py`, `docs/reference/ROSY API & Protocol Reference.md`; 시험 `src/runtime/gateway/test/test_line_follow.py`, `src/runtime/sensing/test/test_command_gate.py`, 신규 `src/runtime/gateway/test/test_camera_fault_hold.py`.

1. **RED:** 카메라 기반 작업 중 센서 프레임 중단·stale·invalid, preview만 중단, 중단 직후 늦게 도착한 프레임, E-stop 경합을 시험한다. 센서 상실이면 이전 후보 명령·generation·목표가 무효가 되고 0 명령 및 별도 속도 readback 상태가 남아야 한다. preview만 중단되면 카메라 기반 운전 증거까지 고장으로 단정하지 않는다.
2. **GREEN:** 기존 line-follow stale zero/loss latch와 CORE safety/command 소유권을 재사용해 `CAMERA_HOLD` 원인·시각·정지 단계를 보고한다. Navigation/도킹/기타 카메라 의존 작업의 취소 범위를 명시해 각 작업 owner에서 취소한다. Control policy가 camera tracking을 필수로 묶은 경우에는 정지 후 별도 보정 revision의 카메라 비의존 정책으로 다시 bind하고 새 센서 관측을 요구한다. 운전 중 `required` 센서 목록이나 `_tracking_required` latch를 지워 통과시키지 않는다. 새 모터 publisher를 만들지 않는다.
3. **검증:** 집중 pytest와 단일 최종 `cmd_vel`/watchdog ROS-SIM 시험. CORE의 명령 응답, 0 출력, 오도메트리 속도, 물리 정지 결과를 각각 다른 필드로 남긴다.

## T2 — 작업별 폴백 적격성 판정

**파일:** 신규 `src/runtime/services/core_features/recovery/camera_fault.py`와 `__init__.py`, 신규 `src/runtime/services/test/test_camera_fault_eligibility.py`, CORE 서비스 wiring과 capability 시험, `docs/reference/ROSY API & Protocol Reference.md`.

1. **RED:** 입력을 카메라 고장 종류, 현재 작업, 실행 모드/capability, G4/G5 gate, 센서 age·보정 revision, 지도/TF/localization, stop readback, Fleet 영상 시야/age로 분리한다. 다음 표의 허용·거부 이유를 각 테스트로 고정한다.

   | 요청 | 필요한 실기 증거 | 실패 시 |
   | --- | --- | --- |
   | `IR_LINE` 시연 | 바닥 흰 선, 개별 IR 흑/백 보정, fresh 선/낙하 IR, LiDAR/근접 정지, 승인된 구동 | `IR_NOT_ELIGIBLE`, HOLD |
   | 짧은 Nav2 goal | G4/G5, `hardware` Nav2 active, fresh LiDAR/IR/odom/TF, 일치하는 map ID, 관제 시야 | `NAV_NOT_ELIGIBLE`, HOLD |
   | 입회 Teleop | G4, 승인된 수동 제어, local safety/deadman, 관제 시야와 현장 작업자 | `TELEOP_NOT_ELIGIBLE`, HOLD |
   | 현장 회수 | 이동 승인 불필요 | 새 원격 이동 요청 거부 |

2. **GREEN:** ROS import 없는 순수 판정 함수가 `allowed_actions`, `reasons`, `evidence_ages`, `expires_at`을 낸다. Fleet 입력은 허용 범위를 낮출 수만 있고 로컬 센서 실패를 해제하지 못한다. 새 작업 시작 직전에 CORE가 다시 판정한다. E-stop·불명확한 정지 결과는 항상 거부한다.
3. **검증:** 단위 시험에서 오래된 영상/IR/LiDAR/TF, 보정 불일치, `motor` 모드의 Nav2 요청, sighting/robot pose 불일치, 영상 없이 선명한 로컬 센서의 작업별 차이를 검사한다.

## T3 — Vision의 인증된 라이브 영상

**파일:** `src/site/overhead/overhead/ingest.py`, 신규 `src/site/overhead/overhead/preview.py`, `src/site/overhead/overhead/cli.py`, `src/site/fleet/fleet/server/app.py`, `deploy/site/Caddyfile`, `deploy/site/compose.yaml`, `docs/reference/ROSY API & Protocol Reference.md`; 시험 `src/site/overhead/test/test_preview.py`, `src/site/fleet/test/test_no_video_relay.py`, Fleet 권한 시험.

1. **RED:** 무인증, 폰 업로드 token으로 보기, viewer lease로 명령, 다른 source 보기, 만료·변조 lease, stale 프레임, 업로드 폭주, 여러 viewer 동시 요청을 실패 시험으로 만든다. Fleet production 경로에 JPEG byte/import/route가 들어가면 기존 `test_no_video_relay.py`가 실패해야 한다.
2. **계약 제안:** 인증된 Fleet `POST /api/fleet/vision/lease`가 principal·source·보기 scope·짧은 만료의 서명된 lease를 낸다. 브라우저가 `Authorization` 헤더로 Vision `GET /api/vision/sources/{source_id}/frame`을 요청한다. Vision은 서명과 source scope를 직접 확인하고 최신 JPEG/캡처 시각/seq/age만 반환한다. URL query에 token을 넣지 않는다. Fleet·Vision에는 폰 업로드 token과 다른 검증용 비밀을 배포 secret으로 읽기 전용 mount하고 회전/재시작 시 오래된 lease를 무효화한다. Caddy는 해당 경로만 Vision으로 전달한다. 권한 발급은 Fleet, 영상 byte 제공은 Vision이다.
3. **GREEN:** ingest의 최신 1장만 읽고 오래된 프레임은 404/명시적 stale로 답한다. 크기·FPS·동시 요청/대역 상한을 둔다. 영상 서비스 고장·지연은 CORE 안전 루프에 영향을 주지 않는다. 영상 오류가 sighting 성공으로 감춰지지 않게 상태를 분리한다.
4. **검증:** localhost 합성 폰→Vision→브라우저 테스트, TLS reverse proxy/권한 계약, 부하에서 Fleet heartbeat·CORE stop 지연 독립 확인. 실제 프레임 age·사람의 관제 반응시간·로봇 제동거리로 지시 가능한 속도와 한 번에 이동할 구간을 정한다. 수치 상한은 측정치로 결정하고 환경별 설정으로 제한한다.

## T4 — Fleet 관제 화면과 지시 경로

**파일:** `src/site/fleet/fleet/server/web/index.html`, `web/console.js`, `web/map-view.js`, 필요하면 신규 `web/vision-view.js`, `src/site/fleet/fleet/server/console_view.py`, `app.py`; 시험 `src/site/fleet/test/test_server_app.py`, `test/test_fleet_console_browser.py`.

1. **RED:** 영상 stale/가림/미보정 구역에서 `라이브` 표시나 해당 구역의 관제 지원 이동 버튼이 켜지지 않는지, 불일치하는 robot pose/sighting, viewer 권한, 중복 goal, 디스패치 `UNKNOWN`, 정지 readback 부재를 시험한다.
2. **GREEN:** 라이브 영상과 지도/로봇 상태를 나란히 표시한다. camera source·captured age·보이는 구역과 로봇 ID를 표시하고 마지막 프레임 동결을 감춘다. `IR_LINE`, 짧은 goal, 입회 Teleop, 회수는 T2가 허용한 것만 활성화한다. Fleet은 CORE API를 통해 명령하고 로봇에 ROS/DDS를 직접 보내지 않는다. 명령 `QUEUED`/`ACCEPTED`/`RUNNING`/`COMPLETED`/정지 readback을 구별한다.
3. **검증:** 1920px 관제 PC와 좁은 화면에서 영상·상태·정지 조작이 보이는지 브라우저 시험. 합성 프레임/스크린샷만으로 현장 전체 시야나 물리 동작을 주장하지 않는다.

## T5 — 시연 경로와 배포

**파일:** `deploy/robot/config/line_follow.yaml`의 장치별 외부 설정, `deploy/site/site-cameras.yaml.example`, 신규 `docs/deployment/camera-fault-supervised-demo.md`, 해당 모듈 `progress.md`/`logs.md`.

1. 카메라 없는 **IR 선 시연**을 첫 경로로 잡는다. 실제 흰 선 구간, 장치별 IR 흑·백 측정과 cliff 보정, LiDAR/초음파/정지 readback, 단일 publisher를 확인한 뒤에만 외부 보정값을 적용한다. 저장소 기본 `ir_calibration_enabled: false`는 유지한다.
2. Nav2 경로는 D-311/312 G4, localization·지도·G5를 통과한 별도 단계다. Teleop은 수동 구동·deadman과 현장 입회를 별도 수용한다. 그전에는 UI에서 해당 작업을 막고 이유를 보여준다.
3. 서명 아티팩트/SD 설치, Pi 장치 identity와 loaded release, 실물 카메라 시야·프레임 age, IR/LiDAR/TF/안전 센서 readback, 바퀴를 든 시험, 제한된 바닥 시연을 차례로 기록한다. 명령 수락이 아니라 실제 정지·이동·무충돌을 확인한다.

## T6 — 고장 주입과 롤백

1. 전면 카메라 전원/프레임·관제 폰·Vision·Fleet·Wi-Fi·IR·LiDAR·TF를 한 번에 하나씩 끊는다. 각각 `CAMERA_HOLD` 또는 `RECOVERY_HOLD`, stale 표시, 추가 명령 거부, 로봇 0 속도와 독립 정지의 결과를 기록한다.
2. 카메라 복귀 후에도 자동 임무 재개/자동 IR 전환이 없음을 확인한다. 재선택 시 이전 frame/command generation이 재생되지 않게 한다.
3. 결함이나 정지 결과 불명확 시 폴백 작업 플래그를 끄고 이전 서명 아티팩트/관제 구성을 복원한다. 수용 기록이나 기본 센서 gate를 편집해 우회하지 않는다. FIELD 증거가 없으면 시연 범위를 영상 관찰·정지 시연으로 제한한다.

## 완료 판정

SOURCE/LOCAL의 정책·API·브라우저 시험, ROS-SIM의 단일 publisher/중단 시험, 서명 아티팩트, Pinky 장치 readback, G4/G5, 실제 관제 시야와 물리 정지·시연 경로를 독립 표시한다. 어느 한 단계의 PASS도 다음 단계를 대신하지 않는다.
