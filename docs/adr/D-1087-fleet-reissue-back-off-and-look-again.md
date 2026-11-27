## D-1087 같은 지점에서 같은 이유로 되풀이 실패한 Nav2 도로 trip은 한 번 물러나 다시 본 뒤 다시 낸다

**Status:** Accepted (2026-11-28, 사용자 승인 "그렇게 주행해도 돼. 후진하고 보는 것도 더 고민해서 해 봐"; 조정 세션 확정 방향). 구현은 이 ADR과 같은 PR이다. 실물 수용은 남았다. **Fleet이 스스로 기체를 후진시키는 첫 경로다.**

| 결정 | 관계 |
|---|---|
| [D-1086](D-1086-fleet-trip-reissue-after-non-hazard-end.md) | 개정한다. `recovery.same_spot`이 있는 D-1082 exhausted는 D-1086에서 금지였다. 이제 물러나기 한 번이 끝난 뒤에만 다시 낸다(`kind: same_spot`). 재발행 3회·10분 한도 안에서 센다. 물러나기가 거절·중단·미확인이면 종전처럼 다시 내지 않는다. |
| [D-1082](D-1082-fleet-nav2-road-trip-stop-recovery.md) 사다리(#1177) | 지킨다. 같은 지점 반복 표시(`same_spot`)와 저속·문턱 없는 재중심 수단을 재사용한다. 재발행 trip의 첫 1.0 m(`detail.first_leg`)를 저속(0.05)·재중심으로 보낸다. |
| [D-1080](D-1080-fleet-nav2-lane-departure-realign.md) | 지킨다. "다시 보기"는 D-1080의 신뢰 규칙(카메라 anchor 신선, SLAM-카메라 gap ≤ 0.05 m, 칸·도킹 구간은 카메라로 판정하지 않음)을 그대로 쓴다. |
| [D-494](D-494-fleet-trip-execution-m2-contracts.md), D-2·D-369 | 지킨다. Fleet은 구동하지 않는다. 후진은 CORE의 `nudge_backward` 임무이고, 콘솔 한 칸 이동(`POST /robots/{id}/step`)과 같은 내부 함수(`nudge_routes.request_step`)로 요청한다. 새 HTTP 경로·새 모션 writer가 없다. |
| D-424 CORE 뒤쪽 판정 | 지킨다. 뒤쪽 띠·멈춤 간격·무반사 빔 거절, 임무 자체의 거리·시간·장애물·E-stop·센서 정지 종료는 CORE가 한다. middleware는 바꾸지 않는다. |

### Context

2026-11-27 rosy_45가 lower_east에서 벽 쪽으로 3 cm 치우친 채 RPP "collision ahead"로 세 번 멈췄다. 경로 모양으로 제자리 회전을 끌어내는 것은 3 cm에서 산술상 불가하고, CORE 회전·repark는 0.113 m 가드에 걸린다. 남는 것은 속도 저하(#1177)와 물러나기다. 물러나기는 trip 안(복구 3회차)에서 부르면 trip lease를 쥔 기체가 취소 뒤에도 NAVIGATION에 남아 CORE가 409로 거절한다(robot-45·robot-d3 관찰). D-1086의 재발행 대기 단계에서는 trip이 닫히고 모드가 IDLE이므로 lease·모드와 충돌하지 않는다.

### Decision

1. **대상.** D-1086이 판정한 `same_spot` 종료(D-1082 사다리 기록이 있고 같은 사유 정지 3회 이상이 ±0.05 m 안).
2. **순서.** D-1086의 다시 내기 전 조건(읽기 두 번, estop false, 정지 증명, goal 없음, LOCALIZED, 지도·결속 같음) + 아래 안전 조건이 두 번 연속 맞음 → 후진 한 번 요청(0.08 m, 기존 nudge 상한 0.10 m 이하, CORE nudge 속도 0.03 m/s) → CORE 임무 상태를 읽어 `done` 확인 → "다시 보기": D-1086 조건 + LOCALIZED + 카메라 anchor 신선 + SLAM-카메라 gap ≤ 0.05 m가 두 번 연속 → 같은 요청으로 재발행, 새 trip의 `detail.first_leg = {until_m: 1.0}` 동안 road_speed 상한 0.05와 문턱 없는 재중심.
3. **통로.** `nudge_routes.request_step`(콘솔 한 칸 이동과 같은 함수): 기체가 trip·콘솔 동작 중이면 거절, 다른 기체의 trip·대열이 있으면 거절(`STEP_TRAFFIC_BUSY`), 케이블 보호 거절, 이동 전 주변 Fleet 주행 기체 정지(`hold_for_localization`). CORE 거절은 그 코드를 기록하고 재발행하지 않는다(`dropped: back_off_refused`).
4. **안전 조건(Fleet 쪽, 모두 충족해야 후진).**

| 조건 | 어긋나면 |
|---|---|
| `safety.estop` false, 모드 IDLE | 기다림(`estop`, `mode_not_idle`) |
| 케이블 보호 플래그 없음 | 기다림(`cable`) |
| 지도 버전이 원 trip과 같음 | 기다림 |
| 충전 칸 간선·`bay_` 간선·parking handoff·DOCKING·top-view 정차 접근(`_excluded`), 정밀 정차 구간 아님 | 기다림(`excluded_zone`) |
| 현재·직전 구간이 횡단보도·신호 구역에 닿지 않음 | 기다림(`crosswalk`, `signal`) |
| 뒤 0.08 m 지점이 같은 간선의 차선 안, 또는 10° 이내로 이어진 직전 간선의 차선 안(몸체 여유 ≥ 0) | 기다림(`no_room`) |
| 명단의 다른 모든 기체가 같은 지도에서 신선한(1.5 s) LOCALIZED 자세를 가짐 | 기다림(`peer_unknown`): 자리를 모르는 기체는 뒤에 있을 수 있다 |
| 다른 모든 기체가 0.5 m 밖 | 기다림(`peer_near`) |
| 운영자 새 trip, 종료 뒤 E-stop·line-follow OFF 없음 | 버림(D-1086 `new_trip`, `stopped_since`) |

5. **통신 단절.** CORE 임무는 자기 거리(0.08 m)와 시간(거리/속도 + 5 s)에서 스스로 끝난다. Fleet이 `done`을 거리/속도 + 10 s 안에 읽지 못하면 `back_off_unconfirmed`로 버리고 다시 내지 않는다. `aborted`(장애물·E-stop 등)도 다시 내지 않는다.
6. **한도.** 한 사슬에 후진 최대 2회, 합계 0.16 m 이하(stuck lane_lost 후진 상한 0.20 m보다 작다). 물러난 뒤 재발행한 trip이 다시 같은 지점에서 실패하면 0.08 m 더 물러난다. 그 뒤에는 그만두고 `reissue.state: gave_up`, `gave_up: "한쪽 치우침 복구 실패: lat …, 벽 여유 …, 시도한 조건 […]"`을 남긴다. 재발행 3회 안에서 센다.
7. **기록.** 끝난 trip `detail.reissue.back_off = {phase, attempt, distance_m, total_m, before, after, lat_m, started_at, ended_at, result(done | aborted:<이유> | unconfirmed | <거절 코드>)}`, 새 trip `detail.reissued_from.back_offs·back_off_m`, `detail.first_leg`.
8. **코드.** `trips/trip_back_off.py`(조건·다시 보기·문구), `trip_reissue.py`(단계), `nav2_recovery_ladder.py`(`first_leg`), `trip_road_speed.py`(진행 거리 전달), `pose/nudge_routes.py`(`request_step` 분리), `bootstrap/role_builders.py`(연결).

### Consequences

- 시험: `operations/fleet/test/test_trip_back_off.py`(한 번 물러난 뒤 저속·재중심 재발행, 조건별 후진 없음, CORE 거절·중단·미확인 시 재발행 없음, 2회·0.16 m 한도와 문구, 물러나는 중 E-stop, 뒤쪽 공간 판정).
- 기존 콘솔 한 칸 이동 경로의 동작은 같다(함수만 분리).

### Open

- 뒤쪽 기체 판정은 블록 표(held·pinned·last_occupied, route_occupants)가 아니라 "모든 기체 자리 확인 + 0.5 m 밖"이다. 더 보수적이지만, 자리를 모르는 기체가 하나라도 있으면 물러나지 않는다. 블록 표 판정이 필요하면 교통 쪽과 정한다.
- 다른 기체가 trip 중이면 `request_step`이 거절하므로, 여러 대가 동시에 달리는 시간에는 물러나기가 거의 일어나지 않는다.
- 재발행 직후 trip 루프가 `first_leg` 기록 전에 첫 경로를 보낼 수 있다. 그 경우 첫 송신은 평범한 재중심이고, 저속 상한은 그 뒤 갱신부터 걸린다.
- 실물 수용: rosy_45 lower_east 벽 쪽 치우침 재현에서 후진 0.08 m(`done`) → 다시 보기 → 저속 재발행 → 통과, 그리고 뒤에 기체를 둔 상태에서 `peer_near` 거절을 확인한다.
