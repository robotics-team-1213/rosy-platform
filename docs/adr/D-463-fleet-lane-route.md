## D-463 차선 경로는 Fleet이 고른 간선 폴리라인을 따라 다음 짧은 점만 보낸다

**Status:** Accepted (2026-10-05, 사용자 결정. 브랜치에 구현하고 로컬 main에 올린다.)

## 배경

- 관제 목표 `POST /api/fleet/robots/{robot_id}/goal` 은 `{x, y, yaw}` 한 점이다. map_v2_fleet 의 점유는 둘레 벽뿐이라 한 점 목표의 Nav2 계획은 빈 바닥을 가로질러 로터리 안쪽을 지날 수 있다.
- 차선 그래프의 `ring_s`·`ring_e`·`ring_n`·`ring_w` 는 반시계 한 방향이다. 간선 id 의 순서가 경로이고, 한 점 목표는 그 순서를 기억하지 않는다.
- D-395: 스냅샷에 `localization` 이 없으면 레거시이고, 그 좌표는 바퀴 오도메트리일 수 있다. `LOCALIZED` 이고 `pose_frame` 이 지도일 때만 그 좌표를 지도로 믿는다.
- 천장 맞춤(D-360·D-375)은 화면 제안이다. 시야·교통·목표의 입력이 아니다.

## 결정

1. **점 목표 스키마는 그대로다.** `GoalRequest` 는 `{x, y, yaw}` 다. 차선 경로는 `POST /api/fleet/robots/{robot_id}/route` 이고 본문은 저장된 간선 id 순서 `edges` 다. 1개에서 8개까지다.

2. **Fleet이 폴리라인을 소유한다.** 간선은 `lane_graph.yaml` 에 있어야 하고, 앞 간선의 `to` 가 다음 간선의 `from` 과 같아야 한다. 점 순서는 그래프에 저장된 방향이다. 모르는 간선은 `ROUTE_UNKNOWN_EDGE`, 이어지지 않으면 `ROUTE_DISCONTINUOUS` 다.

3. **한 번에 보내는 목표는 그 선 위의 다음 점이다.** 자세를 폴리라인에 올린 뒤 약 0.20 m 앞의 점과 그 접선 각을 기존 goal 경로로 보낸다. 먼 교차로를 한 점으로 보내지 않는다. 끝에서 0.05 m 안이면 `ROUTE_COMPLETE` 이고 목표를 보내지 않는다.

4. **지도에 정착된 자세만 보낸다.** 방금 읽은 스냅샷이 `LOCALIZED` 이고 `pose_frame` 이 지도일 때만 보낸다. 레거시(위치 블록 없음), 오도메트리 좌표, 그 밖의 비신뢰, 재시작 유예는 `ROUTE_POSE_UNTRUSTED` 다. 선에서 0.08 m 보다 멀면 `ROUTE_OFF_LANE` 다. 이 응답은 CORE `navigation/goal` 을 호출하지 않는다.

5. **위치를 만들어 주지 않는다.** 이 결정은 AMCL, `initialpose`, ArUco, 천장 맞춤을 로봇 자세로 쓰지 않는다. 위치 상태가 비어 있는 로봇은 이 경로로 움직이지 않는다.

## 결과

- 관제는 차선 순서를 지정하고, 로봇은 그 선의 다음 짧은 점만 받는다.
- 지도 자세가 없으면 경로는 거절된다.
- 수용은 호스트 시험까지다. 돌아가는 사이트 이미지에는 이 경로가 없다. 실차 주행 증거는 없다.

## 검증

- 호스트: `operations/fleet/test/test_lane_route.py`. 통과 수는 `docs/logs.md` 의 이 결정 행에 적는다.
- `ring_s` 시작에서 다음 점은 그 간선 위 0.20 m 이고 SE 교차로가 아니다. `ring_s` 다음 `ring_w` 는 거절된다. 위치 블록이 없거나 `pose_frame` 이 `odom` 이면 목표를 보내지 않는다.
- DEVICE·ROS-SIM·실차 증거는 없다.

## 잇는 결정

D-12, D-395, D-360, D-375.
