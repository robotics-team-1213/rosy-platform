# 공통 UI 통합 증거 — manifest 형식 정정

2026-10-24. [통합 기록](2026-10-24-local-integration.md)이 가리키는 `runtime-manifest.json`은 `independent_review` 키 앞에 패치 표시 문자 `+`가 남아 JSON 파싱에 실패했다. 원본과 기존 기록의 SHA-256은 그대로 보존한다.

정정본: `Rosy/docs/workspace-records/2026-10-24/component-integration-evidence/runtime-manifest-v2.json`.

SHA-256: `360ca9f64b6f766afd638ee8a46d786e2521d31469899f104be44b8f13b3943c`.

원본에서 해당 문자 한 개를 제거한 바이트가 정정본과 정확히 같음을 확인했다. 정정본 JSON 파싱과 근거 파일 71개의 SHA-256 대조를 통과했다. 실행 코드 기준 `2d9acbfa51`, 시험 결과, 새 캡처 36장, 검토 범위와 수용 한계는 통합 기록을 따른다. 이후 기계 판독에는 v2를 사용한다.

문서 대기 작업은 자신의 대기열 항목·프로세스임을 확인한 뒤 중단했고, 정정 기록을 포함한 새 커밋으로 공식 착지 절차를 다시 실행한다. 이 형식 오류의 원인과 정정·검증은 두 manifest와 이 기록으로 재현할 수 있어 별도 해결 교훈을 추가하지 않는다. 작업 공간 제거 원인에 관한 CE 미해결 상태는 기존 기록을 따른다.
