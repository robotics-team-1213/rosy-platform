# 독립 보정 평가 기준 일치 Implementation Plan

**Goal:** 팀 검수 최소 구간 표본 수와 네 가지 금지 오류를 기존 오프라인 비교에서 정확하게 보고한다.

1. 실제 기존 계산을 호출하는 시험에서 전체 표본은 충분하지만 한 구간의 fit/evaluation 표본만 부족한 상황을 재현한다. 동일 정답 비교와 기존 CLI도 HOLD를 전달해야 한다.
2. 기존 metrics에 오류별 건수를 추가하고 기존 forbidden 사건 수를 유지한다. 기존 PASS 판정에 평가 구간별 fit/evaluation 최소 표본 조건만 추가한다. 빈 미평가 구간은 PASS의 추가 요구로 만들지 않는다.
3. 커밋 HEAD를 원격 시험하고 known-failures와 비교한다. 기존 runtime 선택·보정 CLI·동일 정답 비교·구조 회귀와 독립 검토 후 승인된 로컬 병합을 한다.

후속은 실제 원장·별도 검수 정답·latency·source lineage를 결속한 평가 입력 생산이다. 부족한 지연·정답·전체 운영 coverage를 추정하지 않는다. 실제 모델·배포·현장 수용과 개선 승격·복귀는 별도이며 전체 목표는 ACTIVE다.
