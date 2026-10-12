# D-734 원본 검수 자료와 현재 설치를 분리하는 운영 근거 소유자

**Status:** Proposed (2026-10-12; SOURCE implementation only, no operating admission)

## 문제와 책임

D-727/D-730의 서명·원장 소비자는 evidence owner가 실제 truth·한계·coverage·설치를 검증했다고 전제한다. 현재 시험의 PASS dict와 임의 hash는 그 producer가 아니다. D-697 비교는 계속 HOLD다. Model PC의 독립 평가가 Fleet writer를 import하거나 호출해서는 안 된다.

기존 `learning/evaluation/decision`에 frozen evidence compiler를 둔다. 기존 export/cohort/inventory/보정 계약을 재검증하고 인증된 최종 검수와 원본 수집 창을 결속한다. ROOT `tools/incident_operating.py`는 외부에 고정된 SHA로 원본 파일을 읽고 실제 설치 artifact와 현재 runtime 원본을 검사한 뒤 기대 binding을 독립 계산한다. 기존 OperationalState.apply와 같은 DB를 사용하고 기존 ROOT factory 기본 off를 유지한다. 새 서비스·DB·네트워크·모델 호출·CORE writer는 없다.

## 닫힌 입력과 수용

내부 `rosy.incident.operational_evidence/1`은 profiles/profile/calibration_input/cohort/exports/inventories/inventory_digests/truth/limits/windows/review를 가진다. PASS report, binding, field_accepted, truth_admitted를 입력으로 받지 않는다. 기존 full profile/calibration/cohort/export 코드가 원래 prediction과 분모를 다시 검사한다. train/fit/evaluation session·recording·원본 hash를 분리하고 UNKNOWN·실패를 누락하지 않는다.

truth는 정확한 subject/case/recording과 원본 결과·위험·정상 미개입·재발·지연 자료를 참조하는 최종 검수 행이다. limits는 팀이 검수한 최소 표본·정확도·지연·비용·종결·재발 한계의 닫힌 숫자 표다. 성능 한계를 코드에서 발명하지 않는다. 독립 reviewer의 signed payload는 전체 원본 bundle hash·truth·limits·coverage를 결속하며 현재 trust kind/key·기간을 검사한다. 모델 응답과 표시 이름은 검수 서명이 아니다.

`rosy.incident.operational_window/1`은 subject/start/end와 producer run의 연속 heartbeat sequence·monotonic/receive clock 및 typed original events를 담는다. 전체 command/model/submission/result/recurrence/invoice/observation 창을 독립 source principal이 서명한다. 처음·끝 boundary, 순서·중복·누락·재시작, event 시각과 actor/case/generation/source hash를 검사한다. 빈 event 목록만으로 0건을 수용하지 않는다. raw recording과 CORE 최종 cmd_vel을 독립 원본 검증으로 대조해야 한다. source digest와 서명 자체는 raw 내용 검증의 대체물이 아니다.

ACK는 접수다. UNKNOWN·미해결·결과 확인 실패는 성공 분모에 남고 성공으로 보간하지 않는다. model 기여는 같은 사건의 후보/제출/ACK·원본 최종 출력·독립 검수 결과를 함께 요구한다. 정상 미개입은 normal truth 구간과 전체 모델 호출·명령 원인을 함께 검사한다. 재발은 검수된 후속 창을 요구한다. 실제 invoice와 원장 한계 비용은 별도다.

ROOT의 `rosy.incident.installation/1`은 site installation identity, 전체 profile set, selected full profile, model/calibration/policy/action contract, 실제 artifact 파일 hash와 현재 runtime readback을 결속한다. ROOT의 외부 expected file SHA·현재 owner getter·독립 source trust로 검증하며 receipt에서 기대값을 복사하지 않는다. expired/stale/다른 설치·artifact/provider/revision이면 거절한다. current installation getter는 매 evidence 조회에 재검증하여 기존 claim 직전 gate와 폐기를 보존한다.

검증되지 않은 입력은 거절하고 누락·UNKNOWN·불완전 창·미검수 한계는 HOLD/null이다. 모든 원본·검수·설치가 닫힌 경우에만 operational_acceptance/1과 D-727 binding을 계산한다. compiler는 승인 receipt를 서명하지 않고 importer도 활성화를 자동 수행하지 않는다. 실제 trusted reviewer/source principal, full-window 수집, runtime 설치와 FIELD 정답이 없는 지금은 SOURCE만 검증한다.

## 검증과 후속

RED는 flags-only fake PASS, 변조·위조 HMAC·다른 trust kind·잘린 분모·보정 누출·원본/clock/window/ACK/UNKNOWN/설치 mismatch를 거절한다. 실측 한계와 실제 운영 서명은 만들지 않는다. 커밋 HEAD를 strict remote runner로 검증하고 known_failures와 비교한다. 실제 데이터 검수·서명·설치·제한 모델 호출·현장 수용·승격·복귀는 별도다.
