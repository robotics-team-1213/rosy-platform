# incidents

**Parent context:** `../AGENTS.md`. **Updated:** 2026-10-11.

D-661 팀 알림·사람 인수 책임이다. `handoff.py`는 이름 있는 담당자의 사건 claim,
`notifications.py`는 같은 Fleet DB의 outbox와 고정 채널 worker를 소유한다.
판단·해결기는 `fleet/stuck`, 인증·라우트·생명주기 연결은 `fleet/server`에 남는다.
CORE 장치 admission이나 최종 명령 권한을 추가하지 않는다.

직접 import를 사용하고 이전 루트 경로 shim을 두지 않는다. 기존 DB와 transaction,
직전 freshness/case/claim 검사, 실패·UNKNOWN 처리와 secret 비노출을 유지한다.
`test_incident_handoff.py`, `test_notifications.py`와 설치 검사를 원격에서 검증한다.
크기 경계는 `docs/plans/2026-10-11-fleet-team-incidents-subpackage.md`를 따른다.
