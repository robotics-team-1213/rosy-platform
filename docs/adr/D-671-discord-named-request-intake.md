# D-671 — Discord 기명 요청 접수와 Fleet 소유 경계

**Date:** 2026-10-12
**Status:** Accepted (source only)

## Context

D-669의 전체 대화 실행 경로는 Proposed다. 사용자는 기명 Console 계정을 준비하고 대화 작업 요청 연동의 계속 진행을 요청했다. 우선 접수와 실행을 분리해 실제 요청을 Console에서 확인할 수 있어야 한다.

## Decision

Fleet은 기존 tasks SQLite DB에 별도 `fleet_channel_requests` 접수 표를 둔다. 이 표는 Task/Mission/Job/claim이 아니며 접수가 승인·실행·성공을 뜻하지 않는다. 새 상태는 `REQUESTED` 하나다. Console은 현재 등록된 operator 자신의 요청만 읽는다. 다른 역할·development·공용 Console 자격은 접수 조회 권한을 받지 않는다.

Discord transport holder는 `integrations/messaging/discord/rosy_discord`다. Fleet 배포물에 함께 설치하며 별도 서비스나 wheel을 만들지 않는다. Fleet은 private 설정의 guild/channel/Bot ID와 Discord immutable user ID → 현재 operator principal 연결을 소유한다. transport는 전용 HMAC 자격으로 timestamp와 원문 envelope를 인증한다. Bot/webhook/DM/다른 채널/비등록 사용자/명시적 Bot mention 없는 메시지는 거절한다. caller principal과 operator bearer는 받지 않는다.

guild/channel/message ID를 원장 키로 쓰고 원문·작성자·mention 등 전체 envelope hash를 보존한다. 같은 내용 재전송은 같은 접수 결과를 읽는다. 수정된 내용은 409이며 권한 철회는 재전송에도 적용한다. 원장은 최대 1000건에서 fail closed 하고 원문을 자동 삭제하지 않는다. 메시지 2000자·body 8192 bytes·60초 인증 시간창·조회 50건으로 제한한다.

이번 source는 순수 메시지 projection/signature adapter와 Fleet 접수 API만 제공한다. Gateway 실행기·Bot token·수신 활성화는 후속이며 기본 Fleet 실행은 설정 없으면 경로를 열지 않는다. transport key는 Fleet의 다른 알려진 자격과 겹치면 시작을 거절한다. TLS 검증을 끄지 않는다. Console 원문은 textContent로 표시한다.

## Consequences and gates

API Reference와 protocol DTO, CLI 설정, source mapping, wheel/sdist/source image, 인증·재시작·중복·수정·격리 시험을 같이 변경한다. 이 ADR은 source 구현만 수용한다. Bot token 주입·런타임 수신 활성화·실제 대화 receipt는 별도 증거로 기록한다.

D-669 후보 생성/승인/위험 조치/reply, D-640 provider 및 FIELD는 그대로 후속이다. 새 접수 경로는 모델 호출, `/do`, dispatcher, 장치 writer, stop/rearm을 호출하지 않는다. CORE와 OMX의 최종 권한 및 일반 Mission/Cell Job의 기존 승인 계약은 유지한다.
