# Discord 회신 transport와 접수 원장 검증

Branch: `feat/discord-workflow`. Source: `4bb95bc516` (후속 `096098416`은 style 정리).

원격 fake 시험 67건 통과, exit 0, known_failures NEW 0. 관련 경로는 `test_channel_replies.py`, `test_channel_requests.py`, `test_discord_gateway.py`, `test_discord_replies.py`다. 로그는 X의 기존 discord-fleet-pipeline 세션 `logs/reply-worker-green/run-1.txt`에 있다. 실행기는 D-568 자원 부족 fallback으로 원격 Model PC를 선택했으며 자원 floor 통과 증거로 집계하지 않는다.

접수와 접수 회신 intent를 같은 tasks DB transaction으로 기록한다. 중복 접수는 회신을 새로 만들지 않는다. 전송 중 재시작은 UNKNOWN, claim attempt는 fence, 명확한 RETRY는 3회/600초로 제한한다. 전송 직전 계정 권한·고정 목적지 revision·기한을 확인한다. 취소는 UNKNOWN을 기록하고 CancelledError를 전파한다. 기본 replies_enabled=false이며 Bot 자격 없이 활성화를 거절한다.

transport는 고정 채널과 원래 message reference에만 POST하고 mentions를 차단한다. 다른 채널·Bot·원문 reference의 응답은 provider 수락 증거가 아니다. HTTP 응답은 16KiB로 제한한다. timeout/5xx는 UNKNOWN이고 미접속·429만 RETRY다. nonce는 보조 중복 제한이며 durable journal을 대체하지 않는다. [Discord 공식 message 계약](https://docs.discord.com/developers/resources/message#create-message)을 구현 시 확인했다.

RED는 모듈 누락과 worker/opt-in 미구현 4건을 원격에서 재현했다. GREEN에서 모두 해소했으며 known_failures 목록을 바꾸지 않았다. 변경 파일 flake8 0 errors.

이는 source/fake 범위다. 실제 reply worker lifecycle의 전송·Console 작업 연결·작업 결과 회신·위험 사건 어댑터·설치 closure·크기/독립 검토·latest-main 착지·CI·서명 배포·실제 Discord readback은 아직 남아 있다. 운영 채널에 이번 코드로 메시지를 보내지 않았으며 장치 명령도 없다.
