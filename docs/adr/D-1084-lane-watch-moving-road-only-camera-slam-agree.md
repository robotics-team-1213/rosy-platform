## D-1084 차로 감시는 도로를 달리는 로봇만 판정하고, 이탈은 카메라 자세와 기체 SLAM 자세가 함께 말할 때만이다 (D-511 개정)

**Status:** Accepted (2026-11-28, 사용자 지시 "차선이탈 아닌데 차선이탈이라고 하는 거 해결해 주고, 서로 토론해 보고 더 고민하고 처리해 줘"; 세 세션 토론 합의). 구현은 이 ADR과 같은 PR이다. 실물 수용은 남았다.

| 결정 | 관계 |
|---|---|
| [D-511](D-511-fleet-lane-compliance-watch-and-correction-cue.md) | 개정한다. §2 "움직이는 로봇을 감시한다"를 판정·기록·lane-cue까지 지키게 하고, 충전 칸·주차 유도선을 판정 대상에서 뺀다. 임계값(`warn_margin_m`, `persist_n`, 선 폭)은 바꾸지 않는다. |
| [D-536](D-536-fleet-robot-situation-and-coordinate-guide.md) | 개정한다. 안내 기록의 OFF_LANE·WRONG_WAY 발견도 같은 조건을 따른다. |
| [D-1080](D-1080-fleet-nav2-lane-departure-realign.md) | 지킨다. trip 안의 재정렬(`trip_lane_realign.py`)과 trip_steps의 off-lane 정지는 바꾸지 않는다. |
| D-972·D-1013 충전 칸 정렬 | 지킨다. `evaluate_bay_dock` 판정과 그 입력(카메라 자세)은 그대로이고, lane-cue의 `docking`도 그대로 간다. |

### Context

2026-11-27 16:44Z Fleet R의 `GET /api/fleet/robots/{id}/lane-compliance`:

- rosy_42: 정지, C2 진입선(bay_2, 폭 0.18). offset −0.065, margin −0.031, level ACT, warn·act 5097.
- rosy_46: 정지, C1 진입선. margin −0.020, act 286.
- rosy_45: 정지, C3 칸 안. 주차 유도선 bar_21(폭 0.15)로 잡혀 margin −0.018, act 143, 콘솔 주의 "차선 위 — 안쪽으로 보정 (왼쪽)".
- 북쪽 칸 구역(y > 0.25)에서 천장 카메라 자세는 y +4~6 cm, 요각 +4~8° 틀린다. 순환로는 ±1.5 cm다. 같은 시각 기체 SLAM 자세는 칸 중심선 위였다.

경로별 원인:

1. `lane_compliance_service.tick`이 정지 로봇에도 `LaneComplianceTracker.judge`를 불러 level과 누적 수가 늘었다.
2. `ReturnTracker` 상태는 정지 로봇에도 나왔고, 콘솔 `queues.js` 복귀 행은 `moving`을 보지 않았다(WARN/ACT 행만 보았다). 정지 로봇에 ON_LINE lane-cue도 매 tick 나갔다.
3. `guide/situation.py`의 OFF_LANE·WRONG_WAY 발견은 움직임·칸·자세 출처를 보지 않았다.
4. 판정 자세는 천장 카메라 하나였다. 북쪽 칸의 카메라 오차가 칸 폭 여유(1~3 cm)보다 크다.

### Decision

1. **움직일 때만.** odom 기준 `moving`이 거짓이면 판정하지 않는다. level은 OK(차로가 없으면 UNKNOWN), `warn_count`·`act_count`는 늘지도 0이 되지도 않는다. `exempt: "still"`로 남긴다. 콘솔은 지도 밖(OFF_MAP) 말고는 움직이는 로봇에만 복귀 행을 낸다.
2. **주차/도킹.** 끝 장소 kind가 `charge`·`park`인 간선(world_261026: `bay_*`, `bar_*`, `park_in`, `park_out`)과 `bay_` 간선, 모드 DOCKING, 열린 trip의 `parking_handoff`는 차로 판정에서 뺀다. 지도에는 주차 유도선 표시가 따로 없다. 장소 kind가 이름 접두사보다 나은 기준이라 그것을 쓰고, `bay_`는 D-972와 같게 둔다. `return.state`는 `PARKING`, `exempt: "parking"`이다. 화면 문구는 "주차/도킹"이다.
3. **두 자세가 함께.** 움직이는 로봇은 카메라 자세와 승인된 map binding을 거친 기체 SLAM 자세(`fresh_native_slam` + `matching_fit`, bound Nav2 trip과 같은 읽기)를 모두 잰다. 판정 여유는 둘 중 큰 쪽이다. 그래서 ACT는 둘 다 선 밖일 때만이다. 한쪽 여유만 음수이면 `pose_mismatch`(정보, 경고 아님, 두 자세 차이 `gap_m`)를 남긴다. 복귀 상태는 카메라만 OFF_LANE이면 `POSE_MISMATCH`다. 카메라가 ON_LINE이고 SLAM만 선 밖이면 지금처럼 ON_LINE 보정을 유지한다. SLAM 자세를 못 읽으면 지금처럼 카메라만으로 판정하고 `body_pose_reason`에 이유를 남긴다.
4. **요각.** 좌우·역방향 판정은 기체 SLAM 요각을 먼저 쓰고, 없을 때만 카메라 요각을 쓴다. 칸 정렬 판정은 카메라 자세 그대로다.
5. **lane-cue.** 1~3으로 이탈이 아니게 된 tick의 cue는 `ON_LANE`이고 side·bearing·turn·offset이 없다. 정지 로봇에는 한 번 지운 뒤 보내지 않는다. `docking`은 그대로 실어 보낸다. 실제 이탈(두 자세가 함께 선 밖)의 cue는 그대로다. 마지막으로 보낸 cue가 ON_LANE이 아니면 ON_LANE을 보내지 않고 추적 상태를 그대로 보낸다. ON_LANE은 CORE의 래치(`fleet_wrong_way`, 회전)를 풀기 때문이다(D-430 독립 검토 지적). 로봇이 차로로 돌아와 추적 상태가 ON_LANE이 된 뒤에야 지운다.
6. **화면.** 새 화면 요소는 없다. 주의 큐에 "주차/도킹"·"위치 불일치"를 넣지 않는다. 안내 기록에 정보 발견 `PARKING`·`POSE_MISMATCH`를 넣고, 지도 칩 문구 끝에 " · 주차/도킹" 또는 " · 위치 불일치"를 붙인다.

### Consequences

- 정지·주차 로봇의 거짓 "차로 이탈"·"차선 위" 주의와 그 lane-cue가 사라진다.
- 카메라만 틀린 이탈은 경고가 아니라 위치 불일치로 보인다. 카메라와 SLAM이 같은 쪽으로 함께 틀리면 여전히 놓친다(1차 방어는 IR이다, D-511).
- lane-cue가 주차 간선에서 보정을 싣지 않으므로 결정→움직임 입력이 바뀐다. D-430 Safety-Review 대상이다.
- 열린 PR #1050은 감시 입력 자세를 SLAM으로 바꾼다. 이 ADR과 함께 들어가면 카메라 자세가 판정에서 빠져 3항이 성립하지 않으므로, 그 PR은 이 개정 위에서 입력 자세 변경을 빼거나 맞춘다.

### Open

- 실물: 정지한 칸 진입선·주차 유도선·칸 안 기체에 주의·ACT가 없는지, 움직이는 순환로 기체의 실제 이탈이 여전히 ACT인지, 북쪽 칸 접근 중 `pose_mismatch` 빈도.
