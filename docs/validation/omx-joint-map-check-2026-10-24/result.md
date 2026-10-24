# OMX 관절 ↔ 모터 대응 판정 (D-864 §2)

**날짜:** 2026-10-24 · **대상:** 관제 PC의 S 셀 팔로워. LeRobot 보정 `omx_follower_arm`(2026-10-24 21:29)을 쓰는 팔이다.
**판정:** 통과. 모터 11~16의 레지스터 상태가 "ROS 관절 rad = `dynamixel_rad_v1`" 가설과 맞는다. 이 판정은 이 팔과 이 보정에만 쓴다.

## 절차

1. 진행 중이던 교사 시연 녹화(`chunk_runner.py`)가 포트를 놓기를 기다렸다. 포트가 30초 이상 비어 있는 것을 확인한 뒤에만 읽었다.
2. ROS 드라이버나 LeRobot은 띄우지 않았다. 읽기 전용 도구 `deploy/robot/omx/register_probe.py`(ID 11~16에 PING과 READ만 허용)로 3초 간격을 두고 두 번 읽었다. 두 번 모두 exit 0이었다.
3. `deploy/robot/omx/joint_map_check.py`로 판정했다. 처음 판정(schema 2)은 보정과 묶이지 않아 버렸다. 같은 두 측정 파일과 이 팔의 보정 `omx_follower_arm.json`으로 다시 판정했다(schema 3). 결과는 `holds: true`, exit 0이다.

장치 시리얼, 경로, 주소는 공개 기록에 남기지 않는다.

## 판정의 범위

- 판정의 `arm`은 `omx-cell-s-follower`다. 이 팔의 native 데이터셋을 검수할 때 `--rig-revision`으로 같은 값을 쓴다. 변환은 데이터셋의 rig revision이 이 값과 같을 때만 열린다.
- 판정은 보정 range digest(sha256 `41b49d250f4f35cbdc8ddc3695fdd9318a2c1b132cd2199cd9d708ca39f9770a`)도 기록한다. 다만 이 PC의 팔로워 보정은 S 셀, arm_a, arm_b 모두 range가 0~4095로 같아서, 이 digest만으로는 팔을 구분하지 못한다. 팔 구분은 rig revision이 맡는다.

## 결과

| 모터 | 관절 | 모델 | position_raw | ROS rad (계산) | homing offset | drive mode | operating mode |
|---|---|---|---|---|---|---|---|
| 11 | joint1 | 1060 | 2064 | 0.0245 | 0 | 0 | 4 |
| 12 | joint2 | 1060 | 767 | −1.9650 | 0 | 0 | 4 |
| 13 | joint3 | 1060 | 3130 | 1.6598 | 0 | 0 | 4 |
| 14 | joint4 | 1200 | 3112 | 1.6322 | 0 | 0 | 4 |
| 15 | joint5 | 1200 | 2972 | 1.4174 | 0 | 0 | 4 |
| 16 | gripper_joint_1 | 1200 | 2018 | −0.0460 | 0 | 0 | 5 |

- 여섯 모터 모두 토크가 꺼져 있었고(`torque_enabled: 0`), 두 측정 사이에 레지스터와 위치가 바뀌지 않았다.
- 같은 PC의 LeRobot 보정 파일 `omx_follower_arm.json`, `arm_a_follower.json`, `arm_b_follower.json`도 모두 homing offset 0, drive mode 0이다.
- 예전 `pinky_follower.json`(2026-10-12)은 wrist_roll(15)의 homing offset이 957이다. 그 보정으로 녹화한 데이터에는 이 판정을 쓰지 않는다.

## 근거 파일

- `evidence/probe-1.json`: sha256 `fcfe7bdec50283d2ac54ac71934ad50e7614e70af686d9255096b65dff98f9a8`
- `evidence/probe-2.json`: sha256 `5a8e7de0a2ce8b750dfb8ea322a455746f6b19bb060ab73d9030584301328cf6`
- `evidence/verdict.json`: schema 3 판정. arm, 보정 range digest, 두 측정 파일의 이름과 sha256을 담는다.

## 증명하지 않는 것

- 실물 기계 원점이 URDF(시뮬레이터) 원점과 맞는지는 이 판정으로 알 수 없다. 단위 변환이 아니라 시뮬레이터와 실물 사이의 보정 문제이며, 별도로 다룬다.
- 다른 팔(arm_a, arm_b)과 다른 보정의 레지스터는 읽지 않았다.
- 팔을 움직이는 동작, 정책 실행, 현장 수용은 이 기록의 범위가 아니다.
