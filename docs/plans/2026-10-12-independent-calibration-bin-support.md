# 독립 보정 평가 기준 일치 Implementation Plan

**Goal:** 팀 검수 최소 구간 표본 수와 네 가지 금지 오류를 기존 오프라인 비교에서 정확하게 보고한다.

## Source checkpoint

최신 main 통합 commit `d34e8c2e358129143dd9933b2ace33f42558aafb`를 로컬 착지했다. 적격 AI PC 9GB 원격 통합은 5,039 passed/246 skipped, terminal exit 0, known-failures NEW 0과 lint를 통과했다. Fleet 전체·제공자 어댑터·실제 설치·구조·release·기존 보정 계산/CLI를 포함한다. 고정 로그는 세션 `logs/bin-support-land-d34e8c2e35/run-1.txt`다. 아래 110개는 통합 전 관련 회귀다. push·실제 모델 품질·배포·현장 수용은 수행하지 않았다.

commit `e7beee4fbc`의 원격 관련 5개 파일 시험은 적격 현장 PC 8.6GB에서 110 passed, terminal exit 0, known-failures NEW 0이다. 기존 보정 계산·runtime 선택·동일 정답 비교·CLI와 구조 회귀를 포함한다. 로그는 세션 `logs/bin-support-green/run-1.txt`다. 최초 RED는 기존 누락을 4 NEW로 재현했으며 기존 실패 목록에 추가하지 않았다. 독립 읽기 검토에서 중요한 source blocker는 없었다.

전체 최소 표본 수와 구간별 fit/evaluation 최소 표본 수를 함께 요구한다. fit/evaluation 오류별 건수와 forbidden 사건 분모를 구분하고 기존 외부 승인 hash를 바꾸지 않는다. 마지막 main 통합·lint·remote·known-failures 게이트는 착지 도구가 수행한다. 실제 모델 성능·검수 정답의 출처 수용·운영 coverage·배포·현장 수용은 이 source 증거로 승인하지 않는다.

1. 실제 기존 계산을 호출하는 시험에서 전체 표본은 충분하지만 한 구간의 fit/evaluation 표본만 부족한 상황을 재현한다. 동일 정답 비교와 기존 CLI도 HOLD를 전달해야 한다.
2. 기존 metrics에 오류별 건수를 추가하고 기존 forbidden 사건 수를 유지한다. 기존 PASS 판정에 평가 구간별 fit/evaluation 최소 표본 조건만 추가한다. 빈 미평가 구간은 PASS의 추가 요구로 만들지 않는다.
3. 커밋 HEAD를 원격 시험하고 known-failures와 비교한다. 기존 runtime 선택·보정 CLI·동일 정답 비교·구조 회귀와 독립 검토 후 승인된 로컬 병합을 한다.

후속은 실제 원장·별도 검수 정답·latency·source lineage를 결속한 평가 입력 생산이다. 부족한 지연·정답·전체 운영 coverage를 추정하지 않는다. 실제 모델·배포·현장 수용과 개선 승격·복귀는 별도이며 전체 목표는 ACTIVE다.
