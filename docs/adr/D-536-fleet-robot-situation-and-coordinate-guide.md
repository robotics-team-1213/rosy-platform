## D-536 Fleet 로봇 상황과 좌표 안내 — 몸체 원·방향·불확실성 고리를 그리고, 문제마다 좌표가 붙은 안내를 낸다

**Status:** Accepted (2026-10-09, 사용자 요청: "fleet 에서 각각의 로봇의 위치 그리고 방향등을 오버레이를 통해서 표현해주고 원과 함께 … 이것들이 문제가 생기거나 이러면 그걸 통해서 해결하게 하는 가이드 … 미리 좌표나 이런걸 알고 있다가 바로 처리할 수 있게 하는 파이프라인"). 단계 G1(읽기와 표시)만 구현. 로봇에 아무것도 보내지 않는다.

잇는 결정: [D-494](D-494-fleet-trip-execution-m2-contracts.md)(지도 자세 중재) · [D-457] Rosy Cam 추적 · [D-493](D-493-fleet-console-map-first-layout.md)(지도 먼저, 예외 큐 규칙 하나) · [D-511](D-511-fleet-lane-compliance-watch.md)(차로 여유) · [D-517](D-517-multi-robot-lane-traffic.md)(u, 구역) · [D-424](D-424-one-robot-body-for-every-near-check.md)(몸체) · [D-525](D-525-virtual-signal-fleet-zone-gate.md)(신호 구역) · [D-359](D-359-theme-ready-tokens-shared-controls-and-responsive-tiers.md)(토큰).

### Context

2026-10-09 새벽 실제 현장 관제(현장 PC, 버전 3 지도)를 직접 열어 보았다.

- 카메라 화면에 로봇 셋이 보이는데 추적은 0대(`NO_POSE`)였다. 로봇이 매트 위에 있을 때 배경을 배워 로봇이 배경이 됐다.
- 두 로봇 odom이 "미래" 시각으로 버려져(`odom_refused_reason: future`) 지도 자세가 둘 다 `UNKNOWN`이었다. 로봇 시계가 관제 PC보다 앞선다.
- 카메라·사이트 보기(`drawSiteView`)는 로봇 자세를 그리지 않는다. 격자 보기만 작은 삼각형을 그린다. 몸체 원, 불확실성, 지도 자세 상태(`/map-pose`)를 화면이 읽지 않는다.
- 문제 감지는 여러 곳(D-407, D-438, D-511, trip, D-517 handover, D-395)에 흩어져 있고, 예외 큐는 글만 있다. 한 지도 자세에 대해 차로·s·옆 벗어남·방향 오차·다음 장소를 한 번에 내는 곳이 없다.

### Decision

1. **로봇 상황 기록(순수, `fleet/guide/situation.py`).** 로봇마다: 지도 자세(`LOCALIZED`/`DEGRADED`만 그린다), 출처, 불확실성 u(= 0.12 + 0.05 × 추측 항법 m, D-517 3과 같은 식), 몸체 반경(`RobotBody.rotation_radius_m`, URDF), 차로 문맥(가장 가까운 차로: 같은 방향 우선, 차로 폭 1.5배 안; `lateral_m` 왼쪽 +, `heading_err_deg`, 일방 여부, 구역, 차로 중심 자세, 다음 장소와 거리).
2. **안내(finding).** `{code, severity crit|warn|info, text, target?, action?}`. `target`은 지도 자세 `{x, y, yaw}`(옮길 곳과 바라볼 방향), `action`은 이미 있는 콘솔 동작 이름. G1 규칙:
   - `CAMERA_NOT_SEEING`(warn): Rosy Cam 소스가 OK인데 그 로봇이 `NO_POSE`. 안내: 매트 밖으로 옮긴 뒤 배경 다시 학습, 또는 LED로 찾기. `action: relearn`.
   - `ODOM_CLOCK_AHEAD`(warn): odom이 미래 시각으로 버려짐. 안내: 로봇 시간 동기.
   - `POSE_UNKNOWN`(info): 위 둘 없이 위치 모름.
   - `OFF_MAP`(warn): 어느 차로에도 없음.
   - `OFF_LANE`(warn): 몸 반폭을 더한 옆 벗어남이 차로 반폭을 넘음. `target` = 차로 중심.
   - `WRONG_WAY`(warn): 일방 차로에서 방향 오차 100° 초과. `target` = 차로 중심과 차로 방향.
   - `STOPPED_IN_ZONE`(crit): 구역(D-517/D-525) 안에서 10 s 넘게 정지. `target` = 차로 중심, 다음 장소까지 거리.
   - `TOO_CLOSE`(crit): 두 몸체 원 사이가 0.03 m 미만. 두 로봇 모두.
   - 연결 끊긴 로봇은 안내를 내지 않는다(명단이 이미 말한다). 지도 자세는 흐리게 남는다.
3. **API.** `GET /api/fleet/guide`(viewer): `{map_version, camera, robots: [{robot_id, online, body_radius_m, pose, lane, findings, worst}]}`. 공유 상태 스냅숏(`SharedGather`, 1 s), 중재 지도 자세, Rosy Cam 추적, 활성 지도, 교통 구역만 읽는다. 정지 시각(odom 속도 기준)만 스스로 들고 있다.
4. **화면.** 관제 지도 "로봇" 층(`layerOn("poses")`, `guide-layer.js`): 몸체 원(LOCALIZED 채움, 추정은 점선 테두리, 끊김은 흐리게), 방향 화살표, 몸체 + u 점선 고리, 이름·±u 글, 안내가 있으면 테두리 색(위험·주의 토큰)과 목표까지 점선 + 목표 방향 화살표. 사이트·카메라 보기와 격자 보기 둘 다. 예외 큐에 warn·crit 안내를 같은 규칙으로 더한다(info는 넣지 않음). 1 s 폴링, 404면 다음 로그인까지 묻지 않음.
5. **단계.**
   - **G1(이 ADR, 구현):** 읽기·표시·안내 글과 목표 좌표.
   - **G2:** 예외 큐 행에 `action` 버튼(배경 다시 학습, LED로 찾기, 목표 자세로 trip 계획 열기 — 운영자 확인 뒤). 로봇 카드에 차로 문맥 한 줄.
   - **G3:** 좌표 사전 계산 확장: 횡단보도·주의 지점(D-474)·주차 자리를 현장 지도에 올리고 규칙을 더한다. 기존 감지(D-407 막힘, D-511 ACT, D-517 UNKNOWN, D-525 전체 적색)를 같은 finding 형식으로 모은다.
   - **G4:** 안전한 일부만 자동(예: TOO_CLOSE에서 뒤 로봇 trip 보류). 별도 Safety-Review.

### Alternatives

| 대안 | 판단 |
|---|---|
| 각 감지기(D-511, D-517 등)가 따로 화면 줄을 낸다(지금) | 좌표가 없고 한 로봇의 문제를 한곳에서 못 본다. 기록 하나로 모은다 |
| 브라우저가 지도 자세와 차로를 계산 | 서버의 지도·u·구역과 어긋난다. Fleet이 계산하고 화면은 그린다 |
| 처음부터 자동 처리 | 지금은 지도 자세 자체가 비어 있는 현장이다(Context). 먼저 보이게 하고, 자동은 G4에서 검토 |

### Consequences

- 지도 자세가 있는 로봇은 사이트·카메라 보기에서도 몸체 크기·방향·불확실성으로 보인다. 지도 자세가 없는 로봇은 왜 없는지(카메라, 시계)와 고치는 방법이 예외 큐에 나온다.
- 화면 수용: 로컬 Fleet(실제 코드, 현장 지도 버전 3, 가짜 로봇 6대)에서 1920·390 Chromium으로 확인. 현장 배포는 main 푸시·서명 릴리스 뒤(현장 자동 갱신).
- 시험: `operations/fleet/test/test_guide.py`.
