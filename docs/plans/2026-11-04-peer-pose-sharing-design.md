# 로봇 간 맵 위치 공유(peer pose sharing) 설계

Date: 2026-11-04
Status: Proposed (실행 계획은 별도 문서. 구현 승인 전 코드 변경 없음)

## 1. 목표와 배경

천장 카메라(탑뷰)가 죽거나 없는 현장에서도 로봇들이 **서로의 맵 상 위치를 직접 교환**해,
World `arbitrated_pose`·교통 판단·군집이 위치 사실을 유지하게 한다.

- 2026-10-31 관제 점검 기록: 천장 카메라는 마커 40/41만 인식하고 추적 설정 읽기도
  실패한다. 카메라가 사라지면 sighting 앵커가 없어 `MapPoseTracker`는 UNKNOWN으로
  떨어진다(`operations/world/src/rosy/world/state/projections/map_pose.py`).
- 각 로봇은 이미 D-395로 자기 맵 위치(`LOCALIZED`, `pose_frame: map`)를 CORE가 알고
  있다. 없는 것은 "다른 로봇 위치의 전달 채널"과 "그걸 sighting으로 받아들이는 규칙"뿐이다.

## 2. 이미 있는 조각 (재사용)

| 필요 | 기존 자산 |
|---|---|
| 자기 맵 위치 | CORE D-395 `localization`(`GET /api/v1/robot/state`) |
| 로봇 간 신뢰 | peer-pairing(D-456/535): 세션·승인 코드·CA 넘김·속도 한도·관계당 세션 상한 |
| 서로 찾기 | 기기 avahi 광고(관제 `mdns-bridge`가 소비하는 같은 TXT) |
| 위치 집계·소비 | World `MapPoseTracker`(sighting 앵커 + odom 브리지, 순수 모듈, D-494 3), Fleet `arbitrated_pose` 소비 |
| 물리 충돌 회피 | 각 로봇 costmap이 상대를 장애물로 관측 — 통신과 무관하게 이미 동작 |

## 3. 범위 밖 (하지 않는 것)

- 통행권·trip lease·임무 판단의 분산. 권한은 Fleet 중앙 그대로(D-517, D-541).
  로봇끼리 주고받는 것은 **위치 사실**뿐이다.
- 로봇 간 ROS/DDS 도메인 통합·멀티캐스트 ROS. D-33 분리 유지, CORE만 게이트웨이.
- 카메라 대체가 아니라 보강. sighting 우선순위에서 카메라가 계속 위다.
- LiDAR 교차검증(상대가 주장한 좌표 근처의 동적 장애물 관측 일치)은 2차 후보로 별도 제안.

## 4. 설계

### 4.1 Beacon 송신 (CORE)

CORE 안 백그라운드 루프(기존 타이머 패턴, 신규 프로세스 아님)가 매 1 Hz(기본,
`peers.rate_hz`)에 자기 beacon을 등록된 peer CORE로 `POST`한다.

```
{schema: 1, robot_id, map_id, pose: {x, y, yaw},
 localization: {state, pose_frame}, stamp, boot_id, seq}
```

- `LOCALIZED`가 아니면 `pose` 없이 `localization.state`만 보낸다(수용측은 앵커로 쓰지 않는다).
- 크기 약 300 B. 6대 기준 초당 5회 왕복 — 대역폭·CPU 무시 가능.

### 4.2 발견과 신뢰

- **발견 v1**: 설정 목록(`rosy.yaml` `peers: [{host: rosy-pinky-<id>.local}]`).
  avahi 자동 발견은 기체 측 avahi-utils 가용성을 확인한 뒤 확장한다(열린 결정 1).
- **인증**: 기존 peer-pairing(D-456) 세션을 재사용하고, beacon 전용 부여 유형
  `peer-robot`을 추가한다. 권한은 `POST /api/v1/peers/beacon`과 자기 상태 주장뿐
  (operator 이하, 정지·구동 접근 없음). 세션 수명·폐기·속도 한도·승인 화면은 기존 규칙 그대로.
- **TLS**: 기존 기기 인증서·CA, 출발지 규칙(D-944) 그대로.

### 4.3 수용 (CORE peers 테이블)

- 수신: `POST /api/v1/peers/beacon`(`peer-robot` 세션만; 세션 없으면 401).
- `robot_id`는 **세션 주체**에서 취하고 본문 self-claim은 무시한다(위조 방지).
- 검증: `seq` 단조, `map_id` 기록(비교용), 수신 시각. 마지막 수신이 5 s(연속 5회 유실)를
  넘기면 항목을 제거한다.
- 노출: `GET /api/v1/peers`(Viewer). 대시보드·Pilot 표시와 4.4의 Fleet 보고가 소비한다.

### 4.4 World/Fleet 연결 (sighting `source: peer`)

- `FleetAgent`가 주기 상태 보고에 `peers` 스냅숏을 덧붙인다(기존 1 Hz heartbeat 경로).
- Fleet은 각 peer 항목을 World `MapPoseTracker`에 sighting(`source: "peer:<reporter>"`)로
  투입한다. 앵커 페어링(`max_pair_s`)·odom 브리지 한계(`max_dead_reckon_m`,
  `max_bridge_turn_deg`)·불일치 `RECOVER_AFTER`·재부팅(boot_id 변경) 시 UNKNOWN 후
  재앵커 — **기존 규칙을 그대로 재사용**한다.
- sighting 우선순위: **카메라 > 운영자 핀 > peer**. 카메라가 돌아오면 카메라 sighting이
  앵커를 다시 잡는다(현재 동작 유지).
- 같은 `map_id`만 앵커 후보(D-13). 다른 맵의 peer는 표시만 하고 앵커로 쓰지 않는다.

**v1 실행 범위** (`feat/peer-pose-sharing`): 4.1–4.3(beacon·수용·`GET /api/v1/peers`)과
`StateSnapshot.peers` — 하트비트(1 Hz)가 Fleet까지 실어 나르는 것까지를 싣는다. World의
peer sighting 중재는 v2다: peer 보고가 로봇 B의 odom 표본과 짝 지어 앵커가 되려면
`max_pair_s`(0.25 s) 창이 1 Hz 릴레이 지연을 견디지 못해, 릴레이된 자기위치 스트림에 맞는
앵커 규칙이 별도로 필요하다(열린 결정 4).

### 4.5 실패·저하 동작

- peer 없음·통신 단절: 오늘과 동일(카메라 또는 UNKNOWN). 저하가 아니라 상태 보존.
- peer 주장이 틀린 경우(맵 드리프트): odom 브리지·불일치 규칙이 기존대로 UNKNOWN으로
  내린 뒤 다음 일관 sighting에 재앵커한다.
- Fleet 단절: 로봇 간 beacon은 계속되고(4.1~4.3은 Fleet 불필요) 각 로봇 대시보드는
  서로를 본다. `arbitrated_pose`는 Fleet이 살아날 때 갱신된다.

## 5. 시험 계획

1. **순수/호스트**: beacon 직렬화, peers 테이블(갱신·제거·`map_id` 필터·`seq` 단조),
   인증(세션 없음 401, `peer-robot` 권한 경계), `FleetAgent` peers 첨부, World
   peer-sighting 앵커/브리지/불일치 — ROS-free pytest.
2. **계약**: API Reference와 `contracts/foundation/core_common/protocol/schemas.py`
   동시 갱신(D-18). architecture guard — 새 `cmd_vel` 경로 없음, 로봇 간 ROS 크로스
   도메인 없음.
3. **ROS-SIM/LOCAL**: 두 CORE 인스턴스(네임스페이스 분리)로 beacon 교차·peers 테이블·
   World peer 앵커 확인.
4. **실물(별도 DEVICE 등급)**: 두 기체 LAN에서 beacon 교차, 카메라 비활성 상태에서
   `arbitrated_pose`가 UNKNOWN으로 떨어지지 않는지.

## 6. 수용 기준 (제안)

카메라 비활성 상태에서 (a) 각 로봇이 타 로봇 위치를 `GET /api/v1/peers`로 본다,
(b) Fleet `arbitrated_pose`가 peer 앵커로 유지된다, (c) 카메라 복귀 시 카메라 앵커로
돌아간다, (d) beacon 끊기면 규정 시간 안에 UNKNOWN으로 내려간다.

## 7. 열린 결정

1. avahi 자동 발견 확장 여부(기체 측 avahi-utils 가용성 확인 후).
2. beacon 주기 설정 노출(`peers.rate_hz`, 기본 1) — 고정값으로 시작할지.
3. tailnet 경로(D-477) 지원 시점 — LAN 불가 현장용, v2.
4. World가 peer 보고를 `arbitrated_pose`에 넣는 앵커 규칙 — 카메라 sighting의 odom
   짝짓기(`max_pair_s`)는 릴레이된 자기위치 스트림에 맞지 않으므로 v2 설계가 필요하다.

## 8. 기존 결정과의 관계

| 결정 | 관계 |
|---|---|
| D-2 (cmd_vel 단일 발행자) | 무관·무변경 (위치 사실만 교환) |
| D-33 (로봇별 도메인 분리) | 유지 — ROS 그래프 공유 없음 |
| D-456/535 (peer-pairing) | 세션·인증 재사용, 부여 유형만 추가 |
| D-494 3 (MapPoseTracker) | sighting 소스에 `peer` 추가, 규칙 재사용 |
| D-517/541 (통행권·lease 중앙) | 유지 — 권한 분산 없음 |
| D-18 (스키마·API 문서 동시) | 구현 시 준수 |
| D-427/429/430 | 구조 변경 없음(새 최상위 폴더 없음) |

신규 ADR은 실행 계획 수립 시 `adr_reserve.py`로 예약한다.
