# D-703 실제 모델 원장과 검수 보정 입력 결속

**Status:** Accepted (2026-10-12, source contract)

기존 root 실행 연결 도구 `tools/decision_calibration.py`에 `--from-feedback`을 추가한다. 기존 모델 export /1·/2·/3과 Decision의 순수 Problem/Profile/Judgment 검증, 기존 독립 보정 계산을 연결한다. learning의 JSON 소비자에 Fleet/Decision runtime import를 추가하지 않는다. 별도 서비스·모델 호출·원장 writer를 만들지 않는다(D-427·D-429·D-430).

입력은 schema `rosy.calibration.feedback_input/1`, exports, fit, evaluation, training, reviewed_profile이다. fit/evaluation의 각 검수 행은 기존 id·lineage·reviewed_by·expected·네 가지 오류·latency_ms와 export_digest·subject_id·case_id·attempt_id·receipt_sha256·latency_source_sha256을 명시한다. 모델의 alternatives와 revision·domain·abstained는 해당 원장의 검증된 receipt에서만 읽는다. source의 전체 profile hash와 검수 profile의 identity·choices가 일치해야 한다.

변환 행에는 feedback_binding(export/receipt/attempt/입력/관측 revision/지연 자료 hash)을 포함한다. 기존 reviewed_profile의 fit/evaluation/training hash는 변환 자료에 대해 팀이 고정한 외부 입력이어야 하며 도구가 자동으로 고치지 않는다. 모델 판정에서 정답·오류 없음·지연 0을 생성하지 않는다. 선언된 지연 hash와 reviewer 표시 이름은 자료의 진위나 검수자 인증을 입증하지 않는다.

평가 프로파일에 해당하는 모든 model attempt를 검수 행에 정확히 한 번 결속한다. UNKNOWN·진행 중·receipt 누락·검수 누락은 평가 가능한 확률로 채우거나 분모에서 조용히 빼지 않고 입력을 거절한다. 다른 역할은 해당 프로파일의 보정 표본이 아니다. fit/evaluation 간 동일 attempt·input 재사용, 미사용/중복 export와 기존 lineage 누출은 거절한다. 결과는 prediction quality의 오프라인 범위이며 정상 무명령·재발·실제 해결·운영 coverage·현장 수용·승격은 별도다. 기존 수용되지 않은 모델의 호출 권한을 늘리지 않는다.
