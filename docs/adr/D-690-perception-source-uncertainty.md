# D-690 도로 인지 평가의 출처 단위 불확실성

**Status:** Accepted (2026-10-12, 내부 평가 진단 계약). 인지 승인·배포·주행 수용은 HOLD다.

### Context

D-659는 도로면 인지와 주행 판단을 분리하고 독립 평가를 요구한다. D-666 고정 재생의 픽셀 합산 점수만으로는 같은 촬영에서 나온 인접 프레임의 의존성을 드러내지 못한다. 새 정답이나 물리 보정 없이도 평가 자료의 출처별 표본 수와 변동성을 표시할 수 있다.

### Decision

1. 고정 재생의 프레임 보고서에 검증된 정답 manifest의 `identity`, `session`, `capture_group`을 결속하고 `source_uncertainty`를 추가한다. 중복 identity, 빈 문자열, 공백으로 달라지는 식별자, 한 session의 여러 capture group, 한 capture group의 실물/시뮬레이션 혼합을 거절한다. 기존 독립 검수·모델/학습 출처 분리 검증을 통과한 내부 프레임 보고서가 입력이다. 외부 보고서의 인증 도구가 아니다.
2. 실물과 시뮬레이션을 분리하고 각 조건에서도 출처별 프레임 수·픽셀 합산 지표·abstention·coverage를 보고한다. 기존 `_summarize`의 분모와 점수를 재사용하며 프레임 IoU를 평균하지 않는다. 미예측 정답을 임의의 false negative로 만들지 않는다.
3. `capture-group-percentile-bootstrap/1`은 capture group 전체를 복원추출한다. 각 반복에서 모든 프레임과 보류 결과를 함께 반영하고, 도로면/현재 구역에 같은 출처 선택을 적용한다. 정렬된 출처와 seed 0, 1,000회, 선형 percentile 2.5/97.5를 고정한다. IoU, outside false positive rate, missed fraction, full-grid pixel coverage, frame coverage를 계산한다. 기존 NumPy와 표준 라이브러리를 사용한다. 모델 추론을 반복하지 않는다.
4. 출처가 두 개 미만이면 구간은 null, `insufficient_sources`다. 어느 반복에서든 분모가 0이면 해당 지표의 구간은 null, `undefined_resamples`이고 유효 반복 수를 남긴다. 정의되지 않은 반복을 조용히 제거하지 않는다. 두 출처는 계산 가능 조건일 뿐 충분한 표본 수나 통계적 독립성의 증명이 아니다. 소수 출처나 동질적인 자료의 좁은 구간은 일반화 성능의 증거가 될 수 없다.
5. 전체와 조건별 결과는 항상 HOLD다. 이 경험적 구간은 독립 검수, 실제 보정, 평가 표본/coverage 기준, 수용 임계값, 장치 전달 및 시뮬레이션/실물 수용을 대신하지 않는다. source group 자체의 올바른 분류도 별도 검수 대상이다. 인지 결과로 따라갈 길을 선택하거나 CORE의 최종 명령 권한을 바꾸지 않는다.

### Alternatives and consequences

프레임별 재표집은 같은 촬영의 프레임을 독립 표본처럼 다루므로 채택하지 않는다. 새 통계 의존성이나 임계값 설정은 추가하지 않는다. object 평가는 별도 의미·정답 계약이 준비될 때 연결한다. 이 변경은 파일 평가 결과의 추가 필드이며 기존 점수와 관측 전달 계약을 유지한다.

### Verification

출처 크기가 다른 자료의 합산 점수와 재표집, 입력 순서 불변, 단일/빈 출처, unknown 정답, anchor abstention, 식별자·domain 충돌, 고정 재생 호출자의 manifest 결속을 원격 시험한다. 합성 시험은 인지 성능 수용의 증거가 아니다.

**Related:** D-427, D-429, D-430, D-659, D-665, D-666, D-673. Percentile 방식 참고: [SciPy bootstrap 문서](https://docs.scipy.org/doc/scipy/reference/generated/scipy.stats.bootstrap.html). SciPy 의존성을 추가하지 않는다.
