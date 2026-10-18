# Media work log

## 2026-10-17 · 683d93218b · D-789 media authority source slice

- 변경: 로봇별 서명 위임·원본 CORE 재검사, 첫 구독 intent·활성 lease, 느린 뷰어 분리, 감독 프로세스와 HTTP callback을 추가했다. Fleet·명령 경로와 분리한다.
- 증거: AI PC에서 media unit/HTTP/supervisor 13 passed. 원본은 `C:/DevTemp/webrtc-implementation/media-server-green/run-1.txt`다. 실제 MediaMTX kick·ARM64·장치·현장 수용은 후속이다.
- gate 변화: 없음. SOURCE부터 FIELD까지 통합 미확인 항목을 HOLD로 기록한다.

## 2026-10-18 · 2190ba6889 · D-789 production kick binding and default-on deployment

- 변경: `rosy_media.main`이 CORE 재검사(고정 HTTPS origin)와 `MediaMTXClient.kick`을 한 권한 서비스로 묶고, `rosy_media.supervisor` CLI가 권한 서비스와 MediaMTX를 자식으로 감독한다. 사이트 배포는 Fleet과 별도인 `deploy/site/compose.media.yaml`이다.
- 증거: media 시험 25 passed(c94df2d713, AI PC). 2190ba6889 AI PC에서 실제 WHIP/MediaMTX/WHEP Chromium 재생과 CORE 철회 시 실제 세션 제거 2 passed.
- gate 변화: SOURCE·LOCAL HOLD→GO. ARTIFACT·DEVICE·FIELD는 measurement skipped by user decision 2026-10-18로 HOLD.

## 2026-10-18 · uncommitted · D-801 관제 콘솔 로봇 영상(사이트 발급 읽기 위임)

- 변경: 권한 서비스가 사이트 키로 서명된 READ 위임을 받고, 재확인에서 Fleet 응답과 로봇 CORE 영상 설정(503=거부)을 함께 요구한다.
- 증거: 원격 시험 결과는 착지 기록에 남긴다. 장치·현장 측정은 2026-10-18 사용자 결정으로 생략했다.
- gate 변화: 없음. 모자이크(MCU)는 후속 feat/site-video-mosaic이다.
