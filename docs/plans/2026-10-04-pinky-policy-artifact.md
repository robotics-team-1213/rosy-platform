# Pinky research PolicyArtifact implementation plan

**Goal:** 실제 비교 모델을 공통 정책 산출물과 영속 평가 거절 원장으로 연결한다.
**Architecture:** 계약은 미확인 카메라 보정 null을 보존하고 known CameraProfile과의
모순을 거부한다. 호스트 exporter가 원본 모델·예측·dataset closure와 단위별 오차를
재검산해 PolicyArtifact를 만든다. registry는 bound 보고서의 조건을 재판정한다.
**Tech Stack:** stdlib 계약/registry, numpy/OpenCV/PyTorch 호스트 연구 도구.

## 결정

가짜 보정 해시나 cameras=[]로 영상 정책을 숨기지 않는다. 명시된 front topic과
source/model RGB 크기, null camera_profile/calibration을 보존하는 연구 산출물이다.
CameraProfile을 알려진 revision으로 선언하면 각 calibration SHA도 반드시 알려져야 한다.
null은 물리 shadow 승격을 통과하지 못한다. 기존 알려진 카메라의 valid 산출물은 유지한다.
owner는 Pinky CORE Command Manager, controller/envelope는 unregistered 연구 값이다.
기록된 CORE 속도와 실제 정책의 base_velocity_candidate 의미를 구분한다.

## 작업

1. unknown calibration 허용/known-profile 모순 거절의 계약 RED 시험 후 구현(0.1.5).
2. `learning/training/pinky/artifact_export.py`의 source file manifest/실제 예측 오차/
   원본 split·정규화·dataset binding·학습 모델 선택 검증을 시험 후 구현한다.
3. profile YAML 해시와 명목 limits를 보존하되 현장 safety approval로 해석하지 않는다.
   별도 새 X 출력으로 CNN/ridge artifact를 생성하고 실제 file/hash를 검증한다.
4. `registry.py` Pinky 평가 재계산/거절 원장/CLI와 승격 override 거절을 RED→GREEN으로 구현한다.
5. 실제 두 정책 register/assess/restart readback, wheel dependency 없음과 영향 시험,
   독립 리뷰·소스/호스트 증거를 남긴다. owner/Fleet/물리 활성화는 아직 미완료다.
