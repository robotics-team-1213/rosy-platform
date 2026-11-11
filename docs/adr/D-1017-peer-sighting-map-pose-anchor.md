## D-1017 peer 위치 공유로 지도 자세 앵커 보강 — 카메라가 조용할 때만, 로봇이 보고한 자기 위치로

**Status:** Proposed (2026-11-11, 사용자 지시 "pinky 가 서로 소통… 관제나 기타와 소통". 구현·원격 시험 포함, 실물 현장 수용 없음)

잇는 결정: [D-494](D-494-fleet-trip-execution-m2-contracts.md)(sighting 기반 지도 자세·trip 전용) · [D-593](D-593-operator-map-pin-anchors-map-pose.md)(운영자 핀 앵커) · [D-989](D-989-fleet-auto-locate-observation.md)(자동 위치 피드 앵커) · [D-488](D-488-fleet-site-map-address-routes.md) 3(로봇이 보고한 LOCALIZED 지도 자세도 trip 시작에 쓴다) · [D-456](D-456-lan-receiver-approval-and-persistent-pairing.md)(신뢰 경계는 등록·토큰) · v1.359 peer pose sharing(`docs/plans/2026-11-04-peer-pose-sharing-design.md`)

### Context

1. 지도 자세를 만드는 세 앵커는 모두 외부 시점이다: 카메라 sighting(D-494), 운영자 핀(D-593), 승인된 자동 위치 피드(D-989). 셋 다 끊기면 지도 자세는 odom dead reckoning(`bridged`)으로 흐르고 결국 `UNKNOWN`이 된다.
2. 2026-11-11 관측: 카메라 sighting이 30일 동안 한 건도 수락되지 않은 현장이 있었다. 콘솔 카드의 sighting 칩은 30 s 만에 사라지므로, 화면에서는 "카메라가 고장 난 상태"와 "정상인데 조용한 상태"가 구분되지 않았다.
3. 로봇들은 이미 서로의 자기 위치를 1 Hz beacon으로 주고받는다(v1.359, `StateSnapshot.peers` · `GET /api/v1/peers`). `LOCALIZED`인 로봇만 `pose`를 싣고, 표는 `max_age_s`(기본 5 s)를 넘긴 행을 버린다. Fleet은 그 표를 하트비트 스냅숏으로 이미 받고 있었다 — 쓰지 않고 있었을 뿐이다.
4. 이 값은 **독립 관측이 아니다.** 로봇 A의 자기 위치를 로봇 B가 중계한 것이므로, A의 자기 위치 추정을 B의 표를 통해 다시 읽는 것이다. D-488 3은 이미 "로봇이 보고한 LOCALIZED 지도 자세"를 trip 시작에 받아들인다. 새 신뢰 수준을 만드는 것이 아니라 같은 수준을 카메라 없이도 유지하는 변경이다.

### Decision

1. **peer 앵커를 네 번째 앵커 종류로 넣되, 카메라와 운영자 핀 뒤에만 둔다.** `MapPoseTracker.add_peer`가 상태 스냅숏의 `peers` 행을 받아들일 조건:
   - 로스터에 있는 로봇의 행이고 `localization_state == LOCALIZED`, `pose`가 유한값, `age_s ≥ 0`;
   - `age_s`가 `peer_lease_s`(기본 6.0 s) 이내 — 1 Hz beacon + 5 s 표 + 하트비트 중계가 들어가고 카메라 lease(1 s)는 들어가지 않는 값;
   - `map_id`가 활성 사이트 지도와 같을 때만;
   - 마지막 카메라 sighting보다 `peer_after_camera_s`(기본 10.0 s) 넘게 뒤일 때만 (`CAMERA_RECENT`) — 살아 있는 카메라가 앵커를 쥔다;
   - 운영자 핀이 `max_anchor_age_s`(10 s) 안이면 거절(`PIN_FRESH`);
   - 같은 로봇의 더 새 peer 표본이 있으면 거절(`NOT_NEWER`).
2. **받아들인 peer 표본은 기존 표본 규칙을 그대로 탄다.** `Sighting(kind=PEER)`로 pending에 들어가 odom과 짝지어지고, 첫 앵커·점프·2 일치 복구 규칙이 카메라 sighting과 같다. 따라서 첫 peer 앵커는 `DEGRADED`이고, 2 표본이 맞아야 `LOCALIZED`다. 새 상태기계·새 판정기를 만들지 않는다.
3. **`source`/`anchor_source`에 `peer`를 추가한다.** 라우트 응답은 `asdict`라 필드 추가가 없고, 콘솔 카드는 `로봇 보고`로 이름을 붙인다.
4. **침묵하는 카메라를 화면에 남긴다.** `MapPose.last_sighting_age_s`(마지막 수락 sighting의 나이, 없으면 null)를 응답에 더하고, 카드가 300 s를 넘으면 `카메라 N분 침묵`을 덧붙인다. 30 s에 사라지는 sighting 칩과 달리 이 줄은 계속 남는다.
5. **경계.** peer 앵커는 자동 위치 차단(D-989)을 풀지 않고, D-472 신원 확인을 대신하지 않으며, 운영자 핀을 덮지 않는다. trip·교통·`/route`의 권한 규칙은 바꾸지 않는다 — trip 시작은 여전히 `LOCALIZED` 지도 자세를 요구하고, 그 자세의 출처는 `anchor_source`로 남는다.
6. **로봇 계약을 바꾸지 않는다.** `PeerRow`·`StateSnapshot.peers`는 v1.359 그대로 소비만 한다. peer 공유가 꺼진 현장(`peers: null`)에서는 이 경로가 아무 일도 하지 않는다.

### Consequences

- 카메라가 죽어도 로봇들이 서로를 보는 동안은 지도 자세가 `UNKNOWN`으로 떨어지지 않는다. 편대·trip의 출발 대기가 줄어든다.
- peer 앵커는 카메라보다 **늦고 거칠다**(1 Hz, `age_s` 근사, 중계 지연). 그래서 카메라 최근 10 s 안에는 쓰지 않는다. 카메라가 살아 있는 현장의 자세 품질은 그대로다.
- 잘못된 자기 위치를 가진 로봇은 이웃의 앵커를 틀리게 할 수 있다. 완화: `LOCALIZED` 주장만, 2 표본 일치, 점프 검사, 활성 지도 일치, `peer` 출처 표시. 남는 위험은 D-488 3이 이미 받아들인 "로봇 자기 보고"와 같은 급이다.
- `peer_lease_s`가 짧으면 로봇이 3대 미만인 현장에서 이 경로가 거의 안 쓰인다. 늘리는 것은 사이트 설정 한 줄이다(`fleet.map_pose.peer_lease_s`, 최대 30 s).
- `last_sighting_age_s`는 읽기 시점 계산값이라 감사·원장에 남지 않는다.

### 검증 (Validation / Transition)

- 호스트(원격 D-584): `operations/fleet/test/test_map_pose.py`(peer 앵커·거절 사유 전체·첫 앵커 DEGRADED·2 표본 LOCALIZED·`last_sighting_age_s`), `test_map_pose_service.py`(`_observe_peers` — 로스터·`LOCALIZED`·지도·lease·형식 필터), `operations/fleet/test/web/localization-badge.test.mjs`(`peer` 이름·카메라 침묵 줄).
- 실물: 기체 5대가 모두 켜진 뒤 카메라 sighting을 끊고 peer 앵커로 trip이 서는지 1회 확인한다(사람 몫). FIELD 게이트는 그대로다.

### References

`operations/world/src/rosy/world/state/projections/map_pose.py`(`add_peer`, `PEER`, `peer_lease_s`, `peer_after_camera_s`, `last_sighting_age_s`), `operations/fleet/fleet/server/pose/map_pose_service.py`(`_observe_peers`), `applications/fleet/web/localization-badge.js`, `contracts/foundation/core_common/protocol/schemas.py`(`PeerRow`, `StateSnapshot.peers`), API Ref v1.388
