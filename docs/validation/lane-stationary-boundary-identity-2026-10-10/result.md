# 정지 중 경계 교체 반례와 기억 중단

**판정: SOURCE 합성 반례에서 `edge_left` 경계 기억 중단 확인. 차선 주행 수용 HOLD.** 기준 코드는 `203df5a1600e`이며 이 기록의 수정은 `LaneEdgeFollower`의 정지 odom 경계 일관성 검사다. 일반 카메라 `keep` 추종, RoadState 섀도, Fleet 지도 경로, CORE 명령은 이 수정의 대상이 아니다.

## 재현한 실패

`middleware/perception/test/lane_sim.py`의 바닥 렌더러로 양쪽 선이 있는 직선을 먼저 보여준 다음, **같은 odom 자세**에서 왼쪽 선을 30 mm 안쪽으로 옮긴 단일 선 영상으로 바꿨다. 수정 전 `LaneEdgeFollower`는 새 선을 기존 왼쪽 경계로 이어받아 `error=+0.252` 관측을 냈다. 오른쪽 선을 30 mm 안쪽으로 바꾼 반례도 `error=-0.218` 관측을 냈다. 이 숫자는 합성 카메라 영상의 추종 출력이며 실제 벽·물리 경계 ID나 주행 결과가 아니다.

수정은 odom 이동 ≤2 mm, yaw 변화 ≤1°일 때만 적용된다. 기존 기억과 새로 고른 좌·우 페인트 성분을 **둘 다 보이는 전방 거리 행**에서 비교해 횡방향 중심 이동의 중앙값이 20 mm보다 크면 기억을 버리고 `boundary_identity_unconfirmed`로 이번 프레임의 관측을 내지 않는다. 코너 인계도 그 프레임에 명령 후보를 내지 못한다. 동일 선 재관측과 이동 중 한쪽 선 소실은 기존 추종을 유지한다. 검사 행이 8개 미만이면 이 규칙은 결론을 내리지 않으며 기존 다른 게이트가 결정한다.

수정 전 두 반례 시험은 각각 실패했다. 수정 후 `middleware/perception/test/test_lane_edge.py`의 합성 직선·굽이·호·코너 인계 **전체 51개 시험**이 통과했다. 같은 작업 트리에서 `middleware/perception/test/`는 **2874 통과, 110 건너뜀**, 문서 배치·모듈 구조 아키텍처 검사는 **49 통과, 1 건너뜀**이었다. 모든 실행은 `-p no:cacheprovider`로 수행했고 `test/known_failures.py` 비교에서 새 실패가 없었다. 이는 호스트 SOURCE 시험이며 Gazebo 폐루프나 장치 시험은 아니다.

## 실제 10/7 입력과의 경계

같은 브랜치 기준 `203df5a1600e`에서 출처가 확인된 `rosy_60` 원본 두 세션을 아래처럼 다시 재생했다. `road_replay.py`는 이번에 수정한 `LaneEdgeFollower`를 구동하지 않으므로 수치가 좋아졌다는 주장이 아니다. 11.8° 투영은 당시 승인 카메라 보정이 아닌 후보 값이다.

```text
python learning/training/perception/road_replay.py <session> --out X:/DevTemp/boundary-counterexample-20261010/<case> --compare-boundary --pitch-deg 11.8
```

| 10/7 세션 | 프레임 | RoadState TRACK / STOP | RoadState 목표 페인트 위 비율 | 직선 평균 절대오차 | 가설 전환/100 직선 프레임 |
| --- | ---: | ---: | ---: | ---: | ---: |
| `143038` | 124 | 89.5% / 10.5% | 29.7% | 0.92 | 0 |
| `143211` | 83 | 0% / 100% | 0% (주행 목표 없음) | 계산 불가 | 1.923 |

- `143038`의 `metrics.json` SHA-256 `47fd915c8355db51d93321981f2df2876c8b0fd4c879b74a826df07c654fd216`.
- `143211`의 `metrics.json` SHA-256 `1079ffbf9521e939db166bf6018b5f77d86af00034237dcabd8d9f81200311a6`.

이 결과는 [앞선 10/7 재생](../lane-1007-current-replay-2026-10-09/result.md)의 주요 실패를 그대로 재현한다. 사람 승인 동일 물리 경계 ID와 촬영 당시 카메라 보정이 없으므로 ONE이나 TRACK을 주행 승인 정답으로 세지 않는다.

## 남은 반례와 다음 검증

같은 장소에 새 선이 정확히 겹치거나 벽 밑면이 같은 모양으로 들어오면 **카메라+odom만으로 두 물리 ID를 구분할 수 없다**. 이 정지 변화 검사는 그런 경우를 해결하지 않는다. 20 mm도 현장 카메라 투영 오차 상한이 아닌 합성 반례의 보수적 중단값이다. 실제 운영 전에는 사람 검수된 물리 경계 ID, 시각이 맞는 LiDAR/물체 가림, 지도/카메라 보정 오차, 직선·곡선·분기 재생과 CORE STOP readback을 함께 확인해야 한다. 두 선이 모두 불확실하면 STOP, 최종 `cmd_vel`은 CORE 한 곳에서만 발행한다.
