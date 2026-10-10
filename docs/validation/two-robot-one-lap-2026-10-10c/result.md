# 현장 지도 v5의 양방향 한 바퀴 계획 계산, 2026-10-10

**판정: 활성 지도에서 두 유한 경로 계산 성공, 실행·안전 수용 HOLD.** Fleet의 읽기 전용 `/api/fleet/site-map/active` 응답을 AI PC의 기존 `ai_observer` 권한으로 가져와 `X:/DevTemp/one-lap/field-map-v5.json`에 두었다. 후보 `feat/one-lap-console` HEAD `5654740e6`의 `SiteMap`·`build_graph`·`plan_trip`·`unsupported`로 로컬 계획 계산을 수행했다. pytest는 노트북에서 실행하지 않았다.

- 지도: `map_v2_fleet` v5, Fleet SHA-256 `cd13474068721637c1824f7b97422eef6370fd3ca5c3788433d060b159acf94f`. 원본 응답 파일 SHA-256 `c9be7cc458316d60b5925a4560d6ffda2386df8bf623238e4e9b82fb623bf337`.
- 방법: 각 이름 있는 출발 장소의 좌표와 통행 방향의 차선 접선 자세에서 `PlanRequest(to=start, via=(other,))`를 계산했다. `pinky_pro`, `drive_modes={lane}`, 상한 0.04 m/s, 유한 trip으로 `unsupported`를 검사했다. 이는 실제 로봇의 현재 자세를 계획 시작 자세로 가장하지 않는다.

| 출발·경유·복귀 | 길이 | 계획 차선 순서 | 마지막 action | 차로 실행 검사 |
|---|---:|---|---|---|
| `W_mid → E_mid → W_mid` | 7.3752 m | `west → ring_in_sw → ring_s → ring_out_se → east_out → east → ring_in_ne → ring_n → ring_out_nw → west_out` | `stop @ W_mid` | `junction_turn:true`에서 거절 없음; false면 `west / JUNCTION_TURN_UNSUPPORTED` |
| `E_mid → W_mid → E_mid` | 7.3752 m | `east → ring_in_ne → ring_n → ring_out_nw → west_out → west → ring_in_sw → ring_s → ring_out_se → east_out` | `stop @ E_mid` | `junction_turn:true`에서 거절 없음; false면 `east / JUNCTION_TURN_UNSUPPORTED` |

계산 출력은 `X:/DevTemp/one-lap/field-route-plan.txt` (SHA-256 `ebe0bd34aac94d7d8981dbc2d6bb5a76db91a67d59f20d66da9034182af4bb2e`)에 있다. 모델 PC `--pick sim`은 가용 메모리 7.2 GB로 요구 8 GB를 채우지 못했다. 실제 출발 위치·방향, `rosy_40`의 회전 증거, 교통 점유, 차체 경계, 정지 거리는 이 계획 계산에서 검증되지 않았다. 두 로봇 주행 명령은 보내지 않았다.
