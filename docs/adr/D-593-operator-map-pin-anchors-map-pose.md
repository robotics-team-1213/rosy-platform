## D-593 운영자가 지도에 찍은 위치가 D-494 지도 자세의 앵커가 된다 — odom이 잇고, 천장 카메라 sighting이 검사한다

**Status:** Proposed (2026-10-10, 사용자 지시: "지도에 좌표를 찍어주는 것도 한 방법 — 마커로 찍어서 그게 움직이도록"). SOURCE 변경과 호스트 테스트만 한다. 사이트 배포와 현장 수용은 이 기록이 하지 않는다.

잇는 결정: [D-494](D-494-fleet-trip-execution-m2-contracts.md) 3항(sighting이 앵커, odom이 다리, LOCALIZED/DEGRADED/UNKNOWN) · [D-587](D-587-ceiling-marker-sightings-anchor-map-pose.md)(천장 마커 sighting) · [D-546](D-546-recovery-manoeuvre-signals-and-fleet-pose-request.md) 6항(overhead 답) · [D-540](D-540-fleet-console-structure-v2.md) 9항(이름 있는 운영자) · [D-581](D-581-trail-follow-ceiling-camera-anchored-odom.md)(odom_to_map). 폴더 구조는 바뀌지 않으므로 D-427 3항은 해당하지 않는다.

### Context

- 2026-10-10 현장에서 두 로봇의 Fleet 지도 자세가 `UNKNOWN`이었다. 그래서 trip은 422 `TRIP_POSE_UNTRUSTED`를 냈고, D-581도 기준을 잡지 못했다. 원인은 sighting이 없는 것이었다. 승인 보정 sighting은 D-587이 다룬다.
- 카메라가 로봇 마커를 읽지 못하는 자리도 있다. 화면 밖, 가림, 작은 마커가 그런 경우다. 사람이 로봇을 보고 지도에 위치와 방향을 찍는 길이 필요하다.
- 기존 조각: D-395 운영자 결정(`DecisionSource.HUMAN`)은 로봇 AMCL로 간다. D-494 지도 자세와는 다른 경로다. D-513 시작점은 저장하는 지도 기준점이다. 로봇의 지금 자세가 아니다.

### Decision

1. **핀은 D-494 앵커다.** `POST /api/fleet/robots/{robot_id}/map-pin` `{x, y, yaw}`(지도 좌표, m, rad). Fleet은 그 로봇 상태를 REST로 한 번 읽은 다음, 핀을 가장 새 odom 표본과 짝지어 `MapPoseTracker`의 앵커로 둔다. 새 자세 경로는 만들지 않는다. trip, D-511, D-581, guide는 지금처럼 `MapPose`를 읽는다.
2. **신뢰.** 핀 직후 상태는 `LOCALIZED`다. 사람이 로봇을 보고 확인한 것이라 첫 sighting 앵커의 2회 확인을 요구하지 않는다. 다리 한도는 sighting 앵커와 같다. 다음 중 하나면 `DEGRADED`다: odom 이동 1.5 m 초과(`max_dead_reckon_m`), 회전 270° 초과, 앵커 나이 10 s 초과(`max_anchor_age_s`). 더 넓은 한도는 두지 않는다.
3. **sighting이 검사한다.** 핀 뒤에 온 sighting은 다른 앵커와 똑같이 예측과 비교한다. 0.15 m 또는 20°를 넘게 다르면 `DEGRADED`로 다시 앵커를 잡고, 2회 일치하면 회복한다. 맞으면 sighting이 앵커를 이어받는다. 핀보다 먼저 찍힌 sighting은 버린다. 핀이 고치려던 옛 관측이기 때문이다.
4. **조건.** 다음은 거절한다.
   - odom이 3 s(`max_odom_age_s`)보다 오래됨: 409 `MAP_PIN_ODOM_STALE`
   - 그 로봇이 trip 중: 409 `MAP_PIN_TRIP_ACTIVE`. 진행 중인 trip의 자세가 순간 이동하지 않게 한다.
   - 숫자가 아님: 422
   - 이름 없는 공유 토큰: D-540 9항에 따른 401/403

   odom이 리셋되면(CORE 재시작) 핀도 사라진다.
5. **표시와 감사.** `map-pose`에 `anchor_source`(`sighting` \| `operator_pin`)를 더한다. 핀 뒤 odom이 오기 전까지 `source`는 `operator_pin`이다. 콘솔은 "운영자 핀"과 앵커 나이를 보인다. 모든 핀은 site map 이벤트 `map_pin`이 된다. 이벤트에는 운영자, 자세, map_id, 직전 자세 상태가 들어가고, HTTP 감사도 따로 남는다.
6. **로봇에 보내지 않는다.** D-546 6항 (a)의 overhead 답은 `anchor_source == sighting`일 때만 낸다. 핀은 로봇 AMCL 초기화가 아니다. 로봇에 핀을 넣는 일은 D-395 운영자 결정이 할 일이다.
7. **trip 시작 조건은 그대로다.** 시작은 앵커 나이 2 s 이하(`start_anchor_age_s`)를 요구한다. 그래서 카메라 없이 핀만 있으면, 핀을 찍은 뒤 2 s 안에 시작해야 한다. 그 trip은 앵커 나이 10 s에서 `DEGRADED`가 된다. 핀만으로 오래 달리는 것은 이 결정의 범위가 아니다. 그 한도를 넓히려면 별도 결정이 필요하다.

### 오차와 안전

- 핀 오차는 운영자 클릭의 정확도다. 지도 축척과 사람의 눈에 달려 있다. 그래서 신뢰를 sighting 하나와 같은 다리 한도에 묶는다. 카메라가 로봇을 다시 보면 0.15 m / 20° 검사가 잘못 찍은 핀을 잡는다.
- 핀은 `cmd_vel`, 안전 정지, 로봇 AMCL에 들어가지 않는다. 지도 자세를 읽는 Fleet 쪽 판단만 바뀐다.

### Alternatives

| 대안 | 판단 |
|---|---|
| 핀을 sighting으로 넣는다(`POST /api/fleet/sightings`) | 기각. source 토큰과 보정 revision이 카메라의 것이다. 사람의 입력을 카메라 관측으로 꾸미게 된다 |
| 핀은 `DEGRADED`로 시작한다 | 기각. 그러면 trip과 D-581을 열 수 없어 사용자 목적을 이루지 못한다 |
| 핀 앵커에 더 긴 나이·거리 한도 | 보류. 사용자가 정한 한도는 기존 다리 한도다 |
| D-395 운영자 결정 재사용 | 기각. 로봇 AMCL로 가는 경로다. 지도 자세 앵커가 아니다 |

### Validation

- `operations/fleet/test/test_map_pose_pin.py`: 즉시 LOCALIZED, odom 다리, 한도, odom 낡음, sighting 일치·불일치, 핀 이전 sighting, odom 리셋, 다른 지도, 경로 권한·이벤트·trip 중 거절, overhead 답 제외.
