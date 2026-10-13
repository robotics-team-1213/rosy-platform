# D-705 Incident 실행 책임과 운영 보정 포트

**Status:** Accepted (2026-10-12, source contract)

기존 bounded read-only worker의 실제 구현을 같은 Fleet distribution의 `incidents/automation/execution/worker.py`로 옮긴다. 기존 `automation.worker.IncidentCaseWorker`는 직접 class re-export로 유지한다. 실행/cancellation/provider orchestration은 execution owner, 원장·예산·UNKNOWN은 ledger owner, observation/closure/factory는 부모가 맡는다. 기존 299행 worker의 이동을 child 기준으로 삼으며 부모 기준·+150·파일 한도를 올리지 않는다(D-427·D-429).

worker의 선택적 동기 포트 `calibration_artifacts(profile)`와 `approved_artifacts()`는 함께 지정한다. 기존 immutable CalibrationArtifact와 외부 승인 revision→digest를 읽어 `select_calibrated`를 production 경로에서 호출한다. 근거 부족·이의·Fleet 불일치와 함께 미수용/낮은 보정 신뢰도·대안 차이는 제한 reviewer 호출의 사유가 된다. 보정으로 reviewer를 부를 때 같은 입력의 primary prior를 전달한다. 포트가 없으면 기존 bounded read-only 동작을 유지한다.

승인된 profile/artifact라고 물리 authority를 주지 않는다. 마지막 미수용 판정도 기존 get_incident_status 읽기만 허용하고 조치 candidate는 실행하지 않는다. 읽기·후속 모델 호출은 기존 사건/관측/역할/시간/비용 예산 안에서만 진행하고 최종 미해결 인수는 유지한다(D-430). 포트 오류는 자기 승인·hash 변경이 아닌 미수용 판정으로 다룬다.

영속 reasoning registry·운영 승인 공급·승격/복귀와 새 사건 revision 전환은 아직 구현하지 않는다. 이 포트 연결은 registry나 physical dispatch 완료가 아니다. 모델 호출·배포·현장·독립 품질 수용은 별도다.

GLM codec은 Fleet 불일치만을 전제하지 않고 같은 사건·입력에 결속된 primary prior를 받는다. 재평가 필요 여부와 호출 예산·승인은 Fleet/제공자 경계가 맡으며 codec의 profile·schema·unsafe 검증은 유지한다. 승인 포트의 일반 예외는 미수용으로 처리하고 cancellation과 BaseException은 삼키지 않는다.
