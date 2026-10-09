# 짧은 경계 조각의 모서리·한쪽 경계 재생 게이트

**판정: 10/6의 가로 페인트·벽 장면에서 회전 후보를 STOP으로 줄였으나 차로 추종 수용은 HOLD.** 이 기록은 원본 MCAP의 후보 검출기 비교다. 사람 승인 물리 경계 ID, 촬영 당시 승인 카메라 지면 보정, CORE 주행 결과가 없다.

## 반례와 처리

- [실물 한 프레임 분석](../lane-live-line-ambiguity-2026-10-09/result.md)의 거절된 피치 후보는 경계 0개에서도 `corner_left`를 만들었다. 앞선 수정으로 모서리 방향을 처음 잡을 때 현재·직전 닫힌 쪽 경계를 요구하게 했다.
- 10/6 `091340Z` 프레임 614에서는 그 게이트를 통과한 길이 0.061m의 새 왼쪽 조각과 횡단 후보가 `corner_right`를 만들었다. 이후 28프레임의 그 조각은 0.079m 이하였고, 화면에서는 벽 아래와 횡단 페인트가 겹친다. 이는 **벽 오인식 후보**이며 사람의 물리 선 판정은 아니다.
- 새 모서리 방향의 근거는 길이가 최소 반 차폭(`lane_half_width_m`)인 닫힌 쪽 경계로 제한했다. 길이가 짧아도 직전 프레임에서 이어진 한쪽 경계는 유지하고, 처음 나타난 짧은 한쪽 조각은 STOP한다. 지도에서 굽이를 예고한 `bend_expected`와 현재 프레임의 굽이 후보가 함께 있을 때만 짧은 조각의 기존 선택을 유지한다. 이 게이트는 이전의 `error/confidence/visible` 계약과 CORE 단일 `/cmd_vel` 권한을 바꾸지 않는다.

## 원본 재생 비교

[재생 코드](evidence/replay.py)는 10/6 두 세션의 `source-readback-1006.json`과 manifest·bag 파일의 해시, 10/7의 [207프레임 원본 증명 목록](../lane-1007-source-proof-2026-10-08/result.md)과 JPEG 해시를 검사한다. 같은 세션 내 영상 간격이 0.5초를 넘으면 keeper를 초기화한다. `LaneKeeper(corner_turning=True)`를 두 지면 가설(공칭 8°, 10/6 재생의 후보 11.8°)로 돌리고, 프레임별 `strategy/reason/error/confidence`를 X:에 저장한다. 둘 다 촬영 당시 승인된 보정값이 아니다.

| 입력·지면 가설 | 수정 전 → 수정 후 전략 변화 | 해석 |
|---|---|---|
| 10/6 원본 3,129장, 8° | `corner_left → none` 176, `left_only/right_only → none` 3 | 모두 STOP 후보 증가. `091340Z` 466–641번의 회전 후보가 사라졌다. |
| 10/6 원본 3,129장, 11.8° | `left_only → corner_ahead` 1 | STOP 증가 없음. 모서리 후보 `corner_ahead` 3, `corner_left` 11, `both` 21이 남는다. |
| 10/7 MCAP 원본 207장, 8°·11.8° | 두 설정 모두 프레임별 출력 변화 0 | 이 수정의 10/7 비회귀 확인이며, 한쪽 경계 ID의 정확성 증명은 아니다. |

10/6 입력 근거는 [원본 후보 증명](../lane-1006-mcap-candidates-2026-10-08/result.md)에 있다. 재생 출력은 `X:/DevTemp/lane-live-readonly-20261009/tracked-replay-1006-final.json`(SHA-256 `a28d6636c8661e02db596f3e33f25d7bd98bb799fa270424bf4d9f8057691a3d`), `.../tracked-replay-1007-final.json`(SHA-256 `5a8e6e93a2b2f2beb7fceda184719e389bf483b10de5a92df9f93f54504bf162`)이다. 비교 기준 코드는 `7d66eaa7a0a2d2a21f0b541c91a4ce213b0c1cf6`; 현재 재생의 `lane_keep.py` SHA-256은 `25868e820e3138ef03027b9feab709c72725c915ac4890e352ed2c0220dc6e93`이다. 파일 경로는 X:에만 두고 원본 화소·프레임별 출력을 공개 저장소에 넣지 않았다.

```text
New-Item -ItemType Directory -Force X:/DevTemp/lane-live-readonly-20261009
python docs/validation/lane-corner-seed-2026-10-09/evidence/replay.py X:/DevTemp/projects/rosy-platform/2026-10-08--045427--lane-evidence-learning--e0687b/evidence/recordings --out X:/DevTemp/lane-live-readonly-20261009/recheck-1006.json
python docs/validation/lane-corner-seed-2026-10-09/evidence/replay.py X:/DevTemp/lane-goal-20261008/1007-proven/verified-inputs.jsonl --out X:/DevTemp/lane-live-readonly-20261009/recheck-1007.json
```

## 남은 판정

10/6·10/7의 `BOTH/ONE/corner`는 검출기 후보이며 승인 차선 정답이 아니다. 특히 11.8°에서 새로 나온 `corner_ahead` 1프레임의 물리 의미와 잔여 모서리 후보는 사람 검수가 필요하다. 기존 [R0 재생 게이트](../lane-1006-current-r0-replay-2026-10-08/result.md)는 10/6 차선 추종을 수용하지 않았고, 이 국소 STOP 보강이 그 결과를 뒤집지 않는다. 승인 GT와 장치별 지면 보정, SIM 주행, CORE 상태·최종 명령, 물리 수용까지는 계속 HOLD한다.

## 계획을 쓰는 주행 전환 가설

한 프레임의 선 소실마다 멈추는 것은 목표가 아니다. Fleet의 선택된 지도 간선·교차로 지시를 CORE가 구간 근거로 사용하고, 카메라는 보이는 경계로 위치 오차를 줄인다. 단, 지도 경로는 보이지 않는 바닥이나 새 흰 조각의 물리 경계 ID를 증명하지 않는다. 다음 표는 **검증할 구간별 동작**이며 이 문서가 모드를 켜거나 주행을 승인하지 않는다.

| 상황 | 사용할 근거와 동작 | 만료·거절 |
|---|---|---|
| 양쪽 경계 | 같은 차로의 신선한 좌우 경계와 차체 여유로 가운데를 추종 | 폭·방향 충돌, 차체 여유 부족 |
| 한쪽 경계 | 같은 물리 경계의 연속성, 승인 차폭, 지도 구간/오돔과 맞는 쪽을 감속 추종. 가려진 반대쪽은 `inferred`로만 기록 | 경계 ID 불명, 지도·영상 불일치, 오차가 차체 여유를 넘음 |
| 잠깐 양쪽 소실 | 직전 확신 구간에서 무장한 [D-476 bridge](../../adr/D-476-lane-loss-expected-road-bridge.md)를 CORE가 짧게 사용. 기본 꺼짐, 거리·시간·바닥·몸체 경로 조건 유지 | 오돔 불연속, 신선한 경로 여유 없음, 거리·시간 한도 초과 |
| 계획된 굽이·ring | Fleet의 `bend`·`exit_segment`를 [D-507](../../adr/D-507-lane-trip-leg-structure-and-site-floor.md)·[D-520](../../adr/D-520-map-guided-ring-arc-following.md)의 CORE 동작에 사용하고 카메라는 제한된 옆 보정만 제공 | 지도 ID·지시 창·구간 길이 불일치, IR/LiDAR/바닥 거절, 끝에서 차로 재획득 실패 |

이 표의 모드는 서로 다른 최종 명령 발행자를 만들지 않는다. CORE만 `/cmd_vel`을 내며 매 틱 몸체가 쓸고 갈 경로를 검사한다. 현재 Fleet→CORE의 교차로·굽이·호 지시는 있지만, Fleet→keeper의 [`line/route_context`는 D-531 제안](../../adr/D-531-route-context-to-lane-keeper.md)으로 아직 구현되지 않았다. 현재 로봇의 기본 카메라 모드도 `line`이고 이번 변경은 `keep`에만 적용된다. 지도가 카메라 pitch를 자동 승인하지 않는다. 정지 촬영의 보정 후보는 장치·카메라·시각·revision을 묶어 별도 승인한 뒤 적용해야 한다.

**경계 통과:** 계획된 교차로·굽이의 경계 통과는 지시의 기대 창과 CORE 운동 허가 안에서만 평가한다. 장애물 때문에 임의로 다른 차로를 쓰는 우회는 현재 허가된 간선·통행권·차체 전체 경로 근거가 없으므로 일반 추종의 폴백이 아니다. 경계 밖이 `undrivable`이라고 단정하거나 `drivable`의 역마스크를 자유 공간으로 쓰지 않는다. 미관측 바닥은 unknown으로 남긴다.

다음 비교는 10/6·10/7의 같은 물리 경계 ID·가림 원인·재출현을 사람이 승인한 뒤 고정한다. 현재 R0와 구간별 후보를 같은 입력에서 비교해 가림 통과·재획득 거리, 불필요한 STOP, 잘못된 경계 유지, 페인트/차체 경계 침범을 함께 센다. 벽·횡단선·분기·바닥 불명, 오돔 정지/점프, 지도 ID·시각 불일치를 음성 사례로 넣고 그 경우 잘못된 계속 주행은 0이어야 한다. 다음은 닫힌 루프 SIM, 마지막이 서명된 장치의 설치·CORE 명령·물리 경로 확인이다. 10/7의 [R0 실패](../lane-1007-r0-gate-2026-10-08/result.md)는 `ONE` 104프레임과 RoadState 목표가 페인트에 닿은 33프레임을 기록했으므로, 그 결과를 한쪽 선 추종 성공으로 재해석하지 않는다.
