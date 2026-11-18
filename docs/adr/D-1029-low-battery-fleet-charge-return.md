## D-1029 저전력 충전 복귀: Fleet이 경고 수준에서 충전 칸 앞으로 데려가고, 그동안 CORE는 10 % 정지를 미루고 0.10 m/s로 달린다

**Status:** Proposed (2026-11-14, 사용자 지시: "충전이 안되면 충전으로 돌아가도록 하는 거에 대해서도 처리하도록 해. 저전력모드로 해서 nav2 로 해서 돌아가도록 하는거에 대해서 고려해봐." 결정: 시작 20 %, 복귀 중 10 % 예외·5 % 바닥, 칸 앞 정지 후 사람이 꽂음, 0.10 m/s). 호스트 시험까지다. 기체·현장 수용은 없다.

잇는 결정: [D-721](D-721-return-to-station-or-outing-start.md)(정류장 복귀 요청 S1 → 이 결정이 S2 이동), [D-941](D-941-track-platoon-hold-points-charge-bays.md) 6항("Fleet 충전 복귀 중이면 그것이 복귀"), [D-541](D-541-core-fleet-trip-lease.md)(trip lease), [D-502](D-502-battery-estop-release-and-battery-evidence.md)(배터리 정지 해제), SAF-005.

### Context

2026-11-14 rosy_45는 배터리 13.8 %에서 경고 표시가 켜져 Fleet의 식별 점멸을 거절했고, 그래서 위치가 없어 출발하지 못했다. 6분 뒤 10.1 %(critical)가 되었다. 전압으로 잰 %는 크게 뛴다. 그때까지 낮은 배터리 기체는 사람이 데려가야 했다.

1. Fleet의 정류장 복귀 요청(D-721 S1)과 충전 칸 계획(D-941)은 보여 주기만 하고 기체를 움직이지 않았다.
2. Pinky의 10 % 정책은 `STOP`이다. Fleet이 데려가는 중에 10 %를 지나면 그 자리에서 E-Stop이 걸린다.
3. `PowerMode`는 센서·화면만 바꾼다. 달리는 속도를 낮추는 "저전력 주행"은 없었다.

### Decision

1. **경고 수준(20 %)에서 Fleet이 복귀를 시작한다.** D-721 복귀 요청이 승인되면(`fleet:auto` 또는 이름 있는 운영자) 사이트 설정 `fleet.station_recovery.dispatch: true`일 때 그 기체를 고른 충전 칸 앞으로 Nav2 목표를 보낸다. 목표는 trip이 free 목표를 바꾸는 방식 그대로 기체 프레임으로 바꾼다(D-1003·D-1022). Fleet 측정 위치가 없으면 움직이지 않고 사유를 남긴다. 기본값은 꺼짐이다.
2. **복귀는 trip lease의 목적으로 CORE에 알린다.** `PUT /api/v1/trip-lease`에 선택 필드 `purpose: "charge_return"`을 더한다(이 값만 허용, 갱신으로 바꿀 수 없음). lease가 살아 있는 동안이 "Fleet 충전 복귀 중"이다. TTL은 기존 1–10 s다. Fleet이 죽으면 lease가 끝나고 CORE는 기존대로 주행을 멈춘다.
3. **복귀 중에는 10 % 동작을 미룬다. 5 %는 그대로다.** 충전 복귀 lease가 있고 Nav2 목표가 진행 중일 때 10 %(`STOP`·`RETURN_HOME`)에 닿으면 CORE는 동작하지 않고 `battery.critical_deferred` 사건을 남긴다. 그 뒤 매 측정에서 아직 10 % 이하인데 복귀가 끝났으면(도착·취소·실패·lease 끝) 그때 `battery_policy` E-Stop을 건다. 10 % 위로 돌아오면 미룸을 지운다. 5 % `battery_deep` E-Stop은 바꾸지 않는다. **사용자가 가드 약화를 알고 고른 예외다.**
4. **복귀 중 속도 상한은 0.10 m/s다.** 안전 게이트 `clip`이 충전 복귀 lease가 살아 있는 동안 모든 범위의 선속도 상한을 `safety.charge_return_linear`(기본 0.10)로 낮춘다. 낮추기만 하고 올리지 않는다.
5. **칸 앞에서 멈추고 사람이 꽂는다.** 도착하면 Fleet이 lease를 끝내고 기체에 사람 요청("충전 칸 <id>에 꽂아 주세요")을 보낸다. 자동 후진 도킹(D-972)은 쓰지 않는다. 전압 상승만으로 충전 확인을 켜지 않는다(D-941 6).

### Consequences

- 10 % 아래에서도 복귀가 계속 달릴 수 있다. 5 % E-Stop과 lease TTL이 바닥이다. 복귀가 끝나면 아직 10 % 이하인 기체는 칸 앞에서 E-Stop으로 묶이고, 충전으로 회복하면 D-502대로 풀린다.
- 복귀 중 0.10 m/s라 칸까지 시간이 더 걸린다. 그래서 시작은 15 %가 아니라 20 %다.
- `dispatch`를 켜기 전에 기체 위치(카메라·auto-locate·D-1022 결속)와 칸 앞 자세가 있어야 한다. 없으면 복귀는 시작하지 않고 사유를 보인다.

### 한계 (다음 일)

- 실물: 선을 뗀 기체로 20 % 유도 시험(설정 경고값을 잠시 올려서) → 칸 앞 도착·0.10 m/s 상한·10 % 미룸·lease 끊김 시 정지 확인.
- 자동 도킹(D-972)과 충전 확인 장치는 이 결정 밖이다.
- 복귀 경로의 남은 배터리 예측(거리 대비 %)은 없다.

### 검증 (Validation / Transition)

- 호스트(원격): CORE `test_core_trip_lease.py`·배터리 정책·안전 게이트 시험(미룸·lease 끝·Nav 끝·5 %·회복·상한), Fleet 정류장 복귀 시험(꺼짐 그대로·켜면 lease 목적·목표 변환·도착 시 사람 요청·위치 없음·실패).
- 실물: 위 한계의 실물 순서.

### References

`middleware/core/gateway/core/bridge/battery_policy.py`, `middleware/core/gateway/core/trip_lease.py`, `middleware/core/api/core_api_web/api/v1/trip_lease.py`, `contracts/foundation/core_common/protocol/trip_lease.py`, `middleware/core/services/core_features/safety_gate/manager.py`, `operations/fleet/fleet/server/console/station_recovery_routes.py`.
