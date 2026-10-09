# B9 카메라 wash의 복구 명령 차단

2026-10-09, 격리 `route_a` SIM 후보. [앞선 원인 분석](../lane-route-wash-gate-2026-10-09/result.md)의 40% BEV 밝기 거부 프레임은 `visible=false`로만 전달되어 CORE가 일반 차선 상실로 해석했다. 그 실행에는 `RECOVERING/stuck_back_off` 23건이 있었다. 경로 잠금 상태의 전백색 프레임은 `RouteCameraFollower`가 새 `MANOEUVRE`를 시작할 수도 있었다.

이번 변경은 `LaneEdgeFollower`의 기존 40% 거부에 `washed` 원인을 붙이고, `RouteCameraFollower`가 그 프레임에서 경로 기동을 중지하게 한다. `route_a` 관측 노드는 이 경우 기존 CAMERA_LINE `quality={valid:false, reason:"overexposed"}` 계약으로 CORE에 전한다. 설정값, route, 최종 `/cmd_vel` 권한은 바꾸지 않았다. `overexposed`는 현재 CORE 품질 계약의 이름이며, 여기서는 BEV의 흰 화소 비율에 의한 거부도 포함한다.

## 검증

- SOURCE: 저장된 실제 Gazebo `camera-loss.png`와 전백색 프레임 테스트에서 관측은 `None`, 후보 상태는 `STOP`, 원인은 `washed`다. 노드 wiring 테스트에서 `overexposed` 품질 전송을 확인했다. 관련 호스트 pytest **147 passed**, `test/known_failures.py` **0 NEW**. `rosy_harness.py lint`: 오류 0, 기존 stale-version 경고 23.
- 격리 SIM: 모델 PC `~/rosy-ml/scratch/lane-route-gap-live-20261009/`, domain 139, 같은 B9 시작 자세 `(-1.26955,0.24255,-1.5708)`와 `left:60` 사전 지시, 40% gate로 별도 실행했다. 31 카메라 프레임 중 CAMERA_LINE 관측 28건은 visible 3 / invisible 25였다. invisible 25건 모두 `quality.reason=overexposed`. CORE 상태 표본은 `HOLD/camera_overexposed` 14, TRACKING 4, `LOST/reselection_required` 1, `RECOVERING` 0건. 이전 40% 실행의 `RECOVERING/stuck_back_off` 23건과는 별도 실행이므로 완전한 프레임 대응 비교는 아니다.
- 원시 수집: `X:\DevTemp\lane-route-gap-live-20261009\camera_washquality.json`, `camera_washquality.npz` 및 모델 PC의 같은 scratch 경로. 실행 뒤 SIM partition을 종료했다.

## 남은 범위와 결정

독립 안전 리뷰(`/root/wash_quality_review`, 읽기 전용)는 **유효 odom pose가 있는 route_a에서 감지된 wash** 범위만 조건부 승인했다. 리뷰는 기존 BEV gate, 경로 기동 전 STOP, 관측 노드의 품질 전달, CORE의 복구 차단, 관련 테스트와 `git diff --check`를 확인했다. 아래 예외와 실물 주행은 승인 범위에 넣지 않았다.

이 변경은 **유효한 odom pose로 BEV wash가 판정된 `route_a`**에 적용된다. wash와 odom 상실이 동시에 오면 tracker가 BEV 판정 전에 반환해 일반 차선 상실 경로가 남는다. `route_b`·`route_ab`는 별도 follower여서 대상 밖이다. D-520의 실행 중인 map-guided `lane_arc`는 의도적으로 카메라 없이 한정 거리 동안 odom·IR·장애물 가드로 진행하며, 이 변경은 그 계약을 바꾸지 않는다. 따라서 모든 카메라 품질 불량에서 전 동작 정지를 증명한 것은 아니다.

40% 밝기 거부에 따른 **거짓 STOP은 아직 남는다**. 75% 완화 실험은 IR 중앙선과 LiDAR 벽 근접 HOLD를 드러냈으므로 제품 gate로 채택하지 않았다. 경계 추종 주행의 합격, 10/6·10/7 사람 검수 GT, DEVICE/현장 수용은 모두 미완료다.
