# 도로 인지 출처별 불확실성 — 2026-10-12

## 범위와 결과

D-690의 내부 평가 진단을 D-666 고정 재생에 연결했다. 검증된 정답 manifest의 session/capture group을 보존하고 도로면·현재 구역을 출처 전체로 재표집한다. 기존 픽셀 합산 지표, abstention, 실물/시뮬레이션 분리와 HOLD를 유지한다. 외부 정답·보정이나 수용 임계값은 생성하지 않는다.

## 실행 증거

- `379ca4cc78`의 올바른 RED: 새 모듈 부재 및 호출자의 capture group 누락으로 원격 시험 exit 1, 12개 실패. 앞선 import holder 누락은 시험 구성 오류로 수정했으며 기능 RED로 해석하지 않는다.
- `43c8438588`의 GREEN: 모델 PC에서 source uncertainty, fixed replay, road fitness 세 시험 파일이 terminal exit 0. 83개 중 81개 통과, 2개 제외. 일반 원격 시험 환경에 ONNX 관련 패키지가 없는 기존 실제 모델 사례만 제외되었으며 새 출처 진단 시험은 모두 실행했다.
- `test/known_failures.py` 비교: `0 new, 0 known, 0 listed but not failing`, exit 0.
- 검증 사례: 크기가 다른 출처의 픽셀 가중 점수, 출처 전체 재표집, 입력 순서 불변, 단일/빈 출처, 미관측 정답과 anchor 보류의 분모, 잘못된 identity/session/group/domain와 중복 거절, 고정 재생의 manifest 결속.

원본 로그: `X:\DevTemp\projects\rosy-platform\2026-10-11--213319--perception-fitness-pipeline--024175\logs\source-uncertainty-red-fixed\run-1.txt` 및 `source-uncertainty-green\run-1.txt`. 브랜치는 `feat/perception-source-uncertainty`다. 최신 main 통합은 착지 도구의 별도 최종 gate로 확인한다.

## 증거의 한계

합성 시험과 파일 평가 진단이다. 두 출처는 계산 가능 조건이며 충분한 독립 표본 수를 보장하지 않는다. 좁은 구간도 일반화 성능·검수 독립성의 증명이 아니다. 독립 전체 도로면/현재 구역 정답, 물리 보정, 사전 고정 수용 profile, 장치 전달/지연/손실, 실물/시뮬레이션 성능 수용은 여전히 미완료다. push·CI·배포·주행 활성화를 수행하지 않았다.
