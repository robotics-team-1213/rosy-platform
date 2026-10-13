# D-675 — Discord Gateway 수신과 기존 Fleet lifecycle

**Date:** 2026-10-12
**Status:** Accepted (source only)

## Context

D-671 기명 접수는 source에 있으며 Bot 초대와 토큰 REST 인증은 완료했다. 지속 수신 경로가 없어 Bot은 아직 offline이다. 사용자 요청에 따라 기존 Fleet 프로세스에서 수신을 연결한다.

## Decision

`integrations/messaging/discord/rosy_discord/gateway.py`는 Discord 연결·identity 확인·heartbeat·resume만 소유한다. Fleet의 기존 lifespan이 선택적 worker를 시작하고 종료한다. 별도 서비스·wheel·provider를 만들지 않는다. operations의 integration allowlist에 messaging을 추가하며 middleware에는 허용하지 않는다.

private intake 설정의 `bot_token_file`이 없으면 수신은 OFF다. 토큰 파일은 이미지·wheel·로그·API에 넣지 않으며 기존 자격과 분리한다. Guilds와 GuildMessages intent만 사용하고 Bot을 명시적으로 mention한 등록 operator의 지정 채널 메시지만 기존 접수 원장에 넣는다. 원장 commit 후 resume sequence를 전진한다. 일시적 저장 실패는 resume으로 재전달받고 영구적인 범위·권한 거절은 작업을 생성하지 않는다.

프로세스 시작 전과 resume 불가능한 연결 공백의 메시지는 자동 복구하지 않는다. 저장 실패가 미해결인 채 session이 무효화되면 worker는 멈추며 수동 재확인이 필요하다. 접수는 REQUESTED이며 승인·실행·성공이 아니다. CORE/OMX writer, Task/Mission/Job/claim, provider 활성화는 이 변경에 포함하지 않는다.

## Verification

실제 원격 RED는 gateway 모듈 누락을 확인했다. handshake/identity/scope, 저장 실패 sequence, heartbeat ACK, lifespan 종료와 기본 OFF, wheel/sdist/source image closure 및 영향 회귀 시험 후 source 인수를 판단한다. 실제 이미지·현장 READY·사용자 메시지→원장→Console readback은 별도 증거다.

Protocol reference: [Discord Gateway](https://docs.discord.com/developers/events/gateway).

Source 인수: 독립 검토2241b7b6b 승인, 최신27fc0de96 원격83 PASS/NEW0(수신·자격·구조·wheel/sdist 설치). 전체 main 착지와 실제 이미지/현장 수용은 별도다.

배포 caller closure: 기존 signed Compose는 Fleet-only private directory를 읽는다. 상호 배제 CLI `--discord-intake-config-optional`은 파일이 없을 때만 OFF이며 잘못된 파일/권한은 fail closed다. 독립 검토b78edf399 승인, 원격138 PASS/NEW0(CLI·수신·compose·설치·구조). Fleet53617은 기존53606+150 내이며 app906과 모든 기존 한도를 유지한다. unsigned 운영 교체나 push 승인은 이 ADR에 포함되지 않는다.
