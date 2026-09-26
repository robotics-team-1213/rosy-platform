# 사이트 미들웨어 역할 패브릭 설계

작성일: 2026-09-14

상태: D-59 Accepted(설계 결정). Fleet 서버·관제 PC 런타임·영상 분리는 미구현. Device ARTIFACT/FIELD 게이트는 이 문서로 건너뛰지 않는다.

관련: [ADR Log](../reference/ROSY%20ADR%20Log.md) D-5, D-8, D-12, D-20, D-21, D-22, D-31, D-33, D-34, D-38, D-48, D-57, D-59 · [CORE SRS](../spec/ROSY%20CORE%20SRS.md) §2, §6.2, §14 · [FLEET SRS](../spec/ROSY%20FLEET%20SRS.md) §1 · [API Ref](../reference/ROSY%20API%20%26%20Protocol%20Reference.md) · [Device 검증 계획](2026-09-13-rosy-os-device-validation-implementation-plan.md)

## 1. 확정한 방향

관제 PC의 **한 Fleet 서버**가 현장의 모이는 점이다. 각 디바이스는 ROS를 서로에게 열지 않고, 로봇 쪽 CORE가 노출한 **미들웨어 계약**(REST 명령 + outbound 이벤트 + swarm pose 소켓)으로만 모이고 흩어진다. 영상은 나중에 인지 역할에서 분리할 수 있으나, 명령 버스나 최종 `cmd_vel`을 나누지 않는다.

한 컴포넌트는 한 역할만 수행한다. 다른 역할의 데이터를 바꿔 싣거나, 다른 역할의 권한을 빌려 바퀴를 돌리는 것은 결함이다.

이 문서는 새 메시지 브로커를 로봇에 올리지 않는다. 로봇 안 제어는 localhost ROS(D-33), CORE 사건은 EventBus(D-8), 사이트 계약은 기존 envelope(D-5, D-10, D-31)이다. Fleet 서버 내부 구현(프로세스, 큐, DB)은 이 계약 뒤에 숨는다.

## 2. 역할 목록 — 하는 일 / 하지 않는 일

역할이 겹치면 구현하지 않고 거절한다.

| 역할 | 사는 곳 | 한다 | 하지 않는다 |
|---|---|---|---|
| **로봇 게이트웨이** | `rosy_core` | 외부 API·인증·상태 스냅샷·EventBus·명령 중재·최종 `cmd_vel` 발행 | 장치 파일 개방, 원본 프레임 디코드, 대형 기하 계산, 미션 DSL |
| **장치 어댑터** | `rosy-io` / bringup | 열거된 장치만, deadman, `motor/ready` | FastAPI, Fleet 소켓, 안전 정책 결정, 최종 `cmd_vel` |
| **항법 실행** | Nav2 + `NavigationManager` | 목표·취소·세대, 우회 또는 정지 | 군집 오케스트레이션, 사이트 이벤트 팬아웃 |
| **추종 실행** | `SwarmManager` (팔로워) | 참조 pose → moving goal, 단절 HOLD | 리더 선정, 슬롯 배정, 다른 팔로워 지휘, `peer` DDS |
| **리더 참조** | 리더 CORE 소켓 | 자기 pose ≥10 Hz 발행 | 팔로워에 직접 명령, 대형 유지 계산 |
| **사이트 오케스트레이터** | 관제 PC의 Fleet 서버 | 등록, 미션, 대형 지정, pose 중계, 명령 REST, 이벤트 수집 | 로봇 ROS 토픽 구독, `/cmd_vel` 스트림, 원본 영상 필수 경로 |
| **관제 UI** | 관제 PC 웹 | Fleet가 모은 상태·이벤트·명령을 보여 주고 내린다 | 로봇 DDS, 로봇 로컬 대시보드를 사이트 관제로 대체하는 척 |
| **인지(현재)** | 선택 worker / 향후 vision 슬라이스 | 프레임 위생, compact evidence, telemetry | 모션 허가, 안전 권한, 사이트에 `Image` 상시 송출 |
| **로봇 로컬 화면** | CORE `/dashboard` (D-23) | 그 로봇 한 대의 현장 화면 | N대 관제, Fleet 미션 편집 |

`rosy_fleet` 씨앗 패키지(기하·배정·릴레이·CLI)는 오케스트레이터 역할의 구현 조각이다. 로봇 CORE를 수정하지 않는다. `FleetAgent`는 서버가 생기기 전에는 소켓을 열지 않는다.

## 3. 모이고 흩어지는 경로

```text
                    관제 PC
          ┌─────────────────────────┐
          │  관제 UI  →  Fleet 서버 │
          │  (모음) 이벤트·상태·pose │
          │  (흩음) REST 명령·릴레이 │
          └────────────┬────────────┘
                       │ 계약만 (envelope)
         ┌─────────────┼─────────────┐
         ▼             ▼             ▼
      rosy_01       rosy_02       rosy_03
      CORE API      CORE API      CORE API
         │             │             │
      localhost     localhost     localhost
      ROS/IO        ROS/IO        ROS/IO
```

- **모음(gather):** 로봇 → 서버. heartbeat, `EventMessage`, swarm pose, capability, 이후 compact 인지 요약.
- **흩음(scatter):** 서버 → 로봇. REST 원자 액션(goal/stop/estop/follow 지정), 릴레이된 참조 pose. 모터 속도 스트림 없음.
- **로봇 간:** DDS 없음. 리더 출력을 팔로워 입력에 잇는 일은 서버(또는 그 전까지 CLI 릴레이)가 한다. 추종 계산은 팔로워 로컬이다.

관제 PC가 꺼져도 각 로봇은 로컬 대시보드·e-stop·deadman으로 안전하다. 사이트 기능만 멈춘다(FLEET SRS 1.2.3, D-5).

## 4. 버스 층 — 영상이 나중에 빠지는 자리

| 층 | 이름 | 범위 | 실체 | 영상 |
|---|---|---|---|---|
| L0 | 제어 | 로봇 안 | localhost CycloneDDS, 50 Hz `cmd_vel`, scan, odom, Nav2 | 안 탐. 인지 evidence만 구독 가능 |
| L1 | 사건 | CORE 프로세스 | EventBus → `/ws/events`, 감사, 이후 FleetAgent | 이벤트 요약만 (`camera.unavailable` 등) |
| L2 | 계약 | 현장 | REST + WS envelope, swarm pose 소켓 | compact 결과만. 원본 프레임 금지 |
| L3 | 인지 | 로봇 안, 선택 | 현재 worker / 이후 `rosy-vision` | 프레임은 여기만. 분리해도 L0 명령권 불변 |

영상 분리는 L3를 별도 컨테이너로 승격하는 일이다(D-41, D-52). 새 사이트 브로커를 만드는 일이 아니다. 관제에서 미리보기가 필요해지면 L2에 저주기 스냅샷 또는 별도 미디어 경로를 두고, 그 경로도 명령을 실을 수 없다.

발행 주기는 소비자에 맞춘다(D-34). 구독자가 없는 원본 영상은 보내지 않는다.

## 5. 메시지 × 역할

| 메시지 | 생산 | 소비 | 층 | 실패 |
|---|---|---|---|---|
| `cmd_vel` | CORE RosBridge만 | 모터 어댑터 | L0 | 게이트 실패 시 50 Hz zero (D-58). 사이트에서 생산 금지 |
| `scan` / `odom` | IO | CORE, Nav2 | L0 | stale면 HOLD. L2로 격자 전체를 상시 올리지 않음 |
| `motor/ready` | 어댑터 | CORE 준비 게이트 | L0 | 만료 시 주행 거절 |
| `EventMessage` | CORE 매니저 | 대시보드, 감사, Fleet | L1→L2 | `since_seq` 갭 필. 순서 위조 금지 |
| swarm pose | 리더 CORE | 릴레이 → 팔로워 | L2 | 끊기면 0 Hz로 읽는다. 마지막 프레임 반복 금지 |
| follow 지정 | Fleet | 팔로워 CORE | L2 | 원자 액션 1회. 폐루프는 로봇 |
| `camera/telemetry` | 인지 | CORE 진단 | L3→L0 | 모션 허가 아님 |
| `Image` | 인지 | 인지만 | L3 | L2 상시 경로 금지 |

Fleet 서버가 나중에 내부 큐를 쓰더라도, 로봇이 말하는 언어는 이 표의 L2 행이다. 로봇 YAML에 브로커 URL을 추가하지 않는다.

## 6. 구현이 이 설계를 깨는 경우

다음이 보이면 머지하지 않는다.

- 로봇 compose에 Kafka/NATS/MQTT/Redis를 “사이트 버스”로 추가
- Fleet 또는 관제 UI가 로봇 `cmd_vel`이나 DDS에 붙음
- 비전 노드가 Command Manager 우선순위 칸을 차지하거나 최종 속도를 냄
- 리더가 팔로워 namespace의 ROS 토픽을 구독
- CORE가 `/dev` 카메라·NPU를 직접 염
- 미션 DSL이 로봇에 들어옴(D-12). 로컬 조작 트랜잭션(D-55)은 별도 ADR 없이 미션 엔진이 되지 않음
- Device 미인수를 이유로 이 패브릭을 GO로 표시

## 7. 전환 순서

Device 검증 계획의 ARTIFACT → DEVICE → FIELD를 이 설계가 앞지르지 않는다.

1. **계약 고정(지금):** 이 문서와 D-59. 역할 표와 메시지 표를 구현 가드레일로 쓴다.
2. **허브 슬라이스:** [실행 계획](2026-09-14-site-middleware-role-fabric.md) — 호스트 역할 가드와 ROS 없는 `SiteHub` gather/scatter. 시뮬 릴레이는 기존 `rosy_fleet`을 재사용한다. 이 단계의 게이트는 hub-slice 호스트 시험이다.
3. **관제 PC listen + UI:** Hub를 프로세스로 열고, UI는 서버만 본다. 로봇 `FleetAgent`는 이때 처음으로 outbound를 연다.
4. **영상 분리(선택):** L3 배치를 Pi에서 비교한 뒤(D-52). 사이트 미리보기는 compact/스냅샷만.
5. **RMW 교체 재검토:** localhost 제어 버스의 계측 문제가 실측될 때만. Zenoh를 로봇 간 버스로 승격하지 않는다.

## 8. 검증

- 역할 가드: 패키지 import 경계 시험이 오케스트레이터 → CORE 내부, 인지 → `cmd_vel` 발행, Fleet → `rclpy`를 거부한다(기존 `rosy_fleet` 경계 시험 확장).
- 메시지 가드: 최종 `cmd_vel` publisher 수 = 1, swarm 릴레이는 바이트 그대로, 스트림 단절은 0 Hz.
- 로컬 우선: Fleet 프로세스 없이 CORE teleop/e-stop 시험이 통과한다.
- 이 설계의 호스트 시험 통과는 Pi 서명 이미지·물리 주행 인수가 아니다.

## 2026-09-26 보충: 사이트 작업 스케줄러와 선택적 브로커

[D-271](../adr/D-271-site-fleet-task-scheduling-and-broker.md)과 [사이트 작업 스케줄링 설계](2026-09-26-site-task-scheduling-and-broker-design.md)는 이 문서의 **Fleet 서버 내부 구현**을 구체화한다. D-59의 로봇 compose 브로커 금지는 유지한다. Fleet은 사용자/API의 허용된 목표를 SQLite 작업 원장에 기록하고, 서버 정책으로 우선순위·장비·자원 점유를 결정한다. 독립 worker 분리 필요가 실측되면 사이트 내부 RabbitMQ를 실행 전달 계층으로 도입한다. 브로커가 생겨도 장비는 기존 CORE REST/WSS 계약을 사용하고 DDS·속도·영상 원본은 큐를 지나지 않는다. 현재 메모리 교통 대기열과 SQLite task history를 영속 우선순위 스케줄러 구현으로 간주하지 않는다.
