---
title: 보이는 곡선과 주행 목표점 미채택을 구분한다
date: 2026-10-12
module: isaac_sim
problem_type: workflow_issue
applies_when:
  - "곡선 주행 실패를 카메라가 방향을 잃었다고 설명할 때"
  - "차선이 보이는 영상과 camera_target_unavailable 로그가 함께 있을 때"
tags: [isaac, camera, segmentation, lane-follow, diagnosis, map-parity]
---

# 보이는 곡선과 주행 목표점 미채택을 구분한다

## 교훈

곡선이 영상에 보이는데도 로봇이 멈췄다면 곡률이나 카메라의 일반적인 한계로 설명하지 않는다. 원본 영상의 차선 존재, 세그멘테이션 결과, 지면 투영, 이번 프레임의 목표점 선택, CORE의 출력 허용을 각각 확인한다. `camera_target_unavailable`은 코드가 현재 관측에서 사용할 목표점을 채택하지 못했다는 기록이며, 영상에서 선이 사라졌다는 증거가 아니다.

## 확인한 사례

소스 `54cba0b3fe`의 R31 baseline 707, simulation 6.600000344s/frame 1850에서 실패 PNG에 흰 바닥 선이 보였다. 동일 trace에는 `target_m=[0.19,0.137]`, `target_now_m=null`, `ahead_m=0`, `strategy=none`, `inference_error=null`이 기록됐다. CORE line 상태는 `HOLD`, 사유는 `camera_invalid_observation`, 최종 후보는 `[0,0]`이었다. 유효 목표점의 현재성 검사를 통과하지 못했음을 확인했으며, segmentation 자체의 실패 여부는 이 trace만으로 확정하지 않는다. `model_used=false`도 별도 inference 오류 없이 관측 무효화 과정에서 기록될 수 있으므로 모델 미실행으로 단정하지 않는다.

사용자가 제공한 실제 맵 사진의 곡선과 실패 전방 프레임의 선 형상을 별도로 비교해야 한다. 동일 STL 계보와 공유 맵 생성기를 썼다는 사실만으로 실제 사진·Gazebo·Isaac의 곡선, 차선 폭, 카메라 시점이 일치한다고 선언하지 않는다. 전방 프레임에서 각진 선이 보인다는 관찰만으로 맵 전체 형상 불일치도 확정하지 않는다.

## 다음 검증 기준

1. 실패 프레임의 RGB, 원래 class mask, 투영 결과, 목표점과 거절 사유를 같은 timestamp로 보존한다. mask가 없으면 인식 실패 원인은 미확인으로 남긴다.
2. 실제 맵 사진과 공통 생성 자산, native 카메라·Gazebo의 같은 위치/방향 프레임을 대조한다.
3. 목표점 미채택의 원인을 재현한 뒤 해당 로직을 고친다. 회귀 시험과 실제 곡선 주행 영상으로 확인한다.
4. 보이지 않거나 오래된 목표점을 채택하거나 CORE/Fleet 정지 조건을 완화해 완주시키지 않는다.

주행 오류는 아직 해결되지 않았다. 연속 정지 검사 실패는 별도 문제로 기록하며 이 교훈과 원인을 혼동하지 않는다. 상세 원본은 승인된 로컬 `private/isaac/media/2026-10-12-r31-floor-camera-diagnostic/`와 일지에 보관한다.
