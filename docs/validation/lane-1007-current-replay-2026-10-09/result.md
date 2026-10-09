# 10/7 원본의 현재 차선 재생과 보정 경계 (2026-10-09)

**판정: 오프라인 후보 분석, 주행 HOLD.** 로컬 `main` commit `7d9eb18e2`에서 [출처가 증명된 10/7 MCAP 207프레임](../lane-1007-source-proof-2026-10-08/result.md)을 `road_replay.py`로 다시 실행했다. 이후 `main`의 `a7e4eef5a`까지 재생기·keeper·경계 추적기 파일은 바뀌지 않았다. 촬영 당시 로봇은 자율 차선 주행을 하지 않았고, 이 재생에는 사람 승인 물리 경계 ID나 바닥 마스크가 없다.

```text
python learning/training/perception/road_replay.py <session> --out X:/DevTemp/lane-r0-current-1007-20261009/<case> --compare-boundary [--pitch-deg 11.8]
```

`<session>`은 `X:/DevTemp/projects/rosy-platform/2026-10-08--045427--lane-evidence-learning--e0687b/evidence/recordings/20261007T143038Z_rosy_60` 또는 `.../20261007T143211Z_rosy_60`이다. 11.8°는 당시 장치가 쓴 승인 보정이 아니라 비교용 **후보 투영**이다. 모든 출력은 `validated=false`이고 X:에만 저장했다.

| 세션 / 투영 | R0 단계 | odom 경계 단계 | 주요 게이트 |
|---|---|---|---|
| `143038` / 11.8° | TRACK 111, STOP 13 | BOTH 20, ONE 104 | 페인트 위 목표 0.297, 직선 평균 절대오차 0.92, NIS 상위 비율 0.6441, coast 생존 0.909: 각각 해당 게이트 실패 |
| `143038` / 공칭 | STOP 124 | STOP 124 | 추종 오차·coast는 관측 부족으로 `null`; 공허한 통과를 합격으로 세지 않음 |
| `143211` / 11.8° | STOP 83 | STOP 83 | 가설 전환 1.923/100 직선 프레임: 게이트 실패 |
| `143211` / 공칭 | STOP 83 | STOP 83 | 가설 전환 1.923/100 직선 프레임: 게이트 실패 |

124장과 83장 모두 경계 추적기에 신선한 odom이 붙었다. 그러나 `143038`의 ONE 104장은 **같은 물리 경계**의 증거가 아니다. 횡단·분기 표식이 섞인 [원본 표본 판독](../lane-1007-r0-gate-2026-10-08/result.md)은 해당 구간의 경계 이어받기를 실패 후보로 분류했고, 이번 재생은 그 판정을 뒤집지 않는다. `143211`의 STOP은 유지됐다. 넓은 학습 drivable 마스크만으로 그 STOP을 해제하지 않는다([위험 구간](../lane-risk-segments-2026-10-09/result.md)).

| 출력 (`metrics.json` / `frames.jsonl`) | SHA-256 |
|---|---|
| `143038-pitch118` | `c89d9c940ff0c38e9487f6299deddbaf6fe69156ca0037e6723bb281ec067290` / `8907621ecf6ff1d27633e3dd63bc44947de7364f3f5043c6137948ba7fa652b9` |
| `143038-nominal` | `05e47db28eeff3544c2a6388318bb32071a8059f9ebb3653f9db4f4b5aaf7097` / `56242801c64591b90feea8a2b1cfa55cde266eb47a0a9eacdb49a95b088126d0` |
| `143211-pitch118` | `3b4a00b258d82ad9ca3e33eb6f8f2b5a5f5efe024bce556454767c362f7c2b79` / `b7f8a26fb53ec5355930cc6f6f8a8a1d6116ab847d3432b80beb9b7613317aa0` |
| `143211-nominal` | `3a87e7ff46e1b2385597dbdb6b925bba8ebf6c98b38a0e0cff08a8df311b06ea` / `d7868b9160f3d5014b8e1123c133d8796b844d6886cb601402251c384c5148af` |

## 다음 결정의 근거

`LaneKeeper._track`은 아직 로봇 좌표의 횡위치·방향만으로 직전 선을 이어받는다. odom을 넣어도 정지 중 같은 자리에 다른 칠이 나타나는 반례는 물리 ID를 판별할 수 없으므로, 이 재생만으로 ONE/MEMORY 주행 권한을 넓히지 않는다. 별도 `LaneBoundaryTracker`는 odom 기억을 갖지만 이번 ONE 출력 역시 승인 정답과 비교하지 못했다([경계 식별 분석](../lane-boundary-identity-2026-10-09/result.md)). 다음 유효한 게이트는 두 물리 경계 ID와 소실 원인, 벽·분기 음성을 사람이 검수한 뒤 같은 입력에서 false carry·연속 miss·STOP을 비교하는 것이다.

실물 `rosy_26`에서 2026-10-09 읽은 자동 카메라 맞춤 후보는 `recommended=false`(`too few wall returns in view`)였고 LiDAR 방향도 URDF 공칭이었다(`X:/DevTemp/lane-live-readonly-20261009/camera-auto-candidate.json`). 이는 `rosy_60`의 10/7 촬영 보정이 아니다. 현재 `rosy_26`의 수치 투영에도 [운영자 override 때문에 지면 오차 상한이 없다](../lane-live-ground-readback-2026-10-09/result.md). 승인 보정과 동일 시각의 경계·지도 자세가 없으면 Fleet 계획은 예측으로만 쓰고, 불확실한 경계에서는 STOP, 최종 `cmd_vel`은 CORE 한 곳에서만 낸다.
