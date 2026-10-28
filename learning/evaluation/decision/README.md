# 독립 사건 원장 비교

D-715는 비교에서 실패·UNKNOWN 사건이 누락되지 않도록 보존 사건 inventory를 별도로 고정한다. 원장 사본에서 전체 profile tuple·owner·policy와 `start <= budget.started_at < end` 시간 창을 지정한다. 모든 상태를 포함하며 최대 1,000건을 넘으면 잘라서 수용하지 않는다.

```powershell
$RosyScratch = if ($env:ROSY_SCRATCH) { $env:ROSY_SCRATCH } else { [System.IO.Path]::GetTempPath() }
python tools/incident_case_inventory.py $RosyScratch/<session>/fleet.sqlite3 --profiles $RosyScratch/<session>/profiles.json --owner core --policy <policy-revision> --start <epoch-start> --end <epoch-end> --out $RosyScratch/<session>/inventory.json
python learning/evaluation/decision/operational_comparison.py $RosyScratch/<session>/cohort.json $RosyScratch/<session>/case.json --inventory $RosyScratch/<session>/inventory.json --inventory-digest <independently-frozen-digest> --out $RosyScratch/<session>/comparison.json
```

명세의 예상 digest는 별도 수용 설정에서 고정하며 읽은 파일의 자기 보고 hash를 자동 수용하지 않는다. 모델 전략마다 inventory 한 개가 필요하고 CLI에 경로·digest를 순서대로 전달한다. 같은 profile/policy/case의 이전·후속 export를 여러 전략에 사용하면 마지막 값을 덮어쓰지 않고 inventory 모드에서 모호한 자료로 거절한다. 기존 비교 모드는 유지한다. 결과의 `case_inventory.coverage`는 `retained_case_rows_only`이고 정상 명령·모델 호출·재발·정답·전체 원본 수집 coverage와 승격은 여전히 별도이며 HOLD를 유지한다. inventory 생산과 비교는 기존 출력을 덮어쓰지 않는다.

D-703은 실제 model export와 별도 검수 자료를 기존 보정 계산에 연결한다:

```powershell
python tools/decision_calibration.py --from-feedback $RosyScratch/<session>/reviewed-feedback.json
python tools/decision_calibration.py --from-feedback --compare $RosyScratch/<session>/reviewed-feedback-candidates.json
```

입력 schema는 `rosy.calibration.feedback_input/1`이며 exports·fit·evaluation·training·reviewed_profile을 가진다. fit/evaluation 검수 행에는 기존 id·session_id·recording_id·session_sha256·recording_sha256·reviewed_by·expected·latency_ms·네 가지 오류와 export_digest·subject_id·case_id·attempt_id·receipt_sha256·latency_source_sha256을 명시한다. alternatives·abstained·모델 identity는 receipt에서만 읽는다. 다른 역할/모델을 같은 profile의 평가 표본으로 넣지 않는다.

`feedback_bundle`의 변환 행은 `feedback_binding`을 포함한다. 팀이 고정하는 fit/evaluation hash는 이 변환 행을 대상으로 해야 한다. root 도구는 외부 고정 hash를 자동 갱신하지 않는다. UNKNOWN·receipt/검수 누락·변조·중복 입력은 확률이나 지연 0으로 채우지 않는다. 지연 원본 hash는 선언된 결속이며 도구가 원본 측정이나 reviewer 인증을 대신하지 않는다. 이 prediction 평가와 전체 운영 분모·실제 결과·승격은 별도로 검증한다.

기존 확률 보정은 `python tools/decision_calibration.py <frozen-bundle.json>`과 `--compare` 경로를 사용한다. D-702는 검수된 전체 최소 표본 수에 더해 평가에 등장한 각 구간의 fit/evaluation 최소 표본 수를 요구한다. 표본 부족·미검수 한계는 HOLD, 금지 오류는 FAIL이며 `metrics.error_counts`와 `fit_metrics.error_counts`는 네 가지 오류를 각각 보고한다. `forbidden`은 오류가 하나 이상인 사건 수여서 중복 오류 때문에 사건 분모가 늘지 않는다. PASS_OFFLINE_ONLY는 운영 승인이나 현장 품질 수용이 아니다.

D-701의 `operational_cohort/2`는 기존 /1 필드에 `rules` 후보 목록을 추가한다. 각 규칙 후보는 `strategy_sha256`, `config_sha256`, `owner_id`, `policy_revision`, `exports`를 가지며 exports는 기존과 같은 subject_id·case_id·digest 바인딩이다. 같은 평가 사건 집합의 `rule_feedback/1`과 모델 export를 기존 CLI에 함께 전달한다. 정상 case null은 별도 export로 보존하며 사건 cohort에 가짜 사건으로 넣지 않는다.

규칙 후보는 RULE_ONLY 자료만 허용하며 선택·필요성 건수만 보고한다. 결과·모델 호출·비용·명령·재발은 `null`이다. 보존 기록만으로 운영 coverage를 증명하지 않으며 독립 정답·한계와 운영 근거가 충족되기 전 비교·승격·현장 수용은 HOLD다. 기존 /1 입력과 모델 export /1·/2·/3은 유지한다.

D-697의 host-only 소비자다. Fleet 원장 export와 고정 cohort를 JSON으로 받아 사건 결과 건수, 알려진 한계 비용, 남은 예약 책임과 비용 불명 시도를 비교한다. Fleet·Decision·ROS·모델 제공자를 import하거나 호출하지 않는다. 출력은 언제나 HOLD이며 정답 수용·모델의 해결 기여·승격·현장 수용을 승인하지 않는다.

```powershell
python learning/evaluation/decision/operational_comparison.py $RosyScratch/<session>/cohort.json $RosyScratch/<session>/case.json --out $RosyScratch/<session>/comparison.json
```

입력은 각 파일 1MiB 이하로 제한하고 결과는 새 파일에 쓴다. UTF-8 BOM을 포함한 JSON도 읽는다. 기존 출력은 덮어쓰지 않는다. 두 역할 `model_feedback/1`과 선택적 인수 근거 `/2`, 단독 primary `/3`을 소비하고, 원문 제공자·개인 이름·payload를 결과에 복사하지 않는다.

cohort의 schema는 `rosy.incident.operational_cohort/1`이다. 닫힌 최상위 필드는 schema, domain, training, fit, evaluation, candidates다. training·fit은 session_id, recording_id, source_sha256 행 목록이다. evaluation은 여기에 subject_id, case_id를 더한 행 목록이다. 세 집합의 session·recording·원본 hash가 겹치면 거절한다. 평가 사건은 중복될 수 없다.

candidate는 strategy, strategy_sha256, profile_sha256, policy_revision, exports를 갖는다. strategy `primary`는 실제 단독 프로파일의 `/3`, `primary_reviewer`는 두 역할 `/1`·`/2`와만 연결한다(D-698). exports는 subject_id, case_id, digest 행 목록이며 평가 사건 집합과 정확히 일치해야 한다. 각 digest는 원래 case JSON과 전체 프로파일 목록을 결속한다. 변경·누락·중복·사용하지 않은 export는 거절한다. 전략을 실제 호출 횟수로 추정하지 않는다. 전체 목록 hash와 개별 모델 calibration hash는 서로 다르다.

known_marginal_micros는 실제 청구가 아닌 원장에 기록된 한계 비용의 합이다. reserved_liability_micros와 unknown_cost_attempts는 별도로 보존한다. 결과 불명을 비용 0이나 성공으로 바꾸지 않는다. outcomes는 원장의 관측 상태 건수이며 정확도나 인과적 성공률이 아니다.

현재 규칙 생산 기준, 독립 정답과 수용 한계, 정상 명령·재발의 완전한 추적 창, 실제 청구·운영 admission 근거가 부족하다. 단독 모델 생산은 source에 연결했지만 실제 Qwen 품질·현장 수용은 별도다. caller가 명시한 cohort·전략 hash도 데이터 출처 인증이 아니다. 따라서 누락 항목과 null을 남긴다. 두 역할 export를 규칙·단일 모델 자료로 가장하지 않는다. 다음 구현은 이 생산 경로와 출처 수용을 채우고 독립 비교 한계를 적용하는 것이다.

시험: `test/learning/decision/test_operational_comparison.py`와 기존 architecture 소유자·의존·크기 검사. pytest는 커밋된 HEAD를 적격 원격 호스트에 전달해 실행한다.

## D-734 SOURCE 진단 checkpoint

`operational_evidence.compile_evidence`는 `rosy.incident.operational_evidence/1`의 profiles/profile/calibration_input/cohort/exports/inventories/inventory_digests/truth/limits/windows/review만 받는다. 입력 PASS/report/binding/field_accepted/truth_admitted는 거절한다. 순수 compiler는 profile 선택 구조와 cohort/export/inventory를 검사하고, truth/limits/review/window 선언의 별도 trusted principal·kind·HMAC·기간을 확인한다. operations 구현을 import하지 않는다. 실제 개인 이름이나 source hash만으로 검수 상태를 만들지 않는다.

calibration_input은 기존 fit/evaluation/training/reviewed_profile 계산 입력이다. 기존 ROOT `tools/incident_operating.compile_original_evidence`가 실제 ModelProfile/incident_profiles/evaluate_calibration을 호출해 이를 재계산한다. compiler 직접 호출은 이 원본을 재계산하지 않으며 hash는 null, scope는 not_recomputed다. 선택적 닫힌 bundle-bound 진단 자료의 hash/state/domain shape를 확인해도 scope는 caller_supplied_diagnostics_only이고 원본 검증 증거가 아니다. ROOT 조합만 root_recomputed_profile_and_calibration_only를 보고하며 운영 수용은 항상 HOLD다. compiler/ROOT는 `rosy.calibration.feedback_input/1`을 직접 소비하거나 tools/decision_calibration.feedback_bundle을 호출하지 않는다. 원장 prediction receipt와 검수 행의 원본 결속은 feedback_prediction_export_lineage_admission으로 명시적으로 미지원이며 현재 schema 지원 목록에 넣지 않는다.

truth 행은 id/subject_id/case_id/session_id/recording_id/session_sha256/recording_sha256/start/end/expected/actor/resolved/recurrence/result_source_sha256/recurrence_source_sha256/latency_source_sha256/latency_ms와 missing_evidence_error/risk_omission/wrong_case/unnecessary_intervention을 가진다. 알려지지 않은 결과·재발·지연은 null이며 case 분모에서 지우지 않는다. 출력 metrics_scope는 authenticated_review_declarations_only다. 이 선언의 hash·서명 검사가 참조한 실제 원본과 물리 truth를 수용하지 않는다. 운영 limits의 형식·서명은 검사하지만 현재 측정값과 비교하지 않는다.

window 진단은 observation/model/command/submission/result/recurrence/invoice stream의 heartbeat run/sequence/receive·monotonic clock/boundary와 event ID·시각·case/generation/source hash·payload dict를 확인한다. payload 내부 의미, 전체 collector, model actor 기여, clock calibration과 실제 비용/결과/재발 상관관계는 미지원이다. 빈 heartbeat event를 실제 0건으로 수용하지 않는다.

ROOT `tools.incident_operating.load_original_sources`는 caller가 별도로 고정한 episode root/dataset revision/observation DB SHA를 받아 기존 verify_raw와 capture_window를 실행한다. raw pass dict를 대신 넣지 못하며 raw_sidecar_and_retained_observations_only scope를 보존한다. 별도 installation_getter는 pinned manifest와 실제 artifact bytes, signed owner runtime/process 선언을 확인하고 manifest+process 설치 hash를 독립 계산한다. signed_owner_declaration_only이며 OS probe/활성화/physical truth가 아니다.

현재 compiler 출력은 unsupported 목록으로 항상 HOLD다. OperatingEvidenceOwner의 운영 binding branch는 이 HOLD 때문에 도달하지 않으며 installation/calibration getter를 매 evidence 호출에서 실행하는 연결이 아니다. 승인 importer는 flags-only callback을 거절하고 현재 기존 DB apply를 재사용하도록 준비했으며 폐기는 저장된 binding의 기존 검증에 맡긴다. 새 ROOT 설정·서명·운영 활성화는 없다. 이 checkpoint는 US-006 전체 producer 완료가 아니다. 전체 collector·actor credit·clock calibration·원본 invoice·실제 결과/재발·OS probe admission·door/arm을 다음 source/외부 수용 작업으로 남긴다.
