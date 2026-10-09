# 경계가 보이는데도 STOP한 프레임과 밝기 게이트 반례

**판정: 원인 한 가지를 재현했지만 차선 추종 주행은 HOLD.** 2026-10-09 KST, 격리 Gazebo `route_a`에서 B9와 같은 시작 자세 `(-1.26955, 0.24255, -1.5708)` 및 `left:60` 사전 지시를 사용했다. 10/6·10/7 실영상의 사람 승인 경계 정답은 아직 0건이다. 이 문서의 픽셀과 위치는 모두 SIM이며 운영 로봇의 인수 증거가 아니다.

## 원인 분리

| 비교 | 기본 `washed_fraction: 0.40` | SIM 전용 `0.75` |
|---|---:|---:|
| 같은 57개 저장 프레임의 25.125초 | BEV 페인트 39.8%, `BOTH` | `BOTH` |
| 같은 프레임의 25.250초 | 페인트 40.6%, `STOP` | `BOTH` |
| 별도 폐루프의 카메라 가시 프레임 | 20/55 | 477/477 |
| 별도 폐루프 결과 | 약 8초에 `LOST/camera_reselection_required`; 교차부 0 | 0.304m 뒤 `HOLD/lane_departure`; 교차부 0 |

두 저장 프레임은 [직전](evidence/camera-pre.png)과 [손실 순간](evidence/camera-loss.png)의 실제 Gazebo 카메라 출력이다. 두 장 모두 페인트 경계가 육안으로 보인다. 같은 영상과 GT를 현재 `RouteCameraFollower`에 다시 넣었을 때, `lane_bev.py`의 `paint.sum() > washed_fraction * observable` 조건이 40%에서만 전체 관측을 버렸다. 두 설정의 출력 차이는 그 프레임에서 재현됐다. 이것은 **첫 거짓 STOP의 직접 원인**이지, 경계 위치·중심선·장애물 판단이 정확하다는 증거가 아니다.

기본 설정의 폐루프에서는 최초 비가시 후보가 GT `(-1.2708, 0.1828, -1.6117)`에서 나왔다. 이후 CORE는 `HOLD/camera_line_not_visible` 27회, `RECOVERING/stuck_back_off` 23회, 최종 `LOST/camera_reselection_required`를 기록했다. `left` 지시에는 직진 차로 연장만으로 교차부를 건너는 D-476 bridge가 성립하지 않는다. 멈춤 래치는 안전 계약대로 유지됐다.

75% 실험에서는 비가시 판정이 사라졌으나 GT `(-1.2839, -0.0004, -1.6481)`에서 먼저 `HOLD/obstacle_ahead`(body gap 0), GT `(-1.2881, -0.0608, -1.6277)`에서 `HOLD/lane_departure`가 나왔다. 마지막 위치에서 계속 멈췄다. 따라서 **75%를 제품 설정으로 올리면 안전하게 주행한다는 가설은 반증**됐다. 장애물 HOLD는 LiDAR/몸 쓸림 근거이므로 이 실험을 이유로 해제하지 않는다. 기존 출하 keep, CORE 최종 `/cmd_vel` 권한, 제품 설정은 바꾸지 않았다.

## 재현 범위와 원본

- 모델 PC 격리 경로: `~/rosy-ml/scratch/lane-route-gap-live-20261009/`; ROS domain 139, Gazebo partition `rosy_lane_route_gap139`, API 8139. 실행 후 해당 partition 프로세스 종료를 확인했다.
- B9 소스 archive SHA-256 `1934f941668a9a5e273e0bfb592c796837ebff124d92fed906807a374fe50d0b`, 월드 SHA-256 `14c8de02f683435a103728a30a24a83237ff9bc03ba1dc6f87a08feb99f31ebb`. 당시 로컬 `main`의 `route_camera.py`만 교체했으며 파일 SHA-256은 `272f8e146550da2c1067d473705964c74ec1c001b1d7f998d25e5e6407befcbc`다. 현재 전체 `main` 빌드의 증거가 아니다.
- 기본/75% launch SHA-256 각각 `ad6dfd5ab52d80036abf0c556a20069578f0f9b3e4d1ce65fd3dcb27a91b01d3`, `596098e31ad235b14312a593c5ed19d30df33b5b3c4ae40cd303f8327b191fd7`. 75%는 이 격리 launch에서만 바꿨다.
- 57프레임 원본 `camera_loss.npz` SHA-256 `8705c0100ce1c29d69cec1192c509808ba0624a654baded66a83658bd7074616` (모델 PC 위 경로). 기본/75% 폐루프 `summary.json` SHA-256 각각 `14ed1fd46e9691ab176357296d88d36ccfa6a887863f8afb3d74e186cf311675`, `9449bbdc5cdcc1694fabf7abebf5880b2da75fdf05e6658058b7f4f11f00da84`. 폐루프는 동일 영상 재생이 아닌 **별도 실행**이므로 수치 차이를 단일 변수의 인과 효과로 과장하지 않는다.
- 이전 [경로 이탈 SIM](../lane-route-live-offmap-2026-10-09/result.md)은 시작 자세 `(-1.15,-0.511,0)`로 달랐고 장애물 HOLD에서 끝났다. B9 경계 공백과 동등한 주행으로 비교하지 않는다. 앞선 [9/22 Gazebo 검증](../map-v2-fleet-gazebo-2026-09-22/result.md)에도 75% 실험 후 코너 HOLD가 있었다.

## 가설 토론과 다음 판별 실험

1. **전면 밝기 게이트만 완화:** 거짓 STOP은 줄지만 교차로·횡단선처럼 밝은 비경계도 통과한다. 이번 폐루프가 주행 합격 가설을 반증했다. 출하 보류.
2. **관측을 공간적으로 나눠 판별:** 경계 두 줄의 길이·폭·연속성과 횡단 띠를 분리하고, 보이지 않는 쪽은 최근 물리 경계 ID와 odom 예측 범위 안에서만 `unknown`으로 유지한다. 이것이 다음 후보지만 10/6·10/7 사람 검수 없이 `BOTH` 정답으로 승격하지 않는다. 한쪽 경계만 잡는 기존 keeper를 이 57프레임에 적용하면 오차 부호가 바뀌므로 전면 교체도 보류한다.
3. **조향·몸 안전을 독립 계측:** 같은 시작 포즈에서 카메라 경계와 GT 차로 중심의 가로 오차·헤딩, body gap 원인 각도를 프레임별로 맞춘다. `visible` 개수 대신 연속 miss, 차로 이탈, 장애물 HOLD, 교차부 재획득을 함께 비교한다. 이 측정이 없으면 75% 주행의 오차가 세그멘테이션·BEV 보정·경로 투영·LiDAR 중 어디서 시작됐는지 결정할 수 없다.

다음 통과 조건은 사람 승인 10/6·10/7 경계 ID/가림/재출현 후보를 분리 보관하고, 동일 시작·동일 경로 반복 SIM에서 거짓 STOP을 줄이면서 차로 이탈·장애물 정지 회귀가 없다는 것이다. 그 뒤 DEVICE와 현장 수용을 별도로 거친다. 지금은 불확실하면 STOP이며 최종 구동 권한은 CORE 하나다.
