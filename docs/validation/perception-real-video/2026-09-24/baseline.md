# 실물 영상 재생: 현재 카메라 인식 기준선 (D-199 근거)

**증거 등급: REAL VIDEO REPLAY, host only. DEVICE: NOT RUN.**

판정: **현재 인식으로는 실물 로봇을 주행할 수 없다.**

## 실행 조건

- 저장소 코드 `3a17a0aa`(local main, `54bd0f3e` 포함). 저장소 코드는 바꾸지 않았다.
- 입력: `data/teleop/learning/teleop_20260919_151213_part01..07.mp4` — 7개, 4981프레임, 약 623 s, 8 fps, 320x240.
- 카메라 기하는 같은 영상에서 추정한 실물 값이다. 기울기 8.0° 아래, 좌우 화각 59.3°(fx 281.6), 렌즈 높이 67 mm,
  앞 오프셋 34 mm. 측정된 roll 0.9°는 코드에 roll이 없어 모델링하지 않았다.
  바닥 평면은 `camera_ground.simulation_ground_plane`에 이 값을 넣어 만들었다(max_range 0.6 m).
- 재생 스크립트는 저장소 밖에 있다(세션 scratchpad `realrun/replay.py`, 출처 기록용). 저장소 도구가 아니며 다시
  돌리는 절차를 약속하지 않는다. 설계의 P2 재생기(`perception_replay.py`)가 이 역할을 넘겨받는다.
- 영상에는 오도메트리가 없다. BEV 계열 모드는 자세 없이는 결과를 내지 않으므로 **대체 시각 오도메트리**
  (바닥 KLT 특징 → 바닥 평면 → RANSAC 강체 맞춤, 합성 움직임에서 약 1 mm / 0.1° 확인)를 넣었다. 추정 주행 거리 약 20 m.
- **정답(ground truth)이 없다.** 아래 "사용 가능"은 출력이 있다는 뜻일 뿐 맞다는 뜻이 아니다. 벽을 선으로 본
  출력도 사용 가능으로 센다.
- 돌린 모드:
  - `centre`: `LaneBoundaryTracker`, `map_v2_fleet_lane.launch.py`의 인자(문턱 180, ROI 0.25/0.75, washed 0.75)
  - `line`: 장치 기본값 `camera_lane_mode=line`(`line_follow.yaml`, 문턱 180, roi_top 0.40, min_pixels 80)
  - `lane`: `line_follow.yaml`의 lane(코너 회전 끔)
  - `road`: `road.detect_road_observation` 기본 설정 + 같은 바닥 평면
  - 돌리지 않음: route_a/route_b/route_ab(차선 그래프와 지도 자세 필요), edge_left

## 결과

| 항목 | 값 |
|---|---|
| `centre` 등급 비율 | BOTH 13.0% · ONE 36.0% · MEMORY 14.3% · STOP 36.7% |
| `centre` 최장 STOP | 713프레임(89 s) |
| `line`(장치 기본) 출력이 벽 픽셀로 조향한 프레임 | 22.4% |
| `line` 출력 비율(신뢰도 ≥ 0.35) | 88.4% — 위 벽 조향을 포함한 값 |
| `lane` 출력 비율(신뢰도 ≥ 0.35) | 63.2% |
| `road.py`가 정지선을 보고한 프레임 | 89.5% (그중 49.0%가 벽 위) |
| 벽이 테이프보다 밝은 프레임 | 67% |

비교: 2026-09-23 Gazebo route_ab 순회(25° 세계)에서 CORE가 받은 인식은 BOTH 12% · ONE 73% · MEMORY 16%였다.
원인은 `lane_bev.py`의 좌우 라벨 뒤바뀜과 왼쪽 선 단독 시작 경로 부재다(설계 §1.1).

## 주요 실패

1. **흰 벽이 고정 문턱 180을 넘는다.** 벽 면이 BEV에 폭 약 10 cm의 "선"으로 투영된다. 벽을 정면 0.2 m 앞에 둔
   프레임에서 `centre`는 BOTH, 신뢰도 1.00, 오차 -0.01, 즉 벽으로 직진하라고 답했다(`p04_0492_wall_ahead_BOTH.jpg`).
2. **실물 테이프(회색값 169–201)가 문턱 180에서 조각난다.** 두 선이 선명히 보여도 오른쪽 선이 1–2칸 점으로 깨져
   차로폭 쌍이 없고, 시작하지 못해 STOP이다(`p01_0600_threshold_fragmented.jpg`).
3. **59° 화각, 8° 기울기에서는 근거리에 차선 쌍이 들어오지 않는다.** 쌍으로만 시작하는 추종기는 곡선·교차에서 STOP에 머문다.

잘 되는 장면도 있다. 두 선이 모두 보이는 왼쪽 곡선에서 `centre`는 BOTH, 신뢰도 1.00, 오차 -0.02로 맞게 답했다(`p06_0104_good_curve.jpg`).

## 결론과 다음 조건

- 25° 세계에서 받은 이전 시뮬 합격은 장치 증거가 아니다.
- 장치 주행 전에 필요한 것: 벽 밑선 아래 바닥만 보는 마스크, 적응형 문턱, 한 줄 시작 경로.
- 구조와 단계는 [D-199](../../../adr/D-199-camera-perception-contracts-and-backends.md)와
  [인식 구조 설계](../../../plans/2026-09-24-perception-architecture-design.md)를 따른다.

## 원자료(출처 기록)

오버레이 영상(`overlay_p01..07.mp4`), 프레임별 `frames_p0N.jsonl`, `summary.json`, `summary_stats.json`, 스틸 16장은
세션 scratchpad `realrun/out/`에 있다. 영상과 큰 이미지는 저장소에 넣지 않는다. 여기에는 스틸 3장만 둔다.
