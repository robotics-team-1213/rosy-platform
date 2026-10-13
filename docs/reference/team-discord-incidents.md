# 새 팀 Discord 채널과 Fleet 사건 인수

첫 현장 대상은 Pinky 차선 정지·재관측이다. 2026-10-12 사용자 계정의 지정 팀 채널에 `ROSY Fleet` incoming webhook을 만들고, 사용자 승인 연결 확인 메시지 1건의 HTTP 200·메시지 ID·채널 UI 수신을 확인했다. 이 연결 확인은 Fleet outbox나 실제 사건 인수·장치 결과의 수용이 아니다. URL과 채널 식별·receipt·화면은 비공개 X 세션에 보관하며 공개 문서에 넣지 않는다. 진행 계약은 [D-661](../adr/D-661-fleet-named-handoff-and-team-notification-outbox.md)이다.

사용자 후속 방향은 Discord 대화로 작업 요청을 받고 일반 관리는 Fleet Console 규약, 위험 상황은 Discord 관리·대응이다. incoming webhook은 대화를 받지 못하므로 Bot 수신·기명 principal 연결·요청/결과 원장이 별도로 필요하다. [D-669 제안](../adr/D-669-discord-work-intake-and-fleet-response-boundaries.md)의 [설계 점검](../plans/2026-10-12-discord-fleet-pipeline-design.md)과 [구현 계획](../plans/2026-10-12-discord-fleet-pipeline.md)을 따른다. 아직 없는 Bot/실행 경로를 활성화된 기능으로 읽지 않는다.

1. 팀 관리자의 Discord 계정에서 지정 팀 서버/텍스트 채널을 확인한다. 이미 준비한 채널을 사용하며 없는 경우에만 새로 만든다. 담당 팀원이 채널을 볼 수 있도록 권한을 지정한다. Webhook 관리는 관리자가 담당한다.
2. 채널 설정 → 연동 → Webhook에서 Fleet용 incoming webhook을 만든다. URL은 비공개 현장 환경의 `ROSY_DISCORD_WEBHOOK`에만 넣고 채팅·문서·git에 적지 않는다. Discord의 공식 [webhook 설정 안내](https://support.discord.com/hc/en-us/articles/228383668-Intro-to-Webhooks)를 따른다.
3. [설정 예시](../../deploy/site/notifications.example.yaml)를 비공개 설정으로 복사하고 `console_url`을 팀원에게 실제로 열리는 인증된 HTTPS Console로 지정한다. 기존 Fleet 실행 명령에 `--notifications-config <비공개 YAML 경로>`를 추가하며 기존 `--tasks-db`, 로스터, 인증 설정을 유지한다. 이 옵션이 없으면 외부 전송은 꺼져 있다. 모델 PC provider 프로세스가 webhook을 소유하거나 목적지를 결정하지 않는다.
4. 최초 연결은 별도 실제 발송 수용으로 기록한다. 열린 Pinky 사건의 알림 수신 시각/메시지 ID, Console 링크의 로그인과 사건 일치, 이름 있는 담당자의 ‘이 사건 맡기’, `/api/fleet/incidents?robot_id=<id>&stuck_id=<id>`의 인수 readback, 현장 재관측 결과와 종료 통지를 순서대로 확인한다. GET 링크만 열어서 담당자가 되지 않는다. 알림이 제공자에게 수락됐다는 기록은 실제 수신·담당 인수·해소를 대신하지 않는다.
5. 429/연결 전 실패는 제한 재시도하고 timeout/5xx/중간 취소 등 전송 불명은 UNKNOWN으로 남는다. Console에서 실패/불명을 확인한다. 물리 메시지 중복 가능성을 확인하지 않고 UNKNOWN을 맹목 재전송하지 않는다. 닫히거나 다른 담당자가 맡은 사건의 오래된 개입 요청은 취소된다. 정상 비개입은 새 알림을 만들지 않는다.

비공개 수용 기록에 서버·채널 관리자와 실제 담당자, 실행 SHA/설정 식별, 시각·전송→수신→로그인→인수→현장 결과→종료 readback을 남긴다. 공개 기록에는 secret이나 설치 주소를 제외한 receipt 식별/hash와 각 확인 상태만 둔다. 판단 정확도/지연 한계 및 독립 정답은 팀 검수 뒤 확정한다. 채팅 문장·이모지로 장치 명령이나 E-stop 해제를 받지 않는다.

인수 전에는 기존 `--users-file`의 기명 operator 인증과 `--tasks-db` 감사 원장을 준비한다. 비밀번호 로그인 계정은 [기존 API 인증 계약](ROSY%20API%20%26%20Protocol%20Reference.md)을 따른다. 공용 `site-console` 인증은 이름 있는 사건 인수로 기록할 수 없다. `/api/fleet/session`의 principal/role과 실제 인수 원장의 principal이 일치하는지 확인한다.

Discord는 [execute webhook](https://docs.discord.com/developers/resources/webhook#execute-webhook)의 `wait=true` 응답과 메시지 ID를 확인한다. Slack/Telegram adapter의 소스·가짜 전송 계약도 함께 제공하되 이번 실제 수신 채널은 Discord다. 공식 규약 조회: 2026-10-11.
