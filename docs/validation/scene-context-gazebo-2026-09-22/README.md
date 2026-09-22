# Scene-Context Gazebo Rendered-Frame Verification (2026-09-22)

판정: **PASS** — D-162 장면 상황 매처가 **실제 Gazebo 렌더링 카메라 프레임**에서
정확히 분류하고, 표식이 사라지면 제네릭 보수 폴백으로 떨어짐을 확인했다.
합성 프레임 단계(`docs/validation/scene-context-control-node-2026-09-22`)의
다음 단계 증거다.

## 방법

- WSL2 Ubuntu 24.04, ROS 2 Jazzy, **Gazebo Sim 8.15.0**.
  트리: `git archive HEAD`(89c1d11 이후 통합 main) 스냅샷, 13패키지 빌드.
- `ros2 launch gz_sim semantic_road_dashboard.launch.py gazebo_gui:=false`
  (2026-09-21 semantic-road 실행과 동일 절차), 단 로드 옵저버만
  `scene_context_enabled: true`로 스냅샷 내에서 변경(커밋 설정은 false 유지).
- 스폰 (x=-0.20, y=-0.15, yaw=0)에서 카메라가 정지선을 보는 상태로 시작,
  `gz service /world/map_260905/set_pose`로 로봇(모델 `rosy`)을 x=
  0.10 → 0.45 → 0.80으로 순차 이전시키며 페이즈별 관측을 수집했다.
  로봇을 직접 주행시킨 것이 아니라 텔레포트로 시야를 바꿨다(주행+강제 정지는
  2026-09-21 실행이 이미 증명).

## 결과

| 페이즈 | 위치 | 카메라 검출 | context 분류 |
|---|---|---|---|
| phase0 | 스폰(정지선 0.167 m 전방) | stop_line conf 0.986 | **stop_line 20/20** |
| phase1 | x=0.10 | stop_line conf 0.925 | **stop_line 22/22** |
| phase2 | x=0.45(표식 통과) | stop_line None | **generic 18/18** |
| phase3 | x=0.80(차선 이탈) | stop None, lane None | **generic 18/18** |

- 단일 옵저버 확인: `/road/observation` Publisher count 1 (중복 인스턴스
  차단 단정 포함, `publisher-check.txt`).
- 모든 payload에 additive `context` 필드(id·confidence·profile_revision).
- 표식이 시야에서 사라지자 `exit_frames` 히스테리시스 후 제네릭으로
  복귀 — "매칭 실패 시 어디서든 안전한 기본 동작"의 실렌더링 증명.

## 한계

- 텔레포트 기반이므로 주행 중 동역학(진동·모션 블러)은 미반영. 주행+강제
  정지 폐루프는 2026-09-21 증거가 커버한다.
- crosswalk 페이즈는 이 코스 배치에서 카메라에 잡히지 않아 미검증 —
  crosswalk 컨텍스트 분류는 호스트 단위 시험만 존재한다.
- 프로파일 값은 v0 중립(제네릭과 동일). 본 실행은 분류·폴백 메커니즘의
  증명이다.
- 로봇을 움직이기 전 `/road/observation` publisher가 정확히 1인지 단정하는
  가드를 넣었다 — 이전 실행의 잔존 옵저버 오염을 실제로 마주했기 때문이다.
