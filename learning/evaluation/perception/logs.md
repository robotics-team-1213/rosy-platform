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

