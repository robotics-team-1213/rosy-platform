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
