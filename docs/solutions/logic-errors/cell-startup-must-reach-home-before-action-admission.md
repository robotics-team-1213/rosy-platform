---
title: Cell 시뮬레이터는 홈 복귀를 관측한 뒤 Action을 받는다
date: 2026-10-04
category: logic-errors
module: deploy/robot/omx G2 harness + OMX Cell owner
modules: [deploy, docs]
problem_type: logic_error
component: development_workflow
severity: high
symptoms:
  - "Gazebo 컨트롤러가 준비됐지만 첫 Cell Action이 PHASE_RUNNER_START_UNKNOWN으로 보류됐다"
  - "영점 생성 자세에서는 HOME_DEVIATION, 홈 자세에서 닫힌 그리퍼는 GRIPPER_NOT_OPEN으로 계획이 거절됐다"
root_cause: missing_workflow_step
resolution_type: code_fix
tags: [gazebo, omx, cell, startup, home, admission, evidence]
applies_when:
  - "G2 시뮬레이터의 생성 자세와 승인된 Cell 홈 자세가 다를 때"
  - "컨트롤러 준비와 작업 시작 자세의 준비를 구별해야 할 때"
---

# Cell 시뮬레이터는 홈 복귀를 관측한 뒤 Action을 받는다

## Problem

G2 box16 검증은 컨트롤러와 Action 서버의 준비만 기다리고 Fleet 작업을 시작했다.
Gazebo가 만든 영점 자세와 닫힌 그리퍼는 Cell 계획기의 시작 전제를 만족하지 않았다.
r3 실행에는 `PHASE_RUNNER_START_UNKNOWN`과 ROS phase goal 부재가 남았다.
당시 내부 예외를 기록하지 않았으므로 r3의 정확한 예외가 `HOME_DEVIATION`이었다고 단정하지 않는다.
별도 ROS-free 계획 재현에서 영점 자세의 `HOME_DEVIATION`, 홈 자세·닫힌 그리퍼의
`GRIPPER_NOT_OPEN`, 홈 자세·열린 그리퍼의 정상 계획을 확인했다.

## Root cause

서버 준비는 관절의 시작 자세를 증명하지 않는다. 계획기는 승인된 홈 관절과 열린 그리퍼를
검사한다(`middleware/apps/device/omx/adapter/omx_adapter/pose_plan.py`의
`HOME_DEVIATION`, `GRIPPER_NOT_OPEN` 검사). 검증 fixture에 이 전제를 만드는 단계가 빠졌다.
계획기 검사를 완화하거나 별도 trajectory 발행자로 우회하면 단일 명령 소유권과
불확실한 실행의 보존까지 잃게 된다.

## Solution

`deploy/robot/omx/g2_owner.py`는 Cell 홈의 IK와 승인된 열린 그리퍼 목표를 계산하고,
같은 owner runtime의 `prepare_home()`이 성공한 뒤 UDS와 HTTP 서버를 연다.
`deploy/robot/omx/g2_startup.py`는 실제 durable Pilot admission을 사용한다.

```python
# g2_startup.py: register the sink before a goal can report acceptance.
admission.acquire(token, seat, ttl_s=bound + 30.)
admission.reserve_pilot(seat, command_id)
runtime.register_phase_event_sink(command_id, event_sink)
```

신선한 초기 joint state를 출발점으로 한 번만 제출한다. 승인 UUID와 같은 UUID의
`TERMINAL_RESULT`, status `4`, result code `0`을 확인한다. 그 뒤 목표 허용오차 안의
신선한 관절 샘플이 0.5초 동안 안정되고 sequence와 샘플 시각이 전진해야 준비 완료다.
같은 샘플의 재조회는 안정 구간을 깨지 않지만, 멈춘 샘플만으로 완료하지 않는다.

```python
# g2_startup.py: stable advancing readback precedes Action admission.
if (new_sample and sample.received_at > stable_sample_stamp
        and wall_clock() - stable_since >= .5):
    admission.release(token, seat)
    admission.run_action_admission(lambda: None)
```

불확실한 제출·종료나 readiness timeout이면 admission을 닫힌 상태로 남긴다.
SQLite의 pending intent를 지우거나 자동 재제출해 통과시키지 않는다.

## Verified outcome and limits

- r4 모델 PC Gazebo: `startup-home.json`의 `READY`, wall 9.264474초,
  일치하는 승인·종료 ROS goal UUID, status 4/result 0,
  `seat_reconciled: true`를 확인했다. 이후 첫 approach와 grasp ROS goal도 성공했다.
- r5 모델 PC Gazebo: 초기 홈이 다시 `READY`(wall 9.247641초), status 4/result 0,
  `seat_reconciled: true`였다. 첫 박스의 placement receipt가 남았다.
- r5는 두 번째 박스 이송의 `item_lost_in_transit`으로 `LOCAL_ACTION_HOLD`에 종료됐다.
  `cleanup_verified: true`, `fault_matrix: NOT_RUN`, `full_g2: false`다.
  홈 복귀 해결은 box16 완료나 장치·현장 수용을 뜻하지 않는다.

원본 증거는 저장소 파일이 아닌 모델 PC의 validation 작업 루트 아래 각각
g2-box16-230ccfc2a-r4/evidence/run/startup-home.json,
g2-box16-41d9b51e0-r5/evidence/run/startup-home.json, owner.log, result.json에 있다.
장비 주소·계정·임시 자격정보는 공개 문서에 넣지 않는다.
호스트 회귀는 `test/test_cell_g2_startup.py`와
`test/test_platform_cell_owner_assembly.py`가 담당하며, 실제 ROS 실행의 증거를 대체하지 않는다.

## Prevention

새 시뮬 fixture는 서버 준비, 시작 자세 준비, 실행 admission을 각각 확인한다.
첫 Action 전에 단일 owner 경로의 홈 복귀와 전진하는 실제 joint readback을 증명하고,
준비 실패 원문을 저장해 다음 조사에서 예외를 추정하지 않게 한다.
