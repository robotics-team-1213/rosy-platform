# 관제 AI 현장 사전 점검 — 2026-10-21

[소스 착지 검증](../operator-ai-landing-2026-10-20/result.md)의 후속이다. 이번에는 실제 현장 상태와 Discord 진단 송신을 확인했다. 운영 AI 배포·사람의 대화 수신·음성·장치 수용 완료 기록은 아니다.

## 실행 범위와 관측

점검 소스 기준 commit은 `c42fa0260f1fdc1e9e602294c9e4d30feb99f8b4`다. 기존 gitignored 호스트 등록과 고정 SSH host key를 사용했다. 로컬 main의 미게시 변경이나 다른 세션의 `aff1.log`는 게시·수정하지 않았다.

| 확인 | 관측 | 판정 범위 |
|---|---|---|
| 현장 Docker readback | Fleet·Vision·프록시 healthy, 약 13시간 실행 중. site autoupdate timer active | 서비스 생존 확인이며 새 관제 AI 배포 확인이 아님 |
| Fleet 이미지 | 참조 `rosy-site-fleet:cadbfde749be868239f4cd1899c7ad5a2414cf29`, image ID `sha256:487d95c1c979badd99b04e090a183a87696c6a2bb6a2274f23726fcf10c65ffe` | revision/source label 없음. 태그를 모든 실행 바이트의 검증으로 확대하지 않음 |
| operator 설정 | 컨테이너의 `/run/rosy-deliberation/operator.json` 없음 | 현재 operator 기능 미설정. 호스트 원본 상태까지 증명하지 않음 |
| 관리자 설치 접근 | 호스트 `sudo -n` 요청은 interactive authentication required로 거절 | 보호 설치 미실행. 별도 root 경로·컨테이너로 우회하지 않음 |
| 공개 소스 | GitHub main의 `deploy/site/install_operator_broker.py` contents 조회 404 | 관제 AI 소스 게시·검토·동일 SHA CI/서명 후보가 선행 필요 |
| 기존 Discord | intake 설정 존재, replies_enabled=true, Bot 인증·등록 Bot ID·채널 guild 일치 | 토큰·주소·계정·채널 ID는 출력/공개 기록에 포함하지 않음 |
| 실제 Discord 송신·조회 | 진단 메시지 1개 POST 성공, 그 ID의 GET과 내용·author 일치 | Bot REST 송신/조회 확인. Gateway의 사람 MESSAGE_CREATE·AI 답변·작업 결과 통지는 NOT RUN |
| 로그 표본 | 최근 24시간 내 마지막 최대 5,000줄에서 Discord READY·Discord error 문자열 각 0 | 표본 부재는 연결 성공/실패를 판정하지 못함 |

진단 메시지는 한국어·영어로 연결 점검 목적과 장치 작업을 요청하지 않는다는 내용을 표시했다. `allowed_mentions.parse=[]`로 알림 멘션을 끄고 nonce 중복 보호를 사용했다. 봇 자신이 보낸 글을 사람의 명령으로 위장하지 않았다. 삭제·설정 변경·서비스 재시작·Task 요청·장치 명령은 하지 않았다. 메시지 내용과 ID의 SHA-256만 아래에 보존한다.

```json
{
  "observed_at": "2026-10-20T17:03:35.013029+00:00",
  "bot_identity_verified": true,
  "channel_guild_verified": true,
  "diagnostic_message_posted": true,
  "same_message_readback": true,
  "message_id_sha256": "d5eaf1eb41c6388cc97ddb5beb6f3265dceba9163930aa99d6aa634ae936deb7",
  "content_sha256": "328b539463d4913b4ce7bcf4a1ae7dba31b837d1e747916749a31729e2cd9878",
  "operator_config_present": false,
  "gateway_user_ingress_verified": false,
  "robot_task_requested": false
}
```

위 UTC 시각은 한국 시각 2026-10-21 02:03이다. 단발 점검 원본은 `$TEMP/operator-ai/live_acceptance_probe.py`이며 SHA-256은 `f0e6671d55ffb3ca41c2a4fbf4da7b1e546845040b0f0388e9acaa63feb47c9c`다. 이 스크립트는 POST를 포함하므로 자동 재실행하지 않는다. 응답 검증 assert로 등록 신원과 같은 메시지의 원문 일치를 확인했다. 진단 실패를 이유로 메시지를 자동 재전송하지 않는다.

## 남은 실행

[운영 수용 실행표](../../plans/2026-10-21-operator-ai-field-acceptance.md)에 게시·보호 설치·조회 전용 배포·언어별 20개 실제 발화·기명 Discord 왕복·명시적 이동·취소/단절/재시작·rollback의 실행 위치와 판정 기준을 연결했다. 전처리/명령 후보/토큰 절감은 코드 대조 후 별도 검토안으로 기록했으며 구현된 기능으로 표시하지 않는다.

실제 보호 설치는 관리자 실행 환경이 필요하다. 실제 발화는 관제 PC의 마이크와 운영자, 실제 이동은 현장 감독·현재 장치 수용 조건이 필요하다. 이번 결과로 ARTIFACT/DEVICE/FIELD gate를 올리지 않는다. 기존 종료 오류 두 건도 원인 미확정이다.
