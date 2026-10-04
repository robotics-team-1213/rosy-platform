# 새 Gazebo 시연 수집과 ACT 고정 평가

2026-10-04 KST. 이전 ACT 연구의 목표 다양성 부족을 실제 새 시연으로 보완했다.
정책의 SIM 실행·장치 활성화·전체 학습 파이프라인 완료를 증명하는 기록은 아니다.

## 새 SIM 실행

source `c3bd295fd6435f9ed64472a40e81f7a511843d6a`를 read-only로 mount한
별도 `rosy-learning-diverse-20261004` 컨테이너를 사용했다. image는 기존
`faeb86d666c6848ec61478a72087f7cadfc55d6b23e54dff891202b21029efb2`,
ROS 2 Jazzy/Gazebo Harmonic, localhost HTTP와 ROS discovery, domain 76,
privileged false/devices=[]다. 기존 다른 컨테이너는 변경하지 않았다.
source tree SHA는 `669960441ec6e4d254230b822d5d8cf21999c71a068af7b27e43cea84b690c32`,
world SHA는 `3cf7a3df5e7ddc609ee6536cac62af3ae992bdd047f294f4cb59be1829b85bc3`다.
이전 저장 시연의 world/limits와 달라 새 데이터만 함께 묶었다.

Pilot HTTP의 기존 조종권 갱신·fresh state sequence·goal 접수·ROS 결과·stop
경로를 사용했다. 관절당 ±0.02rad, duration 0.4s다. 새 액추에이터 API나
owner override를 만들지 않았다. 기록은 Linux volume에 쓰고 X로 보존했다.

| 순서 | joint / delta rad | Episode | 프레임 | split |
|---|---|---|---:|---|
| 0 | joint1 / +0.02 | e322c41d-8b71-4594-88a0-00ac4ef3dd46 | 13 | train |
| 1 | joint2 / +0.02 | e1619606-e672-4c12-a1ab-5ad3fd1bd3b4 | 12 | train |
| 2 | joint1 / -0.02 | e1ed0cae-b70b-4f6a-9429-e4c361f00c66 | 13 | train |
| 3 | joint3 / +0.02 | 50799d95-8803-4431-8b7e-53b9afaa7cfe | 13 | train |
| 4 | joint2 / -0.02 | fb5829b9-fe1c-41ba-b4fb-5b885214b563 | 12 | fixed eval |
| 5 | joint4 / +0.02 | 438e7b7c-bcc0-4cc3-8a73-f7c3c8947feb | 12 | train |

6 Episode/75프레임 모두 complete/issues=[]이며 ROS goal SUCCEEDED다.
목표와 후속 joint readback의 절대 오차는 최대 0.000034874rad로 호스트
single-joint 검사 한도 0.001rad 이하였다. 이것은 단일 관절 도달 검사이며
집기 성공·환경 ground truth·학습 정책의 독립 과제 판정은 아니다.
원본 task_outcome은 recorder의 operator 필드로 유지했다.

## 미완료 기록과 진단

첫 4CPU/4GiB 실행의 `584145c8-9401-411a-90bf-25d2ffe9b682`는 1프레임 뒤
frame_gap으로 미완료였다. raw Image/CameraInfo를 별도 ROS observer로
확인한 구간에는 0.1 simulation-second 간격의 연속 stamp/pair가 있었고,
wall 수신률은 약 4.7~5.9Hz였다. 해당 구간의 원본 카메라 시계는 정상이나
녹화기 전체 경로가 정상이라는 증거는 아니다. 정확한 누락 위치는 미확정이다.

해당 실패가 terminal인 것을 확인하고 자기 컨테이너만 8CPU로 재시작했다.
첫 접속은 서버 준비 전 connection 종료로 실패했고, 새 pairing/server 준비를
확인한 뒤 실행해 위 6개를 얻었다. 이후 joint3 음수 시연
`d04053d5-b307-4dec-b6c8-6eeb418bbe8b`는 5프레임 뒤 state_camera_skew와
frame_gap으로 미완료였다. 두 미완료 원본을 보존하고 학습에서 제외했다.
CPU 확대가 근본 수정이라고 결론 내리지 않는다. fps/skew 기준과 입력 bytes를
변경하거나 프레임을 보간하지 않았다. 종료 후 컨테이너는 exited/143이며
이는 명시 stop 결과다. volume과 원본 증거는 남아 있다.

## 실제 export·학습·평가

6개 LeRobot 0.4.4 v3 export 각각의 실제 reader로 모든 frame을 재독출했다.
state/action/clock/duration과 영상 shape 검사를 통과한 verified 보고서가 있다.
H264 RGB 평균 절대 오차 최대 1.75258/255로 기존 한도 8 이하다.
export 로그의 PowerShell NativeCommandError 형식과 codec/deprecation 경고는
별도로 보존했다. export handle의 exit 표시 1을 성공 종료 증거로 사용하지 않는다.
후속 ACT 실행에서 export reader와 provenance를 다시 읽었다.

train 63/eval 12프레임, seed 42751, steps 40이다. ACT 구성은
[이전 CPU 연구](omx-act-offline-2026-10-04.md)와 같고 정규화는 train에서만
계산했다. export 전체 snapshot, 공통 Episode·DatasetManifest, weights,
PolicyArtifact·평가 보고서를 생성했다. 실제 native 실행 exit 0이며 저장·재로딩
select_action 추론 일치 검사를 통과했다.

| 고정 eval | 결과 |
|---|---:|
| ACT MAE | 0.0296394574 rad |
| train 상수 평균 목표 기준 MAE | 0.0059898481 rad |
| train 목표 cluster(0.001rad) | 5 |
| joint limit 위반 | 0 |
| offline verdict | reject |

목표 다양성 조건은 충족했지만 상수 기준보다 나빠 승격을 거절했다.
independent_task_success는 unverified다. 연구 artifact만 생성했으며 L0,
PromotionRecord, policy dispatch, ACT의 fresh SIM 실행은 없다.

## 산출물과 잔여 gate

- 원본·export·readback: `X:/DevTemp/rosy-learning-audit-20261004/omx-diverse-sim/`
- ACT run: `X:/DevTemp/rosy-learning-audit-20261004/omx-act-seed42751-diverse/`
- DatasetManifest revision: `8dda786b742bebbd5eae5453f2db60534a22984c5e1943a99de92bb7f0b608bf`
- PolicyArtifact revision: `ede80a29f56e210bf814a4e888d931ed1462c2dc42eb374dfb0c611b0aa6dca9`
- offline report SHA: `9e376a60a320ce5425423017debb805312e98eaff1842525ca0c65e0bf7ebe09`
- 수집 scenario SHA: `9e5cc5bfa203a9e25ab03a8e922b9154cea98eb211fc9894c1d687327b546b6a`
- 원본·실행 스크립트·실패/진단/성공 로그·export·ACT 전체 zip SHA:
  `4cacbad620a5e448c83ce3217d9044d4cafbcbd10939e6405d92d2a7a87ae16d`
  (`X:/DevTemp/rosy-learning-audit-20261004/omx-diverse-sim-evidence.zip`, 44,856,233 bytes).

더 다양한 초기 상태/과제·실패 시연, 녹화 경로 누락 진단, 정책의 독립 SIM task
평가와 owner lease/generation/stale/HOLD 집행, 승격 원장/rollback,
Pinky 주행 정책/Fleet 결과 연결은 남아 있다. 모델 PC step-up은 새 인증 요청으로
대기 중이며 같은 SSH handle을 유지했다. 전체 목표는 active다.
