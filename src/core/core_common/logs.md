# core_common logs

추가만 한다. 형식: [module harness 설계](../../../docs/plans/2026-09-15-module-harness-design.md) §4.2.
2026-09-22 이전 이력은 `git log -- src/core/core_common`를 본다.

## 2026-09-22 · uncommitted · docs(harness): register core_common under D-168
- 변경: `AGENTS.md`(없던 경우), `progress.md`, `logs.md` 추가, `harness.yaml` 등록
- 증거: `python -m pytest src/core/core_common/test -q` — 1 passed (2026-09-22 Windows)
- gate 변화: 없음(신규 기록). SOURCE/LOCAL GO, 나머지 N/A(라이브러리 등급)
- 결정: D-168
- 교훈: config.py가 core share를 역참조한다 — D-168 KNOWN_CHAIN_BACK_EDGES

## 2026-09-22 · uncommitted · core_common+fleet_agent(identity): hello 신원 실값 공급 (T6)
- 변경: `RobotIdentity` 에 device_uid(빈 문자열 기본)·device_name(미지정 시 robot_name 폴백) 파라미터와 model/profile_model·hardware_serial/serial hello 필드명 property 를 additive 추가, from_config 가 robot.device_uid/device_name 을 읽음. `fleet_agent/agent.py` 는 hello 본문 생성을 hello_payload() 로 추출하고 hasattr 폴백 "" 제거 — 신원을 모르면 지어내지 않는다. SiteHub 방어 시험 2건(DUPLICATE_IDENTITY/IDENTITY_DRIFT)을 test_hub.py 에 신규(기존 무시험).
- 증거: `python -m pytest src/core/core/test/test_fleet_agent.py src/core/core/test/test_runtime_config.py src/site/fleet/test/test_hub.py src/core/core/test/test_protocol_schemas.py -q` 52 passed(신규 6건 적색 후 초록). 근거: communication-protocol-report.md §5 편차 ②.
- gate 변화: 없음.
- 결정: 없음 — D-170 과 같은 방향(계약 필드에 실값).
- 교훈: 없음.
