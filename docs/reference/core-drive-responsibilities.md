# CORE와 Drive의 현재 책임 구조

2026-10-11, D-625/D-626/D-627. 작업 브랜치의 실제 구조다. 공유 main이나 설치된 로봇에 반영됐다는 뜻은 아니다.

```text
middleware/
├─ core/
│  ├─ api/                           외부 API, 기존 core_api_web 패키지
│  ├─ gateway/core/
│  │  ├─ services.py                 전체 조립, 공통 운용과 listener 순서
│  │  ├─ drive/
│  │  │  ├─ line_follow.py           설정·센서·기하 envelope·복구 배선
│  │  │  └─ docking.py               도킹·군집 조립, Nav2/모드 소유권 연결
│  │  ├─ bridge/                    ROS 입출력과 최종 cmd_vel 발행
│  │  └─ system/                    host/runtime 관측
│  ├─ services/core_features/       기존 알고리즘과 정책; 추가 추출은 후속
│  └─ events/                       사건 계약과 감사
├─ control/drive/planning/nav2/     기존 navigation 패키지와 launch/config
├─ devices/
│  ├─ pinky/                        bringup·description·profile
│  └─ omx/                          adapter·profile·agent; Arm owner 유지
└─ perception/                     센서 근거, 역사적 ROS 패키지명 control
```

| 책임 | 현재 실제 소유자 | 이번 작업 |
|---|---|---|
| 공통 운용·조립 | `core/gateway/core/services.py`, `system/`, `events/` | Drive 도킹/군집 조립을 별도 함수로 분리. 공개 service attribute와 callback 순서 유지 |
| Drive 조립 | `core/gateway/core/drive/{line_follow,docking}.py` | 실제 코드 분리. legacy parser/import facade 유지 |
| 길찾기 | `core_features/navigation`, gateway goal tracker/action transport, `control/drive/planning/nav2` | Nav2 holder 이전. goal facade와 세대/취소 동작 유지 |
| 조향·추종 | `core_features/line_follow`, `swarm`, `localization` | 기존 알고리즘 유지. 별도 control library 추출은 아직 수행하지 않음 |
| 문제·탈출·복구 | `line_follow/recovery`, `localization/mission`, `docking` | 기존 budget, 부모 목표, 취소·실패 출구 유지. 원인별 수명 통일은 CORE 계획 P3 |
| 곡률·몸체 여유 | `command/manager`, `line_follow/{clearance,body_stop}`, `core_common/robot_body`, Drive envelope 배선 | 기존 검사를 유지. cap 후 후보의 기하 동등성 개선은 P2 |
| Base Safety·최종 출력 | `core_features/{command,safety}`, gateway `bridge/{cmd_vel,ros_bridge}` | CORE 단일 최종 writer와 기존 E-stop/readiness/deadman 경계 유지 |
| Arm 제어·Safety | `devices/omx/adapter/omx_adapter` | 경로만 이전. joint/action owner와 stop/rearm/HOLD는 별도 도메인 |
| 장치 조립·기구 모델 | `devices/pinky`, `devices/omx`, `drivers/` | 장치별 holder 분리; package/share/entrypoint identity 유지 |

Drive 조립은 CORE 실행 권한을 연결하는 코드이고 Control backend는 실행할 주행 후보를 만드는 코드다. 이 둘을 같은 폴더명으로 합치지 않는다. CORE의 Base command 모듈을 Arm까지 포괄하는 완성된 공통 제어 계층으로 선언하지 않는다.

곡률 검토는 `v`와 `w`를 독립적으로 제한한 뒤 검사했던 궤적이 달라질 수 있다는 점에서 시작한다. 이동 중에는 부호를 포함한 `w/v`, 제자리 회전에서는 차체 회전 sweep, 후진에서는 뒤쪽 sweep을 각각 검토한다. line-follow envelope가 제공하는 근거를 모든 모드의 검사 완료로 확대하지 않는다. 새 상한이나 자동 탈출 동작은 이번 구조 변경에서 추가하지 않았다.

후속 구현은 [CORE 전체 계획](../plans/2026-10-11-core-responsibility-and-driving.md)의 P1–P3, [이번 Drive 조립 계획](../plans/2026-10-11-core-drive-composition-first.md), [전체 이전 계획](../plans/2026-10-11-platform-structure-migration.md)에 따라 진행한다. 세계 상태와 행동 예측은 별도 계약이며 실행 허가나 Safety 통과를 대신하지 않는다.
