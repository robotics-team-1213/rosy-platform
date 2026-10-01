# Fleet 보조 위치 확정 — 설계

**결정:** [D-395](../adr/D-395-fleet-assisted-localization.md) (Proposed).
**상태:** 설계. 코드 0줄, 설정 변경 0건. D-395가 Accepted되기 전에는 구현하지 않는다. S3(실물)은 사용자 승인이 따로 필요하다.
**개정 대상:** D-257 5항, D-393 3항(개정안은 D-395 "개정 제안"). 승인 전에는 원문이 유효하다.

## 1. 문제

map_v2_fleet 트랙은 180° 대칭이다. 2–4대가 사람 입력 없이 항상 올바른 map 자세를 가져야 하는 상황은 셋이다.

| 상황 | 지금 | 목표 |
|---|---|---|
| 전원 투입(슬롯 위든 아무 데든) | `nav2_params.yaml:40-45`가 (0,0,0)으로 시작 | UNKNOWN에서 시작해 사람 없이 LOCALIZED |
| 픽업 뒤 | D-393 3항: 운영자 재초기화 | SUSPECT → 자동 재확정 |
| 거울 잠금 | 로봇은 모름 | Fleet이 감시로 발견해 재중재 |

오버헤드 카메라는 보조 단서일 뿐이고 없어도 동작한다. 로봇이나 트랙에 ArUco를 새로 붙이지 않는다. 기존 카메라 파이프라인의 마커(로봇 상단 40–49, 모서리 30–33)는 보조 단서로 쓸 수 있다.

## 2. 지금 있는 것 (저장소에서 확인)

| 사실 | 위치 |
|---|---|
| 자세 주입 API: `POST /api/v1/localization/initialpose {x,y,yaw}`, `operator` + `NAVIGATE`, 교정 임대(D-321) 중 차단 | `src/runtime/api_web/core_api_web/api/v1/navigation.py:89-109` |
| 발행: `RosBridge.send_initial_pose` | `src/runtime/gateway/core/bridge/ros_bridge.py:576` |
| 공분산 고정 0.5 m / 15° | `src/runtime/services/core_features/navigation/initial_pose.py` |
| 보고 pose는 map TF가 없으면 odom이 대신하고 전송에 프레임 표시 없음 | `ros_bridge.py:214-218` |
| Fleet `RobotClient`에 initialpose 없음 | `src/site/fleet/fleet/swarm/transport.py:108-127` |
| 로봇→Fleet 자세 경로 3개: 콘솔 폴링, 1 Hz 하트비트, `WS /ws/swarm/pose` | `console.py:210`, `fleet_agent/agent.py:152-166`, `transport.py:252` |
| 교통정리·bays는 캐시 자세를 나이·프레임 검사 없이 사용 | `src/site/fleet/fleet/server/traffic.py`, `bays.py` |
| 전역 탐색·픽업 리셋 노드는 있으나 기기 launch 밖이고 유일하지 않으면 확정 안 함 | `src/runtime/sensing/control/localization_node.py:45,94,115` |
| 차선은 `parking` 하나 (-1.27,0)→(-1.0,0) | `src/runtime/sensing/map/map_v2_fleet/lane_graph.yaml` |
| 비대칭 단서: 페인트 맵 맞춤(D-375), 로봇 상단 마커 40–49·모서리 30–33(D-257 8항) | D-375, D-257 |

## 3. 구조

```
 로봇 (Pi)                                                 사이트 (Fleet)
 ┌─────────────────────────────────┐                  ┌──────────────────────────────┐
 │ sensing: LiDAR 전역 탐색          │                  │ localization arbiter (신규)   │
 │   → 후보 [{pose, scan_fit,       │                  │   로봇별 마지막 정상 자세·시각 │
 │            paint_score}],        │                  │   채점 → 결정 / 사다리 진행    │
 │     unmapped_objects             │                  │   상시 감시 (25 cm / 60°)     │
 │ CORE (유일한 외부 관문, D-267)    │ ── 상태·후보 ──▶ │ traffic / bays: LOCALIZED 만   │
 │   상태 기계, 검증(3 s), 미션 실행 │ ◀─ 결정·미션 ── │   믿고, 아니면 넓은 장애물      │
 │   최종 cmd_vel 단독 발행 (D-2)   │                  │ 콘솔: "위치 확인 필요" 표시     │
 └─────────────────────────────────┘                  └──────────────────────────────┘
                                                           ▲ 보조 단서(없어도 동작)
                                                           │ overhead sighting (신선도 ≤ 300 ms)
```

- Fleet은 바퀴를 직접 몰지 않는다. 확인 기동과 귀환은 CORE가 자체 장애물 안전과 E-stop 아래 실행한다.
- 새 부품은 모두 제안이다: sensing 후보 출력, CORE 상태 기계·미션 실행기·검증기, Fleet arbiter, `RobotClient` 확장.

## 4. 메시지

모든 메시지는 CORE를 지난다(D-267 2항, D-269). 필드 이름과 경로는 제안이다. 확정은 구현 단계에서 `docs/reference/ROSY API & Protocol Reference.md` 변경과 함께 한다(이 ADR은 참조서를 고치지 않는다).

### 4.1 로봇→Fleet 위치 확정 상태 (기존 1 Hz `StateSnapshot`에 선택 필드 추가)

| 필드 | 형식 | 설명 |
|---|---|---|
| `loc_state` | `UNKNOWN`\|`CANDIDATES`\|`LOCALIZED`\|`SUSPECT` | 로봇이 소유하는 상태 |
| `pose` | `{x, y, yaw}` | 기존 pose |
| `pose_frame` | `map`\|`odom` | **신규, 명시.** 지금은 odom이 map 대신 들어가도 표시가 없다 |
| `confidence` | 0–1 | 스캔/지도 적합도에서 낸 값. 문턱은 열린 항목 |
| `reason` | 문자열, 선택 | SUSPECT 사유(`pickup`, `fit_drop`, `inject_rejected` 등) |
| `needs_human` | bool, 선택 | 사다리가 시간 초과로 끝남(6절 4단) |

### 4.2 로봇→Fleet 후보 보고 (상태가 바뀔 때)

| 필드 | 설명 |
|---|---|
| `request_id` | 로봇이 정하는 고유 값. 결정이 이 값을 되돌려 준다 |
| `candidates[]` | `{x, y, yaw, scan_fit, paint_score}`. 보통 둘(참 자세와 180° 거울상) |
| `unmapped_objects[]` | 지도에 없는 LiDAR 물체 `{x, y}`(로봇 좌표계, 가설별로 map에 투영해 쓴다). 다른 로봇일 수 있다 |
| `pickup` | 픽업 감지 여부 |
| `stamp` | 로봇 시각 |

### 4.3 Fleet→로봇 결정 (기존 initialpose API 확장)

| 필드 | 설명 |
|---|---|
| `request_id` | 낡은 값은 로봇이 무시한다 |
| `candidate_index` **또는** `pose{x,y,yaw}` | 둘 중 하나. 직접 좌표는 오버헤드나 귀환 기준점에서 온다(사용자 승인) |
| `source` | `candidate`\|`overhead`\|`homing_ref`\|`human` |
| `evidence` | 증거 요약(점수, 관측 로봇 id 등) |
| `expires_at` | 만료된 결정은 로봇이 무시한다 |

기존 `{x, y, yaw}` 호출은 `source: human`으로 읽어 호환을 유지한다(API-002 비파괴 확장).

### 4.4 Fleet→로봇 확인 기동·귀환 미션, 로봇의 답

| 방향 | 메시지 | 필드 |
|---|---|---|
| Fleet→로봇 | 확인 기동 | `request_id`, `type`(`rotate_in_place`\|`nudge_forward`), `max_distance_m`, `max_time_s` |
| Fleet→로봇 | 귀환 미션 | `request_id`, `type`(`wall_to_corner`\|`lane_to_stopline`\|`lane_to_slot`), `max_distance_m`, `max_time_s` |
| 로봇→Fleet | 수락/거절 | `request_id`, `accepted`, `reject_reason`(`path_not_clear`, `estop`, `busy`, `calibration_lease` 등) |
| 로봇→Fleet | 결과 | `request_id`, `done`\|`aborted`\|`timeout`, `converged`(스캔/지도 일치가 3 s 유지됨), `reference`(귀환 기준점 종류, 있으면) |

제안 경로(구현 때 확정; 버전은 API-001에 따라 `/api/v1/` 아래): `POST /api/v1/localization/decision`(4.3), `POST /api/v1/localization/maneuver`, `POST /api/v1/localization/homing`, 후보·결과는 기존 `FleetAgent`의 `event` 봉투로 올린다.

### 4.5 권한

새 capability(`LOCALIZE_ASSIST`, 이름은 제안)를 두고 Fleet의 operator 토큰이 나른다. 사람용 `NAVIGATE` 경로와 분리해 둔다. 교정 임대(D-321) 중에는 이전과 같이 막는다. 토큰·역할 모델의 변경 범위는 열린 항목이다.

## 5. 로봇 상태

```
                  전원 투입 / 재시작
                         │
                         ▼
                    ┌─────────┐   후보 생성(전역 탐색)    ┌────────────┐
                    │ UNKNOWN │ ────────────────────────▶ │ CANDIDATES │
                    └─────────┘                            └────────────┘
                         ▲                                   │      ▲
                         │ 전원 재투입                         │      │ 검증 실패(3 s) /
                         │                                   │      │ 결정 만료
                         │                                   ▼      │
                    ┌─────────┐   픽업 / 적합도 하락    ┌───────────┐  결정 수락 +
                    │ SUSPECT │ ◀──────────────────────│ LOCALIZED │◀─ 3 s 검증 통과
                    └─────────┘                         └───────────┘
                         │   후보 재생성                      ▲
                         └───▶ CANDIDATES ──────────────────┘
```

- 자율 주행(Nav2 목표, 차선 유지)은 LOCALIZED에서만 한다. 수동 원격 운전, 확인 기동, 귀환 미션은 UNKNOWN·CANDIDATES·SUSPECT에서도 허용한다(귀환은 map 프레임이 필요 없는 행동만 쓰기 때문).
- UNKNOWN은 전원 투입 직후 항상 처음이다. `set_initial_pose`의 (0,0,0)은 상태를 LOCALIZED로 만들지 않는다.
- UNKNOWN과 SUSPECT는 후보 생성 후 CANDIDATES로 간다. SUSPECT에서는 직전 자세를 근거 없이 버리지 않고 채점의 "마지막 정상 자세" 단서(픽업 없을 때만)로 쓴다.
- LOCALIZED 진입은 결정 주입 뒤 스캔/지도 일치가 3 s 유지될 때만이다. 진입 직후 진행 중이던 Nav2 목표는 취소하고 재계획한다.
- 사다리가 시간 초과하면 상태는 바뀌지 않는다(CANDIDATES 또는 SUSPECT 그대로). 로봇은 정지하고 `needs_human` 표시만 올라가 콘솔이 "위치 확인 필요"를 보인다. 사람의 `source: human` 결정도 같은 3 s 검증을 거친다.
- Fleet이 죽어도 상태를 유지한다: LOCALIZED면 계속하고 아니면 멈춰 있는다.

## 6. 에스컬레이션 사다리

| 단 | 행동 | 허용 조건 | 성공 | 실패 시 |
|---|---|---|---|---|
| 1 | 중재: 후보 채점(7절). 1등이 2등을 뚜렷이 앞서고 2 s 유지 | 후보 보고 수신 | 결정 전송 → 로봇 검증 → LOCALIZED | 2로 |
| 2 | 확인 기동: 제자리 회전 또는 몇 cm 전진 후 재중재 | LiDAR가 경로 비움을 보임(로봇이 판정, 자동 허용). `max_distance`·`max_time` 제한 | 후보 격차가 벌어져 1로 | 3으로 |
| 3 | 귀환: `wall_to_corner` 또는 `lane_to_stopline`/`lane_to_slot`. CORE가 자체 장애물 안전·E-stop으로 매우 느리게 실행 | 로봇 수락. Fleet이 교통정리·양보로 다른 로봇을 비켜 둠 | 기준점에서 후보가 갈라지고(다른 로봇·페인트로 가림) 직접 좌표나 후보 결정 → 검증 | 4로 |
| 4 | 정지, 콘솔 "위치 확인 필요". 사람은 이 경우에만 개입 | 사다리 전체 시간 초과 | 사람이 재초기화(`source: human`, 같은 3 s 검증) | 정지 유지 |

- 귀환의 기준점(벽 모서리)은 180° 대칭이라 두 거울 후보에서 똑같이 보인다. 모서리 도착만으로는 갈리지 않고, 그 자리에서 다른 로봇·페인트 단서가 후보를 가른다. 그래서 귀환은 "단서를 얻으러 가는 행동"이고 자세를 만드는 행동이 아니다.
- 사다리 각 단의 시간·거리 한도는 초기값을 sim에서 정한다(열린 항목).

## 7. 채점 단서

초기값은 sim에서 조정한다. 수치로 정해진 것은 슬롯 10 cm / 20°, 오버헤드 신선도 300 ms, 유지 시간 2 s뿐이고 가중치와 격차 문턱은 S1·S2 결과로 정한다.

| 단서 | 효과 | 초기 규칙 | 비고 |
|---|---|---|---|
| 스캔/지도 적합도 `scan_fit` | 기본 점수 | 후보 보고값 그대로 | 대칭 맵에서 거울 후보끼리는 거의 같다 |
| 페인트 일치 `paint_score` | 가산 | 기대 페인트(가설 자세에서 `lane_graph`/D-375 페인트)와 D-356/keep 차선 마스크의 일치 | 대칭을 깨는 주 단서. Pi 비용은 열린 항목 |
| 다른 LOCALIZED 로봇 일치 | 가산 | 그 가설에서 투영한 `unmapped_objects`가 다른 LOCALIZED 로봇의 보고 자세와 일치 | |
| 있어야 할 로봇이 안 보임 | 감점 | 그 가설에서 LiDAR 시야 안에 있어야 할 LOCALIZED 로봇이 `unmapped_objects`에 없음 | 시야·가림 계산 필요 |
| 출발 슬롯 사전 | 큰 가산 | 후보가 슬롯의 10 cm / 20° 안 | 별도 경로 아님. 슬롯 밖은 같은 절차로 푼다 |
| 마지막 정상 자세와 가까움 | 가산 | **픽업이 없었을 때만** | 픽업 뒤에는 쓰지 않는다 |
| 오버헤드 sighting과 가까움 | 가산 | sighting이 300 ms보다 신선할 때만. `quality`는 null이라 가중은 작게 | 카메라 없으면 항목 없음(S4) |

**결정 규칙:** 최고 점수가 2등과 문턱 이상 벌어지고 그 상태가 2 s 유지될 때만 결정을 낸다. 어느 단서도 단독으로 결정하지 않는다(마지막 정상 자세만으로 결정하는 경로는 두지 않는다).

## 8. 상시 감시 (LOCALIZED 중)

| 주체 | 조건 | 결과 |
|---|---|---|
| 로봇 | 픽업 감지(바퀴 미끄러짐 또는 IMU 기울기), 스캔/지도 적합도의 지속적 하락 | SUSPECT, `reason`과 함께 후보 보고 |
| Fleet | 오버헤드나 다른 로봇의 관측이 보고된 자세와 25 cm 또는 60° 넘게 1.5 s 어긋남 | 그 로봇을 SUSPECT로 표시하고 재중재 요청. 거울 잠금을 여기서 잡는다 |

카메라가 없으면 Fleet 감시는 다른 로봇의 관측만 쓴다. 혼자 있는 로봇의 거울 잠금은 카메라와 페인트 없이는 이 감시로 못 잡는다(로봇 쪽 `paint_score`와 적합도 감시에 의존. 한계로 기록한다).

## 9. 안전

- LOCALIZED가 아닌 로봇은 Fleet 교통정리가 **넓은 장애물**로 다룬다. 다른 로봇은 피하거나 멈춘다.
- 교통정리·bays는 `pose_frame`이 `odom`이거나 `loc_state`가 LOCALIZED가 아닌 자세를 무시한다.
- 최종 `cmd_vel`은 CORE 하나다(D-2). 확인 기동·귀환도 CORE가 낸다. 이 때문에 위치를 모르는 로봇이 움직여도 CORE의 장애물 정지, 최대 거리·시간, E-stop 안에서만 움직인다.
- 모든 주입(`candidate`, `overhead`, `homing_ref`, `human`)을 로봇이 3 s 안에 스캔/지도 일치로 검증한다. 실패하면 거부하고 사유와 함께 SUSPECT. 출처는 로그·이벤트(`localization.initialpose`의 `source`)에 남긴다.
- 로봇은 낡은 `request_id`와 만료된 결정을 무시한다.
- Fleet이 죽었을 때 로봇은 마지막 상태를 유지한다.

## 10. 출발 슬롯

- map/site 설정에 방향이 있는 번호 슬롯 4개 `{id, x, y, yaw}`를 둔다(위치는 열린 항목, 이 설계는 기하를 정하지 않는다).
- 슬롯은 채점의 사전 정보다. 별도 경로가 아니다. 슬롯 밖에 놓인 로봇도 같은 사다리로 푼다.
- 현재 `parking` 차선(`lane_graph.yaml`)은 약 2대만 들어가 4슬롯을 만족하지 못한다. 슬롯 배치(주차 차선 확장인지 트랙 위 별도 구역인지)는 지도·현장 결정이고 이 문서의 범위 밖이다.

## 11. 시험

| 단계 | 환경 | 시나리오 | 통과 기준 |
|---|---|---|---|
| S1 | sim, 로봇 2대 | 슬롯 출발; 슬롯 밖 출발; 강제 거울; 주행 중 픽업 | 사람 입력 0, 모두 LOCALIZED 도달, 거울 잠금 0 |
| S2 | sim, 로봇 4대 | S1과 같음 + 동시 재중재, 교통 속 귀환 | 위와 같고 충돌 0 |
| S3 | 실물 2대, 저속 | S1 시나리오 | 사용자 승인 뒤에만. 모션은 승인 필요 |
| S4 | 오버헤드 카메라 보조 | 카메라 켬/끔 비교 | 동작이 같다 |

S1·S2는 ROS-SIM 이하이며 기기·현장 합격이 아니다.

## 12. 범위 밖

- 로봇 설정·params의 지금 변경(`nav2_params.yaml` 등).
- 카메라의 연속 EKF 융합.
- AMCL 안의 로봇 간 LiDAR 우도.
- 새 ArUco 부착.

## 13. 열린 항목

| 항목 | 막는 것 | 어떻게 푸나 |
|---|---|---|
| 출발 슬롯 기하(4개) | 7절 슬롯 가산, S1 | 현장 지도 결정. `parking` 차선은 약 2대분 |
| Pinky 픽업 감지 신호(IMU 유무, `safety/pickup` 기기 발행) | 5·8절 SUSPECT 진입 | 기기에서 확인(IMU 출력 없음 기록이 D-384에 있음). 없으면 바퀴 미끄러짐·적합도 하락만 |
| 페인트 점수의 Pi 비용 | 7절 | Pi 실측 |
| 점수 문턱·시간 한도 | 6·7절 | S1·S2에서 조정 |
| API 경로·버전, 새 capability 이름 | 4절 | 구현 변경에서 API 참조서와 함께 확정 |
| 직접 좌표 공분산 | 4.3 | 출처별 다르게 둘지 |
| Fleet operator 토큰의 새 capability 부여 방식 | 4.5 | 역할 모델 변경 범위 확인 |
| 귀환 `lane_to_slot`/`wall_to_corner`의 CORE 실행기 | 6절 | CORE에 map 프레임 없는 주행 행동이 이미 어디까지 있는지 조사 |

## 14. 구현 순서 제안 (승인 뒤)

1. 상태 필드·`pose_frame` 추가와 교통정리·bays의 무시 규칙 (가장 작고 독립적, 지금의 odom-as-map 위험을 먼저 줄인다).
2. sensing 후보 출력(유일 해 거부 → 후보 목록).
3. CORE 상태 기계, 3 s 검증, 결정 API 확장.
4. Fleet arbiter와 `RobotClient` 확장, 콘솔 표시.
5. 확인 기동, 귀환 미션.
6. S1 → S2 → (승인) S3 → S4.
