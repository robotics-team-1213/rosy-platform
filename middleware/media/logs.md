# Robot media work log

## 2026-10-17 · uncommitted · D-791 선택 설치 미디어 발행자 분리

- 변경: 이번 작업이 추가한 H.264/WHIP·watermark 구현과 관련 시험을 독립 `rosy-media-edge` wheel로 옮긴다. 기존 perception의 크기 ratchet을 올리지 않고, 기존 카메라 생산자는 그대로 둔다.
- 증거: 원래 위치에서 WHIP/watermark 13 passed, 실제 Chromium 합성 loopback 1 passed. 이동 뒤 같은 회귀를 재실행한다.
- gate 변화: 없음. native ARM64·카메라 IPC·장치·현장 수용은 HOLD다.

## 2026-10-18 · 2190ba6889 · D-789 camera tap, WHIP worker and native unit

- 변경: `camera_tap`이 단일 카메라 소유자의 Picamera2를 640×480 main(미디어)·기존 크기 lores(인식)로 한 번 구성하고 우편함에 쓴다. 업스케일은 거절한다. `worker`가 viewer demand가 있을 때만 WHIP로 발행하고 grant·세션을 20초마다 갱신하며 실패 시 5초 상한 backoff로 재시작한다. `rosy-media.service`(MemoryMax=256M, CPUQuota=100%)를 payload에 넣었다.
- 증거: middleware/media/test 통과(327f750d8a), 실제 loopback 2190ba6889 AI PC 통과. 실물 카메라·ARM64는 확인 못 함.
- gate 변화: SOURCE·LOCAL HOLD→GO. ARTIFACT·DEVICE·FIELD는 measurement skipped by user decision 2026-10-18로 HOLD.
