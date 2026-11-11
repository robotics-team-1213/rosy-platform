# 알림 전달 (전환 전)

독립 wheel `rosy-notifications`는 등록된 Fleet·Harbor의 전달 건만 받는다.
업무 outbox·현재 필요성·수신 범위는 생산자가 소유한다. 기존 Fleet worker가 현재 발송 정본이다.
새 서비스는 배치되지 않았으며 실제 채널 전송·owner 교체는 이번 변경 범위가 아니다.

계약은 [D-998](../../docs/adr/D-998-notification-delivery-http-journal.md)와
[API reference](../../docs/reference/ROSY%20API%20%26%20Protocol%20Reference.md)의 v1.377이다.

보호 JSON 설정은 `channels`와 `producers` 두 mapping을 갖는다.
각 channel 행은 `kind`, `endpoint_env`, Telegram일 때 `chat_id_env`를 지정한다.
각 producer(`fleet` 또는 `harbor`) 행은 `token_env`, `channels`(허용 channel key 목록),
`owner_url`, `owner_token_env`, `screen_url`, `budget`을 지정한다.
`budget`은 `interval_s`, `max_attempts`, `ttl_s`, `capacity`, `admissions_per_minute`다.
Harbor는 모두 명시하고 Fleet은 D-661의60초·3회·600초를 유지한다.
화면 링크·callback URL은 query/자격 없는 HTTPS이며 channel URL·기계 토큰·callback 토큰은 환경변수로만 주입한다.
등록된 기계 토큰과 callback 토큰은 다르다. 파일·환경·DB·lock은 동일 운영자만 읽고 쓸 수 있는 디렉터리에 둔다.

설치 후 `rosy-notifications --config <protected-json> --journal <private-sqlite>`로 loopback 접수를 연다.
worker는 기본 꺼짐이다. `--enable-worker`는 전송 가능한 opt-in이므로 fake 채널 시험 또는 별도 승인된 배치에서만 사용한다.
프로세스 하나가 원장을 소유한다. SQLite 파일을 복제해 두 worker를 켜지 않는다.
중지 후 원장·등록 설정을 함께 백업하고 복원 뒤 UNKNOWN과 생산자 outbox를 대조한다.
이 모듈은 Linux/POSIX 대상이며 `COLCON_IGNORE`를 유지한다.

원격 시험: `python tools/remote/remote_pytest.py --log-dir <external-log-dir> -- operations/notifications/test`.
반환된 각 run 로그를 `python test/known_failures.py <run-log>`로 비교한다.
