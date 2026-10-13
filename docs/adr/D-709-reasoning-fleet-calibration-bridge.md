# D-709 승인 원장과 Fleet 보정 포트 연결

**Status:** Accepted (2026-10-12, source contract)

D-705의 명시적 보정 포트를 D-707 영속 승인 원장에 연결한다. learning registry는 승인된 후보를 정확한 전체 profile JSON과 domain으로 조회하고 현재 snapshot·상태·chain·receipt 신뢰를 다시 검증한다. 폐기·누락·다른 profile/domain은 후보를 반환하지 않는다.

root orchestration `tools/incident_reasoning.py`는 기존 incident_model_config에 이 두 읽기 포트만 구성한다. 기존 create_app→install_incident_runtime→IncidentCaseWorker 경로를 사용하고 Fleet에서 learning을 import하지 않는다(D-427). profile/provider/current/admission/budget/enabled는 바꾸지 않고 이미 지정한 보정 포트를 덮어쓰지 않는다. 초기화가 승인이나 모델 활성화가 아니다.

보정 artifact와 승인 map은 매 요청마다 원장을 다시 읽는다. 그 사이 폐기·변조·신뢰 변경이 있으면 기존 worker의 미수용→제한 reviewer/최종 인수 경로로 처리한다. 같은 입력 binding·정상 무호출·case/role/time/cost 예산과 CORE 최종 권한을 유지한다. 같은 DB의 실제 factory/worker 흐름에서 승인과 폐기를 검증하며 후보를 action authority로 사용하지 않는다.

설치 trust·Model PC 원장 전달·AI PC 실제 추론·운영 current/previous와 사건별 revision 전환·현장 수용은 후속이며 새 서비스나 SDK 공개 wire는 추가하지 않는다.

동기 원장 읽기·보정 재계산은 worker에서 off-loop 실행하고 기존 case deadline 안에서만 결과를 기다린다. 완료 후 사람 소유권과 현재 사건/관측을 다시 확인하며, 만료 시 최종 미해결 인수로 종결한다. 취소/만료된 readonly thread의 반환으로 추가 모델 호출이나 원장 상태 변경을 하지 않는다.
