---
title: SDK 6.2 모델 import 성공 뒤 관절이 움직이지 않음
date: 2026-10-27
category: runtime-errors
module: learning/envs/isaac
problem_type: runtime_error
component: simulation
symptoms:
  - Imported USD has no articulation until its Physics variant is selected
  - ROS clock, joint states and cameras publish but cancel-test travel is zero
root_cause: modern_converter_leaves_missing_joint_drive_gains_at_zero
resolution_type: code_fix
severity: high
tags: [isaac, sdk62, urdf, usd, position-drive, conformance]
applies_when: Migrating a manipulator URDF from the legacy importer to SDK 6.2
---

# SDK 6.2 모델 import 성공 뒤 관절이 움직이지 않음

2026-10-27, Isaac/OMX 소유. SDK 5.1에서 6.2로 이관할 때 적용한다.

## 증상과 원인

URDF 변환이 성공해도 SDK 6.2의 초기 USD는 Physics variant가 선택되지 않아 articulation을 찾지 못했다. live reference에서 physx를 선택한 뒤에는 모델·관절·120프레임 검사를 통과했지만, ROS conformance에서 clock·joint·카메라 메시지를 수신하면서도 취소 전 관절 이동량이 0이었다.

실제 USD에는 DriveAPI와 maxForce가 있으나 stiffness/damping이 없었고 converter는 해당 URDF 값이 없다고 경고했다. 현대 importer의 기본 None은 값을 생성하지 않는다. 따라서 articulation 존재·position 명령 수신·카메라 수신만으로 실제 관절 제어 성공을 판정할 수 없었다.

## 해결과 검증

`importer_compat.reference_model`에서 live reference의 physx variant를 선택하고, 현대 Manipulator 변환에 position target과 명시적 gain을 넣는다. stiffness 40, damping `2√40×0.5+0.3`은 기존 MuJoCo의 actuator 속도 감쇠와 passive damping을 기준으로 삼았다. passive 0.3만 복사하면 actuator 항 약 6.3246을 빠뜨린다. 실물 팔 보정값·엔진 간 물리 동등성은 별도다.

정확한 버전별 importer·variant·drive 회귀와 전체 Isaac 호스트 시험이 통과했다. commit `6df916084147ce51bb10b34e8339e302a88fdfe6`, 모델 PC `isaac62-ros-final-304dbb`는 취소 전 약 0.0297rad, 취소 후 0rad, 양쪽 카메라 56프레임, clock/joint 각각 678개, drift 0mm, failures 빈 목록과 GPU 정리를 확인했다. [수치와 전환 기록](../../validation/isaac62-sdk-migration-2026-10-27/result.md)을 따른다.

## 복구와 다음 적용

기존 SDK·source binding은 보존한다. 전환 장애 시 해당 SDK 작업의 종료와 소유 lease를 확인하고 백업 pointer의 SHA를 대조해 복구한다. variant가 없던 구형 모델에는 새 variant를 임의 생성하지 않는다. Wheeled velocity 설정을 Manipulator position 설정으로 덮어쓰지 않는다.

새 importer나 모델을 적용할 때마다 모델/관절 import 검사와 실제 명령 추종·취소 정지·카메라 주기 검사를 함께 수행한다. 통과 임계값을 낮추거나 정적 관절 상태를 성공으로 처리하지 않는다. 다른 초기 UNKNOWN/조기 실패의 미확정 원인은 이 교훈으로 해결됐다고 표시하지 않는다.
