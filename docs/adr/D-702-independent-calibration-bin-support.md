# D-702 독립 보정 평가의 구간 표본 수와 금지 오류

**Status:** Accepted (2026-10-12, source contract)

기존 확률 보정 계산과 고정 정답 비교를 재사용한다. 팀이 검수한 `minimum_bin_cases`를 오프라인 PASS와 실제 advisory 선택에 동일하게 적용한다. 평가에 등장한 각 choice·확률 구간에서 fit과 evaluation 표본 수가 모두 최소값 이상이어야 한다. 전체 표본 수가 많아도 드문 구간이 부족하면 HOLD다. 평가에 나타나지 않은 빈 구간은 이 조건의 분모가 아니며, 해당 구간의 runtime 선택은 기존처럼 거절한다.

관측 부족 처리 오류(`required_abstain_error`), 위험 누락(`unsafe_error`), 다른 사건 조치(`binding_error`), 정상 불필요 효과(`unnecessary_effect`)는 기존처럼 fit/evaluation에서 하나라도 있으면 FAIL이다. 기존 forbidden 사건 수와 별개로 각 오류 건수를 보고한다. 한 사건의 여러 오류는 각 항목에 모두 계산하며 사건 수를 늘리지 않는다. 정답과 오류 여부는 검수 입력이며 모델 합의나 관측 종결을 정답으로 생성하지 않는다.

D-427의 Model PC 독립 평가 책임, D-429의 기존 계산/CLI 재사용, D-430의 평가와 runtime/CORE 권한 분리를 유지한다. PASS_OFFLINE_ONLY는 실제 원장과 정답의 출처 수용·물리 결과·운영 coverage·모델 승격을 뜻하지 않는다. 기존 runtime의 외부 승인 hash와 모든 admission을 유지한다.
