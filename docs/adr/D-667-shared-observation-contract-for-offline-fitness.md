# D-667: 오프라인 인지 평가의 공통 관측 계약

- Status: Accepted
- Date: 2026-10-12
- Related: D-427, D-665, D-666

## Context

D-665의 순수 관측 형식과 유효성 검사를 학습 평가가 World 구현에서 가져오면 D-427의 learning → operations 금지 경계를 넘는다. 동일한 검사를 복제하면 온라인 관측과 오프라인 평가가 다른 규칙을 사용할 수 있다.

## Decision

`ObservationSnapshot`, `SnapshotValidity`, `road_region_input_errors`의 구현을 ROS-free 공통 계약 `core_common.observation`에 둔다. 기존 `rosy.world.api`와 World projection import는 같은 객체를 재노출한다. 필드와 검증 동작은 유지한다. World는 관측 생산·상태 관리·실물 보정 책임을 계속 가진다. 학습은 공통 계약만 참조한다.

World wheel은 `core_common` 의존성을 선언하고 설치 시험은 두 wheel을 함께 설치한다. 서명된 모델 PC 코드 묶음은 새 재생기가 있는 경우 공통 관측 계약 파일을 반드시 포함한다. 이전 재생기 없는 버전은 유지한다. 모델 PC의 기존 해석기/패키지를 바꾸거나 장치에 배포하는 결정은 아니다.

새 관측 계약을 가진 `core_common`은 0.0.1, World는 0.1.1이며 World의 최소 계약 의존성은 0.0.1이다. 이전 0.0.0 설치본으로 의존성을 만족시키지 않는다. 기존 exact pin의 충돌을 막도록 Execution·Fleet·Palletizing·Cell·gateway/agent 조합의 패치 버전과 내부 pin을 함께 갱신한다. 이 변경은 패키지 메타데이터이며 해당 운영 동작의 추가 변경은 없다.

유효성 검사는 시각·참조·좌표계 결속을 확인한다. 실제 보정 정확도, 독립 정답, 성능 임계값, 주행 승인 증거를 제공하지 않는다. D-666 결과는 HOLD다.

## Verification

World와 계약 import의 객체 동일성, 독립 wheel 설치, learning import 경계, 서명 묶음의 누락 거절·설치 import, 기존 인지 회귀를 확인한다. 실물·시뮬레이션 성능과 장치 수용은 별도다.

새 동작 시험은 D-184에 따라 구현 소유자의 `test/`에 둔다. 인지 기준선은 perception, 평가·고정 재생은 learning evaluation이 소유한다. 기존 공유 시험 corpus는 유지하며 harness가 새 평가 시험도 선택한다. 외부 동작 시험 예외 목록은 늘리지 않는다.
