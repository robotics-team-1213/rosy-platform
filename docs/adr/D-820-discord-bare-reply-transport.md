## D-820 Discord 알림과 답글 전송의 공통 소유권

**Status:** Proposed

### Context

Fleet의 `channel/health/discord.py`는 bare 알림을 보내고 integrations의 `DiscordReplies.send`는 message_reference가 필요한 답글을 보낸다. 동일한 호출로 치환하면 payload 의미가 바뀐다.

### Alternatives

1. integrations에 bare·reply의 공통 bounded HTTP 전송을 두고 Fleet에는 durable delivery 결정을 남긴다.
2. 현재 두 payload 구현을 유지하고 snowflake·응답 제한·재시도·UNKNOWN 분류의 대조 시험을 둔다.

### Decision

선택은 보류한다. Accepted가 되면 별도 실행 계획을 작성한다. 이 제안은 소스 이동·새 실행 권한·배포 승인이 아니다.

### Consequences

공통화는 사본을 줄이지만 배포 의존과 실패 범위를 함께 바꾼다. 현 구조 유지는 설치 경계를 보존하지만 사본의 동등성을 계속 검증해야 한다.

승인 전 확인: 알림에는 reply reference를 추가하지 않고 답글의 message_id·channel·author 결속과 allowed_mentions 제한을 보존한다.
