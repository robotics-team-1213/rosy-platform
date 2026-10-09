# Fleet 계획과 차선 관측의 실물 읽기 전용 확인 (2026-10-09)

증거 단계: **DEVICE readback only**. 로봇 설정, 모드, 명령을 변경하지 않았고 주행 시험도 하지 않았다. 주소와 계정은 공개 기록에 넣지 않는다.

## 현재 설치 상태

두 Pinky의 `/opt/rosy/current`는 `2026.10.09-056`, `source-revision.txt`는 `f588e0ad879fab3f3b726802f4c99b78eed32f87`이었다. 두 로봇 모두 `rosy-core`, `rosy-io`, `rosy-camera`가 active였다. 이는 서비스 상태일 뿐 차선 추종 성공이나 Fleet trip 수용 증거가 아니다.

| 로봇 | `camera_lane_mode` | `camera_ground_source` | `paint_source` | 관측 범위 |
|---|---|---|---|---|
| `rosy_26` | `keep` | `NOMINAL` | `learned` | ROS 파라미터 읽기 |
| `rosy_60` | `line` | `PINKY` | `threshold` | ROS 파라미터 읽기 |

`rosy_26`의 `/var/lib/rosy/models/shadow`는 존재하지 않았다. 읽은 `line/keep_debug` 한 프레임은 `paint_source_used=denoise_fallback`, `paint_model_revision=null`, `camera_geometry_source=NOMINAL`, `strategy=corner_right`, `boundaries=[]`였다. `paint_points_v=1`과 점 48개는 있었지만, 이 한 프레임만으로 그 점들이 자기 차로의 경계라고 증명할 수 없다. `target_m=[0.306,-0.189]`, `lane_width_m=0.185`는 corner 후보의 목표이며, 사람 승인 정답이나 물리 주행 허가가 아니다. 직전 [실물 readback](../lane-live-ground-readback-2026-10-09/result.md)의 84프레임 모두 `denoise_fallback`이었던 결과와 같은 방향이지만, 이번 표본은 한 프레임이다.

## 주행 로직 판단

Fleet의 계획은 계속 활용한다. 이미 [D-520](../../adr/D-520-map-guided-ring-arc-following.md)은 선택한 `exit_segment`의 곡률·길이를 CORE의 원형 구간 주행 목표로 쓰고, 카메라 도색 점으로 그 호를 보정하는 단계 2를 정했다. [D-476](../../adr/D-476-lane-loss-expected-road-bridge.md)은 확신했던 차로가 잠깐 사라진 경우 최근 차로의 연장선과 Fleet 방향 힌트로 제한된 거리를 잇는 경로다. 둘 다 CORE의 장애물·바닥·몸 쓸기 판정과 단일 최종 `cmd_vel`을 통과해야 한다.

운용 후보는 관측 두 선 → 한 선과 직전 차로 폭·odom → 짧은 가림의 직전 중심선·Fleet 다음 간선 → 계획된 굽이·원형 구간의 지도 호 순서다. 단계가 바뀔 때 `map_id`, pose/odom 신선도, 카메라 투영, 예상 접선과 보이는 선의 잔차를 확인하고, 오차가 커지거나 독립 경계 근거가 없으면 감속 또는 HOLD한다. 한쪽 선에서 추정한 다른 선과 가림 중 워프한 선은 **예측**으로 남겨 두고 실측 경계로 승격하지 않는다. 차선 넘기기는 선택된 경로의 승인된 교차로/분기에서만 다룬다.

Fleet 지도 보정은 주행 중 지도 자체를 즉시 다시 쓰는 일이 아니다. 독립 자세 기준(Rosy Cam 또는 LiDAR 벽 정합)과 카메라 경계의 반복 잔차로 카메라 투영·odom 곡률·지도 위치 중 어느 오차인지 분리한 뒤, 로봇별 보정 후보를 재생/SIM에서 검증해야 한다. 특히 `NOMINAL`을 곧 승인된 실물 캘리브레이션으로 해석하지 않는다. [D-531](../../adr/D-531-route-context-to-lane-keeper.md)의 keeper 경로 문맥은 Proposed이고 veto 전용이다. 그것이 Fleet 계획의 유일한 사용처는 아니다. 지도 호의 적극적 주행은 D-520이 담당한다.

## 다음 검증

1. D-520 단계 2의 카메라 호 보정 SIM에서 반경 오차 한계와 오인된 spoke 거르기를 통과한다. 기존 lap SIM 4의 `|r|` 최대 0.056 m는 0.05 m 문턱을 넘었다.
2. `rosy_26`에서 모델 포인터·실사용 모델 revision과 카메라 보정 출처를 분리해 확보한다. 지금 `learned` 설정을 학습 모델 주행 증거로 세지 않는다.
3. 10/6·10/7 원본의 동일 물리 경계·가림·재출현은 후보 분석으로 유지한다. 사람 검수 전에는 승인 GT나 차선 침범 허가로 쓰지 않는다.
4. 실물 주행 수용은 승인된 지도·보정과 독립 자세 기준, IR/LiDAR 게이트를 갖춘 별도 시험으로 판단한다. 이 읽기 전용 확인은 그 단계를 대체하지 않는다.
