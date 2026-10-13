# perception_evaluation verification log

2026-10-11: D-637 folder move in progress; committed-SHA verification pending.

2026-10-11: source d4988bffba landed on local main after independent review, remote regressions/known_failures 0 NEW and installed wheel/sdist/HTTP proof. SOURCE/LOCAL GO only; CI FULL and ROS-SIM/ARM64/device/field remain unverified. See docs/validation/d637-remaining-folders-2026-10-11/result.md.

## 2026-10-11 · b64dc94e0a · D-665 기준점 기반 구역 로직과 별도 인지 평가

- 변경: 명시적 관측 기준점과 World 입력 유효성을 사용해 현재 구역을 산출하고 도로면/구역 정답을 따로 점수화한다. 중앙/최대 영역 대체·목적지 가지 선택·가림 채우기는 하지 않는다.
- 증거: b64dc94e0a 원격 합성 로직·기존 기준선·World 설치 wheel 35 passed, terminal exit 0, known_failures NEW 0. 시각 불일치·잘못된 정답·invalid image의 미평가 분모도 확인했다.
- gate 변화: 없음. 실제 투영 입력 생산자·독립 정답·coverage·장치 관측 전달은 미완료다.
- 결정: D-665

## 2026-10-11 · 468ae9e5ab · 도메인별 인지 coverage와 경계 오차 집계

- 변경: road_fitness의 내부 frame 결과를 도메인·조건별로 합산하고 경계 화소 거리와 제외/미산출 사유를 기록한다. 추론 보류와 정답 전체 255, 전체/점수화 정답 분모를 구별한다. 결과는 HOLD다.
- 증거: 새 집계 함수 부재의 원격 RED 후 합성 지표·구역·기존 기준선 44개 시험 terminal exit 0. 새 모델/실물 성능 시험은 아니다.
- gate 변화: 없음. dataset-backed 재생과 독립 출처·장치 수용은 후속이다.


## 2026-10-11 · 0b14fa02b0 · D-662 offline Pinky judgment checker

- 변경: main에서 추가된 D-662 checker 기록을 D-665 인지 평가 기록과 함께 보존한다.
- 증거: 아래 원래 기록과 연결된 implementation.md를 유지한다. 이번 병합의 재시험은 별도 receipt다.
- gate 변화: 없음. 원래 독립 profile과 팀 FIELD 수용 HOLD를 유지한다.

2026-10-11: D-662 offline Pinky judgment checker at 0b14fa02b0; independent review corrected required-ABSTAIN errors and duplicated physical windows. Remote acceptance-review-green 11 passed, NEW0 (8 checker + 3 installed delivery). Initial profile and team FIELD acceptance remain HOLD. See docs/validation/responsibility-boundaries-2026-10-11/implementation.md.

## 2026-10-11 · a8212d3806 · 모델 프레임 재생과 crop 정답 범위 결속

- 변경: evaluate_model_frame이 기존 preprocess와 모델 session 출력을 별도 도로면/구역 평가에 연결한다. crop 밖 알려진 정답은 실제 255와 구별해 제외 분모와 전체 grid coverage를 보존한다.
- 증거: a8212d3806 원격 55개 시험 terminal exit 0, 실제 ONNX Runtime crop/전체 영상 2개 포함. crop 제외 제거 2개 실패·원본 정답 모순 검사 제거 1개 실패 후 복구했다.
- gate 변화: 없음. 독립 dataset/파일 결속·물리 보정·실물 성능·장치 관측 수용을 검증한 결과가 아니다.

## 2026-10-12 · 1905962030 · D-666/D-667 고정 인지 진단과 공통 관측 계약

- 변경: 두 사람 승인 정답과 별도 관측 입력·모델·학습 출처를 고정 버전으로 결속하고, 로봇 설정 없이 HOLD 보고서를 생성한다. 공통 관측 계약과 World 기존 import는 같은 객체를 사용한다. 새 계약 파일을 구분하는 패키지 버전·의존 pin·서명 코드 묶음의 필수 파일을 정리했다.
- 증거: 재생 20개 합성 시험 terminal exit 0, NEW0. 승인 hash/짝 영상 검사를 제거한 2개 실패를 확인하고 복구했다. 공통 계약 이전 후 World 설치·아키텍처·학습 관련 시험 terminal exit 0, NEW0. 독립 소스 검토의 패키지 버전 문제를 수정했다. 최신 버전의 설치/전체 회귀·착지 증거는 후속 기록이다.
- gate 변화: 없음. 실제 독립 정답·보정·물체 성능·수용 profile·장치 관측 전달과 지연/손실, 실물/시뮬레이션 성능은 HOLD다. 기존 20261010 검수 데이터의 의미와 운영 선택을 유지한다.
