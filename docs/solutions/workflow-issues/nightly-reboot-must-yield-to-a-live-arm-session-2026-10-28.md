---
title: The site nightly reboot restarted the Fleet PC in the middle of an arm move
date: 2026-10-28
category: workflow-issues
module: deploy/site/host-state (rosy-nightly-reboot timer and service)
problem_type: workflow_issue
component: deployment
symptoms:
  - "Fleet PC rebooted at 06:10 while an OMX arm session was moving"
  - "gripper camera preview shows 'No fresh frame' after the reboot"
root_cause: missing_validation
resolution_type: code_fix
severity: high
tags: [omx, nightly-reboot, session-lock, host-maintenance, arm-s]
applies_when: "a host maintenance timer (reboot, update, cleanup) can fire while a person or runner drives a real device"
---

# Host maintenance must yield to the cell session lock

## 문제

`rosy-nightly-reboot.timer`(06:08, 재부팅 06:10)가 2026-10-28 06:10에 팔 이동 중 Fleet PC를
재부팅했다. 서비스의 조건은 업데이트 동결뿐이었고, 장치 세션은 보지 않았다. 현장 벽 경고는
원격 운영자에게 닿지 않으므로 사람이 막을 방법이 없었다.

## 해결

`9e0a75971d`: 세션 잠금(OMX 세션 lock 파일)이 잡혀 있으면 그날 재부팅을 건너뛴다. 시험 통과.
**Fleet PC에는 아직 설치되지 않았다**(sudo 필요). 설치 전까지 같은 사고가 다시 난다. 설치 후
이 줄을 실물 확인 결과로 바꾼다.

## 복구

재부팅 뒤 그리퍼 카메라 미리보기가 `No fresh frame`이면
`systemctl --user restart rosy-omx-camera@front`로 복구했다(검증됨).

## 적용 조건

장치를 구동하는 세션이 있는 호스트의 모든 정기 작업(재부팅·업데이트·정리). 조건에 "동결"만
있고 "세션 중 아님"이 없으면 같은 구멍이다. 관련: 정리 타이머와 업데이트 경로 기록.
