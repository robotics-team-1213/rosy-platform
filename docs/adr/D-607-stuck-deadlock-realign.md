## D-607 막힘을 더 넓게 찾고, 차로 안에서는 돌지 않는다 — CORE 새 막힘 원인 `no_progress`·`dithering`, Fleet 규칙만 고르는 `REALIGN`(제자리 회전·K-턴), 앞뒤 막힘의 제한 회전, 역주행은 회전 자리에서만 돈다

**Status:** Proposed (2026-10-10). 착지 전 사용자 승인, CORE 계약(8항)과 단계 P0–P5는 CORE 쪽 세션이 확인했다(2026-10-10). 착지 전 사용자 승인과 단계별 Safety-Review가 필요하다. 이 ADR은 문서다. 구현은 아래 단계마다 따로 착지한다.

**고치는 결정:**
- [D-577](D-577-trouble-fleet-rules-and-ai-pc-realtime-situation-facts.md) 1항 원인 목록에 `no_progress`·`dithering`을 더한다(1항). 「AI PC 제안」 개정 2항의 원인별 허용 단어에 새 원인을 넣고, `REALIGN`은 어떤 원인에도 넣지 않는다(2항).
- [D-407](D-407-lane-stuck-recovery-console-then-local.md) 막힘 결정 단어에 `REALIGN`을 더한다(CORE API additive, 8항 계약).
- [D-511](D-511-fleet-lane-compliance-watch-and-correction-cue.md) 개정 1 3항 `WRONG_WAY`의 "차로 0.185 m, 몸 회전 반지름 0.088 m라 차로 안에서 돈다"를 고친다. 회전은 회전 자리에서만 한다(4항).

잇는 결정: D-2/[D-18](D-18-rosy-core.md)(CORE만 최종 `cmd_vel`, CORE 재확인) · [D-395](D-395-fleet-assisted-localization.md)(신뢰 지도 자세) · [D-424](D-424-one-robot-body-for-every-near-check.md)(몸 하나) · [D-438](D-438-fleet-stuck-resolver-rules-model-human.md)(규칙 → 사람, 예산) · [D-468](D-468-local-lane-departure-return.md)(차로 복귀) · [D-517](D-517-multi-robot-lane-traffic.md) 3·5항, M4(trip 로봇은 WAIT만) · [D-541](D-541-core-fleet-trip-lease.md)(trip lease) · [D-573](D-573-crosswalk-stop-look-cross.md)(횡단보도는 사람) · [D-430](D-430-safety-as-a-separate-concern.md)(안전 분리).

### Context

1. **재생 자료(다른 세션, 2026-10-10, `X:\DevTemp\steer-review\deadlock\`).** 천장 카메라와 odom으로 확인한 막힘 39건(1448 s). 지금 CORE 5 s `no_motion`은 19건만 잡고 20건(683 s)을 놓친다. 놓친 것의 꼴은 셋이다: 제자리 흔들림(`dithering` 주원인 11건), 명령은 있으나 차로를 따라 나아가지 못함(`no_progress` 주원인 8건), HOLD와 가장자리 추종의 교대·후진 재시도 반복(`HOLD/lane_return_space_or_floor_unconfirmed` ↔ `TRACKING/lane_edge_left`, 최대 174 s). 그동안 HOLD가 한 번에 5 s를 넘지 않아 `no_motion` 창이 계속 다시 시작한다.
2. **기하.** 제자리 회전 원은 URDF 회전 반지름 0.08257 m + `SWEEP_PAD_M` 0.010 m = **0.0926 m**다(`contracts/foundation/core_common/robot_body.py`). 직선 차로의 안쪽 여유(차로 반폭 − 테이프 반폭)는 **0.080 m**, 테이프 바깥 끝까지는 0.105 m다. 회전 원이 테이프 안쪽 끝 안에 드는 곳은 고리 입구 회전 자리 네 곳뿐이다(`turn_spots.json`, 여유 0.099–0.100 m, ±6–7 mm). 확인된 39건 중 그 자리에서 회전이 맞은 건은 0건이다. 22건은 몸이 테이프 위, 15건 차로 안, 2건 차로 밖, |d| 중앙값 0.027 m다. `lane_cue.py` 머리말의 0.088 m는 낡은 값이다.
3. **조작표(`kturn_table.json`).** d = 0이면 제자리 회전(ψ ≤ 90°)·전진 호·K-턴(뒤 호 R 0.05 m, 이어 전진 호 R ≥ 0.02 m)이 된다. d = 0.02 m에서 안쪽 기준은 ψ = 90°의 K-턴뿐이고, d = 0.04 m에서는 바깥 기준 ψ ≥ 60°의 K-턴뿐이다. 나머지는 "없음 → 사람"이다.
4. **앞 물체 정지 14건 중 다른 Pinky는 0건**이다. 모두 차로를 벗어난 뒤의 벽 모서리·기둥이다(`obstacles.txt`, 동료까지 0.9–2.5 m). 앞 물체 막힘의 뿌리는 차로 이탈이다.
5. **방향 자료.** 39건 중 ψ를 아는 것은 16건(천장 23건·안내 16건, 방향 없음 23건)이고 역주행은 8건이다. 지도 v5 방향(지도 좌표 반시계)이 맞다(사용자 결정, 2026-10-10).
6. **겹치는 채널.** 주행 중 방향 보정은 D-511 lane cue(CORE, rosy-e1, Safety-Review 중)가 맡는다. Fleet 막힘 답이 같은 로봇에 회전을 또 내면 두 보정이 다툰다. CORE 세션은 "막힘이 열린 동안 lane cue는 물러난다"를 `feat/core-fleet-lane-cue` 3b263c62e에 넣었다.
7. **크기 규칙.** `docs/plans/2026-10-10-fleet-stuck-subpackage.md`: 이동이 끝나기 전에는 `stuck_*`·`line_stuck`·`ai_facts`를 키우는 변경을 착지하지 않는다.

### Decision

**원칙.** 막힘을 찾는 것은 CORE, 답을 고르는 것은 Fleet **규칙**, 움직이기 전과 중의 마지막 확인은 CORE다. AI 사실과 AI 제안은 Fleet을 더 조심스럽게만 만든다(D-577 7항). 회전 답(`REALIGN`, 7항 R7 포함)은 AI가 만들지 못한다. 고를 수 없으면 `WAIT` + 사람이고, 무응답으로 움직이는 답은 없다. 비상정지와 멈춤은 늘 열려 있다.

1. **새 막힘 원인(CORE) → Fleet R8 `WAIT` + 사람.**
   - CORE `stuck_wiring`이 차선 주행 중 두 원인을 더 낸다. 수치 정의는 CORE가 정해 API Reference에 쓴다. 이 ADR은 성질만 정한다.
     - `no_progress`: 명령이 0이 아닌데 `stuck_report_s` 창에서 차로 방향 순 이동이 문턱 미만. HOLD와 추종이 번갈아도 창이 이어진다(HOLD 시작으로 창을 다시 세지 않는다).
     - `dithering`: 같은 창에서 각속도 또는 선속도 부호가 N번 넘게 바뀌고 순 이동이 문턱 미만.
     - 제외: D-517 통행권 대기, D-494 교차로 HOLD, D-573 서고-보기, 저조도·과노출 HOLD(D-577 개정 4항), 이미 열린 막힘, 사람 조종.
   - Fleet 판단기: 두 원인에는 **R8 `<cause>_hold` = `WAIT` 후 같은 주기에 사람**만 낸다. `BACK_AND_RETRY`를 내지 않는다(놓친 막힘 다수가 후진 재시도 반복이다). 규칙이 생기면 이 ADR 개정이다.
   - D-577 「AI PC 제안」 2항: `no_progress`·`dithering`의 허용 단어는 `WAIT`·`ABORT`뿐이다.
2. **`REALIGN` — Fleet 규칙만 고르는 회전 답.**
   - 모양은 8항 계약이다. 종류는 `PIVOT`(제자리 회전, |각| ≤ 90°)과 `KTURN`(뒤 호 R ≥ 0.05 m·뒤 ≤ 0.08 m, 이어 전진 호 R ≥ 0.02 m)이다.
   - Fleet이 고르는 조건(모두 참): 로봇이 trip이 아님(3항), 원인이 `lane_lost`·`no_motion`·`no_progress`·`dithering`·`obstacle_ahead`(6·7항) 중 하나, `MapPose` `LOCALIZED`·map·`age_s` ≤ 2 s·방향 있음(D-395 신뢰 자세, LEGACY odom 아님), 횡단보도 다각형에서 0.29 m 밖(D-577 1항과 같은 기준), 동료 몸이 회전 원 + 0.30 m 밖(신뢰 지도 자세로; 동료 자세를 모르면 R5 `peer_unknown`), 같은 막힘의 `REALIGN` 시도 < 2, 조작표에 그 (d, ψ)의 조작이 있음.
   - **자세 불확실성을 넣고 표를 읽는다.** `[d − u, d + u]` 전체에서 같은 조작이 가능해야 한다. u = Rosy Cam 보정 잔차 p90(0.018 m) + 마지막 목격 뒤 odom 거리 × `ODOM_DRIFT_PER_M`(D-517 3항). 기하 기준은 **테이프 바깥 끝(0.105 m)**이다. 테이프는 장애물이 아니고 몸이 테이프에 걸친 것은 D-511 `ON_LINE`이 이미 보정하는 상태다. 장애물 안전은 CORE LiDAR 재확인(8항)이 맡는다.
   - 각: 목표 방위(5항 복귀점 또는 v5 차로 방향)와 지금 방위의 차이, ±90°로 자른다.
   - **AI는 `REALIGN`을 내지 못한다.** `POST /api/fleet/ai/proposals`의 허용 단어에 넣지 않는다. AI 사실은 `REALIGN`을 R5로 바꿀 수만 있다(D-577 7항 (2)와 같은 방식).
   - 한 막힘에 `REALIGN` 2번 뒤에는 사람이다. `REALIGN`은 D-438 규칙 예산을 `BACK_AND_RETRY`와 같이 쓴다.
   - 조작이 끝나면 CORE는 막힘을 닫지 않고 `BACK_AND_RETRY`처럼 자기 증거로 다시 판단한다. `lane_lost`는 차선 증거가 있을 때만 풀린다(D-438 §3, RESUME 없음 그대로).
3. **trip 로봇.** P1–P4는 D-517 M4 그대로 `WAIT`만이다. Fleet은 trip 로봇에 `REALIGN`을 보내지 않고, CORE도 lease가 살아 있으면 주인 아닌 토큰의 `REALIGN`을 409 `TRIP_LEASED`로 거절한다(D-541 3항: 움직이는 답). trip 로봇의 `REALIGN`은 P5(Gazebo 통과 뒤, 별도 Safety-Review)에서 정한다. 그때 조건은 조작 동안 몸 앞뒤 끝 ± u가 그 로봇이 이미 쥔 블록 안에 머무는 것이다(D-517 3항 점유).
4. **역주행.**
   - 차로 안에서 U-턴하지 않는다. lane cue `WRONG_WAY`(D-511 개정 1 3항)는 Fleet이 신호에 `turn_spot: true`(로봇 기준점과 u가 회전 자리 안)를 실을 때만 회전하고, 아니면 HOLD `fleet_wrong_way`다. 그 HOLD는 `stuck_report_s` 뒤 `no_motion` 막힘이 되어 Fleet에 온다.
   - Fleet: 역주행(v5 대비 |ψ| > 90°) 막힘은 회전 자리 안이면 `REALIGN PIVOT`(2항 조건), 아니면 R5 `wrong_way_hold` + 사람이다. 역주행인 채 다음 회전 자리까지 달리게 하는 답은 없다(반대 방향 교통과 마주친다).
   - 방향이 맞는(|ψ| ≤ 90°) 로봇은 원래대로 차로를 따라 다음 회전 자리까지 간다.
5. **차로 밖 복귀 목표.** 앞쪽 가장 가까운 v5 차로 점에서 차로를 따라 0.25 m 앞이다. D-511 `entry_ahead_m`을 0.25 m로 두고 같은 값을 쓴다(새 상수 없음). D-468 차로 복귀가 같은 점을 받는다.
6. **`obstacle_ahead`.**
   - trip 로봇: 5 s 막힘 뒤 D-517 5항 (b) 재계획(`handover`, 운영자 확인) → 사람. trip이 아닌 로봇은 경로가 없어 재계획이 없다.
   - Fleet 결정론 판정이 그 로봇을 D-511 `OFF_LANE`(신뢰 지도 자세)으로 보면 `WAIT`에 머물지 않고 2항 `REALIGN`(복귀점 방위) → 안 되면 기존 R2 `BACK_AND_RETRY`(CORE 뒤 재확인) → 사람.
   - "지도의 고정 물체에 막힘"이라는 **AI 사실로는 움직이는 답을 고르지 않는다**(D-577 7항). 그 사실은 큐 참고 칸에만 붙는다. 같은 판정은 Fleet 지도 기하(차로 밖 + 지도 벽·기둥 근처)로만 한다.
7. **R7 앞뒤 모두 막힘.**
   - CORE가 앞 막힘을 냈고 뒤가 막혔을 때(`rear_state: blocked` 또는 CORE의 `rear_blocked` 거절)만이다. 근거는 CORE 판정이고 AI `rear_blocked` 사실이 아니다.
   - `REALIGN PIVOT` 한 번. 2항 조건 전부 + 지도가 그 자리를 차로 밖 모서리 또는 회전 자리로 볼 때. 각은 경로 출구(없으면 복귀점) 방위로 자르고 90° 이하. 아니면 R5 `boxed_hold` + 사람.
8. **CORE 계약(rosy-e1 확인 대상, API Reference additive, D-18).**
   - 결정 `decision: "REALIGN"`, 본문 `realign {kind: "PIVOT"|"KTURN", angle_rad, back_m?, back_radius_m?, fwd_radius_m?, pose_stamp, attempt: 1|2, basis {map_revision, pose_age_s, target: "lane_heading"|"return_point"|"route_exit", d_m, psi_rad, u_m}}`.
     - `angle_rad`: 부호 있음(+ = 왼쪽), |값| ≤ π/2(`KTURN`은 끝 방위 변화).
     - `KTURN`만: 0 < `back_m` ≤ 0.08, `back_radius_m` ≥ 0.05, `fwd_radius_m` ≥ 0.02.
     - `pose_stamp`: Fleet이 각을 계산한 자세의 CORE odom 시각. CORE는 그 뒤의 odom 회전을 빼서 남은 각을 쓴다(D-517 4항 통행권과 같은 방식). 기록에 그 시각이 없으면 거절한다.
     - `basis`는 감사·표시용이다. CORE는 이것으로 허락하지 않는다.
   - **CORE 재확인(시작 전과 매 틱):** 회전 원 0.0926 m(`RobotBody.rotation_radius_m` + `SWEEP_PAD_M`) 밖 LiDAR 여유 `turn_m` ≥ 0.02 m(`_TURN_CLEAR_M`)이고 D-424 회전 8구역이 모두 목격됨. `KTURN` 뒤 호는 뒤 띠 0.06 m(`recovery_rear_clear_m`)와 뒤 사각 규칙(`_back_refusal` 그대로). 스캔 신선(`clearance_stale_s`), 몸 기하 있음. IR 가운데 정지·몸 정지·E-stop이 먼저다. 틱 중 하나라도 깨지면 멈추고 `local_aborted`로 사람에게 간다.
   - 시도 상한: 막힘마다 `REALIGN` 2번(`realign_attempts_exhausted`), `recovery_max_attempts`와 따로 센다. 속도는 기존 `_TURN_RATE`·`recovery_back_speed` 이하다.
   - **거절**(`STUCK_DECISION_REFUSED`의 `why`): `realign_unset`, `realign_angle`, `realign_kind`(P3에서 `KTURN`은 꺼짐), `realign_attempts_exhausted`, `realign_active`, `pose_stamp_unknown`, `turn_blocked`, `turn_unseen`, `rear_blocked`, `rear_blind`, `no_scan`, `scan_stale`, `body_geometry_unset`, `calibration_active`, `crosswalk_gate`(원인 `crosswalk_blocked` 또는 D-573 게이트 활성), `local_recovery_disabled`. lease는 409 `TRIP_LEASED`(D-541).
   - **겹침:** D-541 — 움직이는 답이라 `require_calibration_owner`를 지난다. D-573 — 횡단보도 원인·게이트 활성 중 거절. E-stop — 진행 중 조작을 취소하고 해제 뒤 다시 시작하지 않는다(막힘은 사람에게). D-517 통행권 — P1–P4는 trip 로봇에 오지 않으므로 lease 거절로 충분하다. lane cue — 막힘이 열린 동안 물러난다(3b263c62e, 이 ADR의 CORE 요구사항). 막힘이 닫힌 뒤에만 lane cue가 다시 보정한다.
   - 능력 `stuck_realign: ["PIVOT"]`(P4에서 `"KTURN"`). 없는 로봇에는 Fleet이 보내지 않는다.
   - **IR 가운데 면제(D-344 §12 개정 2·3: 카메라 명령이 제자리 회전인 동안 `lane_departure` 정지 면제, 개정 3: 회전 중 IR 줄 밑에 선이 있고 뒤 LiDAR가 비면 0.02 m/s 뒤 기어가기)는 Fleet이 낸 `REALIGN` `PIVOT`에 지도 회전 자리에서만 적용한다(Fleet은 `turn_spot: true`를 보낸다). 회전 자리 밖에서는 Fleet `PIVOT` 자체가 허용되지 않으므로 면제가 생기지 않는다. CORE 쪽 확인: 조향·lane-cue 세션(2026-10-10), lane-cue가 cue 계약에 `turn_spot`을 더하고 그 값으로 `PIVOT`을 막는다. `lane_cue.py` docstring 반지름은 `robot_body` 0.08257+0.010으로 고쳤다.**
   - **사용자 결정 2026-10-10: 링 입구 4개 회전 지점 허용 (option b).** 링 입구 4개 회전 지점의 `max_free_r`는 0.099–0.100 m이고 필요한 값은 0.0926 + 0.018(자세 오차 한계) = 0.111 m다. 회전 원 가장자리가 칠한 선을 1–2 cm 넘을 수 있다. 사용자는 이 4곳에서만 테이프 폭 0.025 m까지 페인트 겹침을 허용했고, 회전 중 D-344 §12 IR 가운데 면제에 기댄다. 회전 지점은 사이트 YAML `fleet.lane_compliance.turn_spots [{x,y}]`에 두고 허용 오차는 0.018 m, 기본값은 빈 목록이다. 그 밖의 모든 곳에서는 "자세 불확실성 전체에서 맞아야 한다" 규칙이 그대로 엄격하다.
9. **만남(D-517 그대로).** 만남은 D-517만 따른다: 신뢰 지도 자세(`LOCALIZED`)만, 블록 ℓ(3항), 고리 구역 수용 1, `merge_max_wait_s` 20 s. 역주행 로봇의 물러서기는 trip이 아니고 CORE 뒤 재확인이 통과할 때만(R2·R3·R6), 아니면 사람이다. **선행 조건:** D-577 남은 항목 4(R1 `peer_ahead`가 LEGACY odom 자세를 지도 자세처럼 씀)를 먼저 닫는다.
10. **책임 나눔.** 주행 중 방향 보정 = lane cue(CORE). 막힘이 열린 동안의 회전 = Fleet 규칙 `REALIGN`(CORE 재확인). 둘은 같은 순간에 돌지 않는다.

### 단계

| 단계 | 내용 | 주인 | Safety-Review |
|---|---|---|---|
| P0 | 막힘 하위 패키지 이동(계획 2026-10-10) 착지, D-577 남은 항목 4(R1 신뢰 자세) 닫기 | Fleet | R1 변경 |
| P1 | CORE `no_progress`·`dithering` 원인, Fleet R8 `WAIT`+사람, AI 제안 허용 단어 | CORE(원인)·Fleet(행) | 예(CORE 막힘 배선) |
| P2 | Fleet `REALIGN` 그림자: 고를 답과 근거를 `fleet_line_stuck_answers`에 `shadow`로 남기고 실제로는 R5. 재생 39건과 현장 3 운행일로 적용률·오선택을 잰다 | Fleet | 아니오(움직임 없음) |
| P3 | CORE `REALIGN PIVOT`, lane cue `WRONG_WAY` 회전 자리 한정, Fleet 행동(trip 아님, 사이트 목록 `fleet.stuck_resolver.realign_robots`, 기본 빈 목록) | CORE·Fleet | 예 |
| P4 | CORE `KTURN`(새 뒤 호 동작) | CORE·Fleet | 예 |
| P5 | trip 로봇 `REALIGN`(블록 점유 조건) | Fleet·CORE | 예(별도) |

### 먼저 실패해야 하는 시험

- P1 CORE: 놓친 막힘 재생 고정본(`g1c-8kcn` 10–38 s dithering, `g2-8kcn` 0–174 s HOLD↔가장자리 교대, `p13-9dfk` 38–58 s)이 지금 막힘을 열지 않음 → 새 원인으로 `stuck_report_s` 안에 연다. 통행권 대기·교차로 HOLD·서고-보기 고정본은 열지 않는다.
- P1 Fleet: `no_progress`·`dithering`에 `BACK_AND_RETRY`가 나가지 않고 R8 `WAIT` + 사람 행. 이 원인에서 AI 제안 `BACK_AND_RETRY`는 거절.
- P2: 조작표 읽기(d ± u 전체), 횡단보도·동료·LEGACY·자세 나이·trip 각각이 `REALIGN`을 막음, AI 제안 `REALIGN` 거절.
- P3 CORE: `turn_m` < 0.02에서 시작 거절·진행 중 중단, `pose_stamp` 보정, 세 번째 시도 거절, lease 중 409, 횡단보도 게이트 거절, E-stop 뒤 재개 없음, 막힘 중 lane cue 무동작, `turn_spot` 없는 `WRONG_WAY` 무회전.
- P4: 뒤 띠 0.06 m 안 물체에서 `KTURN` 거절·중단.

### Gazebo 시나리오(모델 PC, `tools/remote/remote_pytest.py --pick sim`, 노트북 금지)

G1 직선 차로 역주행 → 회전 없이 HOLD → 사람. G2 회전 자리 역주행 → `PIVOT`으로 반시계 복귀. G3 차로 밖 모서리 앞뒤 막힘 → R7 한 번, 출구 방위. G4 G3 + 동료 0.30 m 안 → 사람. G5 가장자리 dithering → P1 원인으로 막힘, 후진 반복 없음. G6 두 대 고리 입구, 한 대 역주행 → 구역 수용 1, 대기 또는 사람. G7 lane cue와 `REALIGN`이 같은 막힘에서 함께 돌지 않음. G8 `PIVOT` 중 E-stop → 정지, 해제 뒤 재개 없음. G9 trip 로봇 → `WAIT`만. 수용: 접촉 0, 테이프 바깥 끝을 넘는 회전 0, 사람 무응답에 움직임 0.

### Alternatives

- **AI PC가 회전 각을 제안한다.** D-577 7항 위반(새 움직이는 답). 거절.
- **lane cue가 막힘 중에도 회전한다.** 한 로봇에 두 보정 채널. 거절(10항).
- **역주행이면 그 자리에서 U-턴한다.** 직선 차로에서 회전 원 0.0926 m > 0.080 m. 거절.
- **새 원인에도 R6 후진.** 놓친 막힘의 뿌리가 후진 재시도 반복이다. 거절.

### Consequences

- 놓치던 흔들림·정체가 큐에 올라온다. 처음에는 사람 행이 늘어난다(P1).
- 지금 자세 불확실성(u ≥ 0.018 m)에서는 `REALIGN`이 회전 자리와 일부 바깥 기준 경우에만 고를 수 있다. P2 그림자가 적용률을 잰다. 낮으면 P3를 미루고 사람 단계가 답이다.
- CORE API에 결정 단어 하나·능력 하나·막힘 원인 둘이 생긴다(D-18 API Reference).

### Verification

- 이 기록은 문서다. `python tools/harness/rosy_harness.py lint`는 형식 증거다.
- 단계별 시험과 시나리오는 위 표. 호스트 pytest는 장치·현장 수용이 아니다.

### 열린 질문

1. `no_progress`·`dithering` 문턱과 창(CORE가 재생 자료로 정한다).
2. 회전 중 IR 가운데 정지가 테이프를 보고 회전을 끊는가(CORE 확인).
3. P2 적용률이 얼마면 P3로 가는가(사용자).

**Related:** D-2, D-18, D-395, D-407, D-424, D-430, D-438, D-468, D-511, D-517, D-541, D-573, D-577.