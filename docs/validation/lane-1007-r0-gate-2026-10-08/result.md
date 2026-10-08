# 10/7 원본 영상의 현재 R0 재생 게이트

증거 등급: `9fc0a761f` 로컬 `main`의 **호스트 오프라인 재생**. 실물·ROS-SIM 주행이나 사람 승인 차선 정답은 아니다. 입력 MCAP의 SHA-256과 207/207 원본 화소 검증은 [출처 기록](../lane-1007-source-proof-2026-10-08/result.md)에 있다.

두 세션 `20261007T143038Z_rosy_60`, `20261007T143211Z_rosy_60`에 각각 다음 명령을 실행했다. `<session>`은 `X:/DevTemp/projects/rosy-platform/2026-10-08--045427--lane-evidence-learning--e0687b/evidence/recordings/<session>`이며 출력은 X:에만 둔다.

```text
python learning/training/perception/road_replay.py <session> --out X:/DevTemp/lane-goal-20261008/replay-current-<session> --compare-boundary --pitch-deg 11.8
python learning/training/perception/road_replay.py <session> --out X:/DevTemp/lane-goal-20261008/replay-nominal-<session> --compare-boundary
```

| 세션 | 후보 pitch 11.8° | 기본 공칭 지면 | 판정 |
|---|---|---|---|
| `143038Z`, 124프레임 | RoadState `TRACK` 111/124 (`0.895`), `STOP` 13/124; 경계 `BOTH` 20, `ONE` 104 | RoadState·경계 모두 `STOP` 124/124 | 후보 pitch의 `TRACK`은 R0 실패. `on_line_le_keep`, `on_paint_le_keep`, 직선 오차, NIS, coast survival 게이트가 실패했다. RoadState의 페인트 위 목표 비율 `0.297`은 keeper `0.008`보다 높다. |
| `143211Z`, 83프레임 | RoadState·경계 모두 `STOP` 83/83 | 동일하게 `STOP` 83/83 | 정지 상태지만 검출기 hypothesis switch 게이트는 실패했다. 이를 실제 경계 전환의 정답으로 해석하지 않는다. |

후보 pitch의 `metrics.json` SHA-256은 세션 순서대로 `9579aaa3b5ef27146647374ddcd0095ce05530880027e59430a8fa267b530d5f`, `c36dedf95eefc23709fa4424a01e62c40e249ca33886bb49c43e7354f1356609`; 기본 지면 결과는 `125463bf9307c92e188e1c1f5795d8b29033b4134ccd67ef93461a557d19141e`, `062a912b21b5bd5a0e2c9742ff5e31638d5bc6363971ac3afdb5d4412609d054`이다. 네 결과 모두 `validated=false`다.

원본 화소의 표본 `143038Z` 프레임 14·15·34·35·45·60·80·100·123과 `143211Z` 프레임 0·11·55·58·80을 시각적으로 재확인했다. 횡단 표식, 원형 교차 표식, 시야 회전이 섞여 있다. **이 표본에서 물체 가림 뒤 같은 물리 경계 재출현을 승인할 근거를 찾지 못했다.** 이는 전체 207프레임의 사람 검수 결과가 아니다.

따라서 11.8° 재생에서 나온 `TRACK`이나 `BOTH`를 주행 허가·학습 정답으로 연결하지 않는다. 촬영 당시 보정 revision과 `line/keep_debug`가 없고, R0 자체 게이트도 실패한다. 다음 실험은 같은 경계 ID와 소실 원인을 사람이 검수한 양성·벽/분기 음성, 새 녹화의 지면 투영값과 시각 동기, 그리고 D-378 재생 게이트를 요구한다. 불확실한 경계는 STOP이며 CORE만 최종 `cmd_vel`을 낸다.
