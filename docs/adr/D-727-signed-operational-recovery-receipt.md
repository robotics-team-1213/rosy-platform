# D-727 설치·독립 근거·현재 epoch에 결속한 운영 복구 receipt

**Status:** Accepted (2026-10-12, shared source contract; no operating admission)

## Context

D-716은 offline reasoning_calibration을 물리 허가로 사용하지 않는다. 교체 가능한 모델과 동일 사건의 실제 복구를 연결하려면 Model PC의 최종 독립 검수와 Fleet 현재 설치·원장 상태를 함께 고정해야 한다. 자기 보고 확률과 모델 합의는 이 서명을 생산하지 않는다.

## Decision

ROS-free 공통 SDK에 `rosy.incident.operation/1` receipt를 정의한다. 별도 kind인 `reasoning_operational_acceptance`와 `reasoning_operational_revocation`, 전체 profile set SHA·실제 판정 full profile SHA·model revision·calibration SHA·domain·action contract·policy·installation SHA·독립 evaluation/coverage/limits/truth SHA를 닫힌 binding에 담는다. 첫 domain/action은 line_follow/BACK_AND_RETRY와 D-718 조건부 계약이다. 평가 상태는 독립 최종 검수 `REVIEWED_FOR_OPERATION`이며 HOLD와 offline pass는 거절한다.

현재 owner가 제공한 expected binding·epoch·시각과 맞는 서명만 검증한다. 최소 32-byte trusted key와 해당 kind의 권한을 가진 독립 principal이 canonical payload를 HMAC-SHA256으로 서명한다. payload 자체의 canonical revision도 다시 확인한다. 수용은 유효 기간 안에서만 가능하고 폐기는 만료 뒤에도 별도 서명으로 가능하다. 반환 기록은 복사본이며 action_admissible·명령·토큰·주소·속도·거리 필드는 없다.

이 SDK는 서명과 계약을 확인하며 증거의 실측 품질이나 owner admission을 생산하지 않는다. digest·검수 상태를 모델 자기 선언으로 채우지 않는다. 독립 평가 producer와 검수자가 원본 근거·한계·coverage를 검증하고, Fleet importer가 원본을 재검증해 현재 설치 binding과 동일 DB의 수용/폐기 epoch에 저장해야 한다. claim 직전 이 현재 상태를 다시 확인하는 단일 소비자와 실제 결과 검증은 D-716 후속이다. 운영 receipt 검증만으로 경로를 활성화하지 않는다.

공통 wheel은 0.1.11로 올리고 새 계약을 소비하는 Fleet floor·CI·고정 local execution 소비자를 함께 맞춘다. 기존 receipt와 model Problem digest는 바꾸지 않는다.

## Verification

수용·폐기 kind 분리, 실제 HMAC, 전 binding 차이·다른 signer/trust kind/key·다른 epoch·만료·NaN/bool·revision 변조·offline/HOLD 거절과 반환 복사본을 원격 검증한다. 실제 wheel/sdist와 소비자 pins를 확인한다. 이 source 검증은 실제 독립 평가·승격·설치·모델 호출·현장 수용의 증거가 아니다.

## 독립 검토로 확인한 소비 조건

`REVIEWED_FOR_OPERATION`은 서명된 검수 메타데이터다. 후속 producer/importer는 actual evaluation 원본이 HOLD이면 이 상태를 가진 서명이 있어도 거절한다. 원본 full profile·검수 limits/truth·coverage·report bytes와 digest를 검증하고 owner가 독립적으로 expected binding을 계산한다. receipt에서 복사한 binding을 기대값으로 사용하지 않는다. SDK 서명 성공은 품질 PASS·owner admission·물리 성공을 의미하지 않는다.
