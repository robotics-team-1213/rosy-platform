# D-734 원본 검수 자료와 현재 설치를 분리하는 운영 근거 소유자

**Status:** Proposed (2026-10-12; SOURCE implementation only, no operating admission)

## 문제와 책임

D-727/D-730의 서명·원장 소비자는 evidence owner가 실제 truth·한계·coverage·설치를 검증했다고 전제한다. 현재 시험의 PASS dict와 임의 hash는 그 producer가 아니다. D-697 비교는 계속 HOLD다. Model PC의 독립 평가가 Fleet writer를 import하거나 호출해서는 안 된다.

기존 `learning/evaluation/decision`에 순수 frozen evidence 진단 compiler를 둔다. 기존 export/cohort/inventory 계약을 재검증하고 인증된 검수 **선언**을 결속한다. D-427 금지 import 방향을 유지하며 기존 ROOT `tools/incident_operating.py`가 operations의 실제 profile/보정 계산을 조합한다. 출력은 항상 HOLD이며 운영 producer 완료가 아니다. ROOT의 별도 설치 getter는 외부 고정 SHA로 manifest와 실제 설치 artifact bytes를 확인하고 signed owner runtime 선언에서 설치 hash를 계산한다. OS probe 인증·실제 설치 활성화·현장 truth를 증명하지 않는다. 기존 OperationalState.apply와 같은 DB를 재사용할 importer 준비를 두고 기존 ROOT factory 기본 off를 유지한다. 새 서비스·DB·네트워크·모델 호출·CORE writer는 없다.

## 닫힌 입력과 수용

내부 `rosy.incident.operational_evidence/1`은 profiles/profile/calibration_input/cohort/exports/inventories/inventory_digests/truth/limits/windows/review를 가진다. PASS report, binding, field_accepted, truth_admitted를 입력으로 받지 않는다. 기존 ROOT compile_original_evidence가 full profile/calibration codec으로 보정 입력의 형식·독립 분리를 실제 재계산하고 닫힌 bundle-bound 진단 hash/state/domain 자료를 순수 compiler에 전달한다. compiler 직접 호출은 이 원본을 재계산하지 않아 profile/calibration hash는 null, scope는 not_recomputed다. caller 진단 shape만 검증하면 caller_supplied_diagnostics_only이며 원본 proof가 아니다. ROOT 조합만 root_recomputed_profile_and_calibration_only를 보고한다. compiler의 cohort/export codec은 보존 사건 분모를 재검증한다. 원장 prediction 원본과 검수 행의 결속은 아래 별도 미지원 경계다. UNKNOWN·실패를 사건 분모에서 누락하지 않는다.

calibration_input은 기존 fit/evaluation/training/reviewed_profile 계산 입력이며 `rosy.calibration.feedback_input/1`을 직접 소비하지 않는다. 기존 feedback_bundle의 원장 prediction receipt→검수 행 원본 결속도 호출하지 않아 feedback_prediction_export_lineage_admission으로 미지원이다. 보정 재계산과 cohort/export 재검증이 이 별도 원본 결속까지 증명하지 않는다.

truth 입력은 정확한 subject/case/session/recording, 결과·재발·지연 원본 hash와 오류를 **선언**하는 검수 행이다. codec과 HMAC 인증은 원본 참조의 실제 진위·측정·physical actor를 확인하지 않는다. signed review가 전체 bundle bytes에 결속됐는지만 검증한다. UNKNOWN 결과·재발·지연은 null로 보존하고 선언 기반 진단 건수/비율의 scope를 명시한다. limits는 검수자가 공급한 닫힌 숫자 표의 형식·서명을 검사하지만 현재 운영 지표와 비교하지 않는다. 성능 한계 값을 코드에서 발명하지 않는다. 실제 팀 최종 truth/limits 수용과 품질 판정은 미완료다.

`rosy.incident.operational_window/1`의 현재 진단 codec은 subject/start/end, stream run, heartbeat sequence·monotonic/receive clock, event ID·시각·case/generation·source hash·payload dict를 검사한다. source principal HMAC은 이 선언을 인증한다. payload dict의 stream별 내부 의미와 실제 collector의 전체 누락·시작/끝·actor/case 상관관계는 검증하지 않는다. 따라서 full command/model/submission/result/recurrence/invoice/observation collector가 아니다. empty heartbeat도 물리 0건의 증거가 아니며 source digest와 서명은 raw 내용 검증의 대체물이 아니다.

운영 수용의 다음 계약은 같은 사건의 후보/제출/ACK·원본 최종 출력·독립 검수 결과, 정상 구간의 전체 호출/명령 원인, 후속 재발 창과 실제 invoice를 결속해야 한다. ACK는 접수이며 성공이 아니다. 현재 source는 이 actor/ACK/UNKNOWN/result/recurrence/cost 상관관계를 구현하지 않았고 missing/unsupported로 남긴다. 원본 없이 해결률·무명령·재발 0건을 수용하지 않는다.

별도로 호출할 수 있는 ROOT installation_getter는 고정 manifest의 identity/profile/model/calibration/policy/action contract, 실제 artifact 파일 hash, signed current runtime 선언과 process identity/time을 검사한다. receipt의 기대값을 복사하지 않고 manifest+process에서 설치 hash를 계산한다. runtime scope는 signed_owner_declaration_only다. 이 검사도 실제 OS process probe·provider admission·현장 수용을 대체하지 않는다. OperatingEvidenceOwner는 compiler HOLD에서 거절하므로 현재 evidence 호출이 installation/calibration getter나 운영 binding 계산 branch에 도달하지 않는다. 그 branch는 준비 코드이며 운영 연결 완료가 아니다.

ROOT load_original_sources는 실제 기존 verify_raw/capture_window를 호출하고 dataset revision·고정 SQLite bytes를 확인한다. 인정하는 scope는 raw_sidecar_and_retained_observations_only이고 원래 raw verifier의 unverified motion/outcome 및 관측 수집 scope를 확대하지 않는다. 입력 raw pass dict는 받지 않는다. 선택적 원본 loader 자료가 있어도 compiler는 unsupported 목록 때문에 항상 HOLD다. importer는 승인 전에 이 구체 ROOT owner를 요구해 flags-only callable을 거절한다. 별도 폐기는 기존 stored binding 검증에 맡겨 새 원본이 HOLD여도 차단하지 않는다. compiler/ROOT는 승인 서명·활성화를 수행하지 않는다.

## 검증과 후속

RED/GREEN은 flags-only fake PASS, 파일/서명/trust kind, window ID/sequence/clock/boundary, UNKNOWN label/null, 설치 bytes/identity/expiry와 importer 거절/폐기 경계를 확인한다. 기존 보정·비교·원장·P6/import 회귀도 원격으로 검증한다. 전체 collector·actor credit·clock calibration·invoice·실제 결과/재발·OS probe admission·door/arm은 unsupported다. US-006 전체 기준, 실제 데이터 검수·서명·설치·모델·현장 수용·승격·복귀는 미완료다.
