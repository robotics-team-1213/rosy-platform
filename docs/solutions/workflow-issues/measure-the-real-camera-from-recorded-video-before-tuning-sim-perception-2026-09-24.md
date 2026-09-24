---
title: 시뮬에서 인식을 튜닝하기 전에 녹화 영상으로 실물 카메라부터 잰다
date: 2026-09-24
category: workflow-issues
module: sim/gz_sim + core/control (map_v2_fleet 차선 인식, 카메라 프로필)
problem_type: workflow_issue
component: development_workflow
severity: high
applies_when:
  - "Gazebo나 오프라인 렌더러에 카메라를 새로 두고 인식 임계값을 정할 때"
  - "카메라 기울기·화각·높이를 CAD나 추정값으로 정하고 실측한 적이 없을 때"
  - "실물 로봇 주행 영상이 있는데 아직 시뮬 가정과 대조하지 않았을 때"
  - "시뮬에서 받은 합격이나 물리적 설계 결정(마커 모양·높이)이 카메라 시야 가정에 기대고 있을 때"
symptoms:
  - "시뮬 합격과 주차 마커 선택이 실물과 다른 카메라 가정 위에 서 있었음"
  - "밝기 문턱 인식이 실물의 흰 벽을 차선으로 오인할 수 있음"
root_cause: missing_validation
resolution_type: workflow_improvement
related_components:
  - testing_framework
tags: [camera-calibration, sim-to-real, perception, gazebo, teleop-video, crosswalk, pinky-pro]
---

# 시뮬에서 인식을 튜닝하기 전에 녹화 영상으로 실물 카메라부터 잰다

## Context

map_v2_fleet 차선 시뮬레이션은 카메라를 25° 아래로 기울이고(`src/sim/gz_sim/launch/map_v2_fleet_lane.launch.py`의
`math.radians(25.0)`), 좌우 화각 66°, 320x180 해상도를 썼다. 벽은 어둡고 바닥은 균일하다고 가정했다.
이 가정 위에서 교차로·순회 합격을 받았다. 3단계 주차 마커도 "25° 카메라는 6 cm 위를 못 본다"는
전제로 낮은 경사 마커를 골랐다.

2026-09-19 수동 주행 영상(`data/teleop/learning/`의 `teleop_20260919_151213_part01.mp4`부터 `part07`까지, 320x240,
8 fps)으로 실물 Pinky 카메라를 추정했더니 가정이 거의 다 틀렸다
(`docs/plans/2026-09-24-perception-architecture-design.md` 1.2절):

| 항목 | 실물(추정) | Gazebo 가정 |
|---|---|---|
| 기울기 | 약 8° 아래 | 25° |
| 좌우 화각 | 약 59° (fx 약 281.6 px) | 66° |
| 렌즈 높이 | 약 67 mm | 60.2 mm |
| 해상도 | 320x240, 8 fps | 320x180, 5 Hz |
| 벽 | 흰 폼보드. 프레임의 67%에서 테이프만큼 밝거나 더 밝음 | 어두운 청회색 |
| 바닥 | 회색 카펫, 잔무늬 | 균일한 어두운 바닥 |

매트도 CAD와 약 10% 다르다. 이 세션의 영상 추정으로 차선 간격 대 횡단보도 줄 간격 비는 실물 약
5.1, CAD 4.62였다. 설계 문서의 차선 간격 추정(약 195-205 mm, CAD 185 mm)과 같은 방향이다.

## Guidance

1. **실물 영상이 한 편이라도 있으면 시뮬 튜닝 전에 카메라부터 잰다.** 기울기, 화각(fx),
   렌즈 높이, 해상도·프레임률, 벽·바닥 밝기 분포를 뽑아 시뮬 가정과 표로 대조한다.
2. **횡단보도 줄을 보정 표적으로 쓴다.** 등간격 평행 막대라 체커보드처럼 쓸 수 있다. 이
   세션에서는 횡단보도 줄 모서리로 `cv2.calibrateCamera`를 돌리고 차선 소실점으로 기울기를
   교차 확인했다. 표적을 따로 만들 필요가 없다.
3. **카메라 값은 소스별 프로필 하나에서 나오게 한다.** 시뮬 월드, 오프라인 렌더러, 인식 노드가
   각자 상수(25° 같은)를 들고 있으면 한 곳을 고쳐도 나머지가 옛 가정으로 남는다.
4. **가정이 바뀌면 그 가정 위에서 받은 합격을 무효로 표시한다.** 시뮬 합격과, 카메라 시야를
   근거로 한 물리적 결정(여기서는 주차 마커)을 다시 연다.
5. 트랙 치수는 CAD가 아니라 실물 매트를 자로 잰 값을 따른다.

## Why This Matters

실물 카메라가 거의 수평이라 시야 위쪽에 흰 벽이 크게 들어온다. 밝기 문턱만 쓰는 인식은 그
벽을 차선으로 읽는다. 25° 세계에서는 벽이 거의 안 보이므로 시뮬에서 이 결함이 드러날 수 없었다.
틀린 전제 위에서 쌓은 합격, 임계값, 마커 설계는 실기에서 모두 다시 해야 한다. 카메라를 먼저
재는 데는 영상 몇 분과 보정 스크립트 하나면 된다.

## When to Apply

- 새 로봇, 새 카메라 마운트, 새 트랙이나 월드를 시작할 때
- 실물 영상이 생긴 직후. 시뮬 합격이 쌓이기 전일수록 싸다
- 카메라 시야에 기대는 물리적 결정(마커, 표지 높이)을 내리기 전

## Examples

- 이전: 25° 가정으로 "6 cm 위는 안 보인다"고 보고 낮은 경사 주차 마커를 골랐다.
- 이후: 실물 8° 카메라는 벽 높이의 세로 태그도 잘 본다. 설계 문서는 주차 마커를 "재결정 필요"로
  돌리고, Gazebo 카메라·벽·바닥을 프로필로 실물에 맞춘 뒤 교차로·순회·주차 합격을 다시 받기로 했다.
  이전 25° 합격은 무효로 표시한다. (auto memory [claude]: 사용자가 2026-09-24에 실물 카메라가 거의
  수평임을 확인하고 시뮬을 실물에 맞추기로 결정)

## Related

- [호스트 pytest가 초록이어도 Gazebo 인식 경로는 실제로 돌려서 렌더된 값을 재야 한다](sim-perception-green-host-tests-hide-live-gazebo-defects-2026-09-22.md)
- [합성 픽스처에서만 검증한 가드는 실제 파이프라인의 가장 비싼 지점에서 깨진다](guards-validated-only-against-synthetic-fixtures-2026-09-23.md)
- 설계: `docs/plans/2026-09-24-perception-architecture-design.md`
