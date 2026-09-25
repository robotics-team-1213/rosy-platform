# 모듈 결합도 평가 보고서

> 후속: `module-coupling-scorecard.md` (2026-09-23) — 5축 루브릭(독립 작업성·역할 명확성·동시 유지보수성·공용 관리·결합 정합)으로 재채점한 평가표.

작성일: 2026-09-19 / 대상: `Rosy OS/src` 작업 트리 (6개 도메인, 19개 패키지)
범위: `package.xml` 선언 의존 + 비테스트 Python import + ROS 토픽/서비스 + launch/deploy 참조.
주의: 평가 시점 작업 트리는 `origin/main` 대비 대량 개명(rosy_* → 도메인 그룹) 중인 상태이며, 본 평가는 작업 트리 기준이다.

## 1. 현재 구조 요약

- `src/core`: `core`, `core_common`, `core_events`, `core_features`, `core_api_web`, `interfaces`
- `src/apps`: `control`(302 py), `emotion`(11), `games`(44), `omx_adapter`(7)
- `src/hardware`: `bringup`(16), `led`(7), `imu_bno055`/`sensor_adc`/`lamp_control`(C++)
- `src/navigation`: `navigation`(7) / `src/sim`: `description`, `gz_sim`(9) / `src/site`: `fleet`(41)

## 2. 선언 의존 (`package.xml`) — Efferent

| 패키지 | 선언 의존 (요약) |
|---|---|
| `core` | `core_api_web, core_common, core_events, core_features` + `interfaces, rclpy, nav_msgs/geometry/sensor/std, tf2, nav2_msgs, slam_toolbox` |
| `core_api_web` | `core_common, core_events, core_features` |
| `core_features` | `core_common, core_events` |
| `core_events` | `core_common` |
| `core_common` | 없음(leaf) |
| `control` | `rclpy, geometry/nav/sensor/std/visualization, tf2` + `nav2_*, slam_toolbox, numpy/opencv/yaml` — `core`/`interfaces` 없음 |
| `fleet` | `core`에 `exec_depend` + `fastapi/httpx/uvicorn/websockets/yaml` |
| `navigation` | `nav2_bringup, navigation2` + `bringup`에 `exec_depend` |
| `gz_sim` | `gz_ros2_control, ros_gz` + `fleet`에 `exec_depend` |
| `bringup` | `rclpy, geometry/nav/sensor/std, tf2, launch, xacro, sllidar_ros2` — `core`/`control` 없음 |
| `emotion/led` | `interfaces, rclpy` / `lamp_control/sensor_adc/imu_bno055` | C++ `rclcpp(+realtime_tools)`, `lamp_control`만 `interfaces` |
| `games/omx_adapter` | ROS 없음 (`httpx/websockets/yaml` 수준) |

판정: `core_*` 5개는 `common ← events ← features ← api_web ← core` 단방향 DAG로 선언상 사이클 없음. 양호.

## 3. 실제 코드 결합 (비테스트 Python import)

- `runtime/control → core_*`: **0건**. `control` 내부 import만 존재. 선언과 일치하며, 흡수 원칙(CORE가 최종 명령 소유, control은 증거 생산) 유지.
- `runtime/core → control`: `runtime/core/core/bridge/control_sensor_adapter.py` 1개 파일에서 `control.calibration_snapshot`, `control.control.command_gate`, `control.safety.node` import. **선언(`package.xml`)에는 `control`이 없음 = 미선언 결합.** opt-in 어댑터 의도와 일치하나 빌드 순서·단독 빌드 시 깨짐.
- `core_api_web → core_features/core_common`: v1 12개 모듈이 `command.arbitration, navigation.manager, docking.database, diagnostics.collector, maps, swarm, waypoints` + `protocol.schemas, config, identity`를 직접 참조. 선언과 일치하나 fan-out 최대(약 12개 하위 모듈).
- `core_features → core_common`: `protocol.schemas/evidence`로만 수렴. 양호(스탬프 결합 수준).
- `core_events → core_common.protocol.schemas`만. 양호.
- `site/fleet → core_common.protocol.schemas`: `hub/hub.py`, `hub/registry.py`, `swarm/arming.py`, `swarm/session.py`, `swarm/transport.py` 5개. `package.xml`은 `core`에 걸려 있으나 실제 코드는 `core_common` 스키마에만 의존 = **선언이 실제보다 넓음**.
- `sim/gz_sim → fleet + navigation`: `scripts/swarm_bench.py`가 `fleet.formation.geometry, fleet.swarm.{robots,session,transport}`, `launch/gz_multi.launch.py`가 `navigation.frame_prefix` 참조. 시뮬이 함대·내비에 직접 결합.
- `apps/emotion → interfaces.srv`, `hardware/led → interfaces.srv`, `lamp_control.cpp → interfaces` — IDL 경유 결합으로 양호.
- `games`, `omx_adapter`: 도메인 내부 import만. 완전 분리. 양호.

## 4. ROS 통신 결합

- 최종 `cmd_vel` 발행은 1곳: `src/runtime/core/bridge/ros_bridge.py` (`create_publisher(Twist, "cmd_vel")`). 단일 발행자 원칙 유지.
- `control`은 `cmd_vel_raw`, `wander/cmd`, `calib/*`, `camera/*` 발행, `scan/odom/imu_raw/us_sensor` 구독. 단, 레거시 잔재 2곳이 최종 토픽을 **구독**함:
  - `src/runtime/control/control/web_node.py:431` — `create_subscription(Twist, 'cmd_vel', ...)`
  - `src/runtime/control/control/wander/node.py:36` — 동일 패턴
  - 발행은 아니나, 운영 시 CORE와 동일 토픽명을 소비하는 이중 결합이므로 정리 대상.
- `bringup`은 `cmd_vel` 구독(`TWIST_SUB_TOPIC_`) + `odom/joint_states/motor/ready` 발행. `navigation/hardware.launch.py → bringup`, `bringup_robot.launch.py → description/sllidar` 로 launch 결합은 하드웨어 방향으로만 흐르고 `core`를 포함하지 않음. 양호.
- `emotion`은 `display/info`, `power/mode`(CORE 발행) 구독 — 단방향 관측 결합. 양호.
- `fleet` 런타임은 ROS 토픽 직접 의존 없음(스키마 import 수준). `gz_sim` 벤치만 fleet 로직을 import.

## 5. Launch / Deploy 결합

- launch 포함 방향: `navigation/hardware → bringup`, `gz_multi → description/navigation/gz_sim`, `core launch → core` 단일, `control launch → control/slam_toolbox`. 패키지 경계를 넘나드는 포함은 `navigation→bringup`, `gz_sim→navigation/fleet` 2계열뿐.
- `deploy/robot/compose.yaml`: `core/bringup/navigation` 3 서비스를 한 파일에서 렌더. `device_readback.py/install-pi.sh`는 `core` 참조, `verify-motors.sh`는 `bringup` 참조. 배포층이 3개 런타임 패키지에 fan-out하는 구조로, 런타임 패키지 간 직접 의존보다 느슨함. 적정.

## 6. 결합도 등급

| 경계 | 수준 | 등급 | 근거 |
|---|---|---|---|
| `core_common/events/features/api_web` 층 | 스탬프/데이터 | A(낮음) | 하향 DAG, 스키마 공유로 제한 |
| `core → control` 어댑터 | 제어+내용 혼합 | C(주의) | 미선언 import 3건, 1파일 집중. 정책 교체 시 무효화 로직과 얽힘 |
| `control → 외부` | 데이터 | A | CORE import 0, 증거 토픽으로만 발신 |
| `fleet → core_common` | 스탬프 | B(보통) | 실제는 스키마 1점이나 선언은 `core` 전체 |
| `gz_sim → fleet/navigation` | 내용(직접 import) | C | 시뮬 스크립트가 함대 내부 모듈명 직접 참조 |
| `core_api_web fan-out` | 스탬프 다발 | B | 12개 라우터가 features 하위 7개 영역 참조, 변경 전파 반경 큼 |
| `레거시 cmd_vel 구독 2건` | 외부(토픽명 공유) | C | 단일 발행자 원칙과 충돌 가능, 운영 launch 미포함 확인 필요 |
| `games/omx/emotion/led` | 분리/IDL | A | 독립 또는 `interfaces` 경유 |

종합: **아키텍처 방향성은 유지되나, 미선언 1곳 + 레거시 구독 2곳 + 시뮬 직결 1곳이 결합도 상위 리스크**다.

## 7. 조치 제안 (우선순위순)

1. `src/runtime/core/package.xml`에 `control` `exec_depend` 추가 **또는** 어댑터를 `core_features`/`core_api_web`과 같은 명시 경계로 이동. 현 상태는 빌드·패키징이 코드 실체를 거짓말함. (`runtime/core/core/bridge/control_sensor_adapter.py`)
2. `web_node.py:431`, `wander/node.py:36`의 `'cmd_vel'` 구독을 `cmd_vel_raw`/`session` 계열로 개명하거나 삭제하고, 운영 launch에 포함되지 않음을 계약 테스트로 고정.
3. `fleet` `package.xml`의 `exec_depend: core`를 `core_common` 수준으로 축소 검토(실제 import와 일치). 중앙 Fleet 서버 미구현 상태와 정합.
4. `gz_sim/scripts/swarm_bench.py`의 `fleet.swarm.*` 직접 import를 CLI/스키마 경유로 전환하거나, 시뮬 전용 스텁으로 격리.
5. `core_api_web/api/v1/*`의 `core_features.*.manager` 직접 참조를 `deps` 파사드(`api/deps.py`) 뒤로 통합해 fan-out 계수 축소.

## 8. 검증에 사용한 명령

- `package.xml` 19개 파싱 (1.항 표)
- 비테스트 import 스weep 스크립트 2종 (`coup1/coup4`, `X:\DevTemp\opencode\` — 임시 분석용, 저장소 미포함)
- `cmd_vel` 발행/구독 grep + launch `get_package_share_directory` 추출 (`coup2/coup3`)

재현 시 `Rosy OS` git 루트가 아닌 본 폴더 기준으로 위 스크립트를 재실행하면 된다.

## 9. 조치 이행 상태 (2026-09-21, Rosy OS 커밋 23025fe..ab9d349 및 후속)

| # | §7 조치 | 상태 |
|---|---|---|
| 1 | core→control 미선언 import | **해결** — 정적 import 자체를 제거(D-126 `rosy.sensor_provider` 엔트리포인트). `exec_depend` 추가 불필요 |
| 2 | `cmd_vel` 레거시 구독 2건 | **해결** — `web_node`/`wander` 모두 `cmd_vel_raw` 구독으로 개명 완료 |
| 3 | `fleet` 선언 축소 | **해결** — `exec_depend core_common` + `test_depend core_features`로 선언=실제 |
| 4 | `gz_sim→fleet` 내용 결합 | **해결** — D-148: `fleet.bench` 공개면 신설, `swarm_bench` 전환, gz_sim 구조 테스트로 고정 |
| 5 | `core_api_web` fan-out | **해결** — v1 라우터 9개 파일 12건 직접 import를 `api/deps` 재수출로, `test_v1_import_boundary.py`로 고정 |

추가 이행: 도메인 재그룹 소급 공식화(D-147), control 단독 모드 최종 발행 계약(D-149, **Accepted** — 2026-09-21 구조적 구성 증거로 승격: core 이미지 control 미복사 + 배포 launch 폐쇄의 control 실행파일은 증거 생산 3종뿐 + 계약 테스트 6종. 실물 readback은 상시 DEVICE 게이트 확인 항목), `web_node` 디버그 서피스 잔류 + 맵 단일 홈 `navigation/map`(D-150), 깨진 레거시 launch 참조(`pinky_imu_bno055`, `lcd_control`) 수정, deploy 설정의 디버그 포트(28161/28162) 부재 가드.

새 계약 테스트 5종(벤치 경계, 파사드 동일성, v1 경계, launch 마커, 디버그 포트)은 전부 변이 증명 완료(망가뜨림→적색→복구→초록). 잔여: §6의 `bringup` `cmd_vel` 구독은 최종 소비(deadman)로 정상, `emotion`/`led` IDL 경로는 정상 — 열린 항목 없음.
