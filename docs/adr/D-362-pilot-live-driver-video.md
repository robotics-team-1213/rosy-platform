## D-362 운전 중인 한 사람에게만 인증된 MJPEG 실시간 영상을 주고, 그동안만 로봇 미리보기 발행을 올린다

**Status:** Accepted (2026-09-29, 설계 결정). 구현·장치 수용은 아래 Validation 게이트로 따로 닫는다.
D-323 §5 의 "새 영상 전송 경로를 열지 않는다"를 이 범위에서만 바꾼다. D-332 결정 1(카메라 폴링
150ms)을 대체한다 — CORE 계약(`vision.preview_min_pull_interval_s ≥ 0.4`)과 충돌해 429 만 늘렸다.

### Context

2026-09-29 실물 로봇(rosy-pinky-8kcn) 태블릿 실주행 영상에서 명령 경로는 빠르다(놓음→0 명령
23~56ms, 명령→움직임 150~400ms). 체감 지연의 주원인은 영상이다.

- 로봇 `road_observer_node` 가 카메라(320×240, 차선 인식용)에서 미리보기를 **2 fps** 로만
  발행한다(`dashboard_preview_fps: 2.0`, 관측 전용·DDS 대역폭 보호).
- CORE 는 인증 뷰어마다 프레임 당김을 **0.4 s** 에 한 번으로 묶는다(429).
- 그래서 pilot 은 초당 2~2.5 장, 지연 0.2~0.5 s 영상으로 운전한다. 게임식 조작감이 불가능하다.

### Decision

1. **스트림 라우트** `GET /api/v1/vision/front/stream` 을 CORE 에 둔다. `multipart/x-mixed-replace`
   JPEG 이고, 최신 프레임 저장소(`core_features/vision/store.py`)에 새 시퀀스가 들어올 때만
   내보낸다. 새 코덱·새 프로세스·새 의존성이 없다.
2. **받을 수 있는 사람은 운전석 보유자 한 명이다**(D-343). 운전석이 없거나 다른 사람이면 409.
   관전자와 관제 화면은 지금의 0.4 s 폴링을 그대로 쓴다. 스트림은 한 번에 하나만 열린다.
3. **인증은 헤더로만** 한다. 브라우저 `<img>` 는 헤더를 못 보내므로 pilot 은 `fetch()` 스트림을
   잘라 `createImageBitmap` 으로 캔버스에 그린다. 토큰을 URL 에 넣지 않는다(D-193).
4. **발행 주기는 요청이 있을 때만 올린다.** CORE 가 스트림을 여는 동안 로봇 관측 노드에
   "운전 미리보기"를 요청하고(기본 12 fps, 상한 15), 닫히면 2 fps 로 돌아간다. 차선 인식
   입력(해상도·주기)은 바꾸지 않는다 — 미리보기 인코딩만 늘어난다.
5. **끊기면 폴링으로 자동 복귀**하고, HUD 는 영상 나이(ms)와 fps 를 보인다. 영상이 1 s 이상
   멈추면 HUD 가 경고색으로 바뀐다(운전자는 멈춘 화면을 믿고 달리면 안 된다).
6. pilot `vision.js` 의 폴링 주기는 CORE 하한 이상(420 ms)으로 고정한다(이미 구현).

### Alternatives

- **폴링 하한을 낮춘다.** 거부. 모든 뷰어의 부하가 같이 늘고, 요청마다 헤더·TLS·JSON 왕복이 든다.
- **WebRTC.** 후속. 30 fps·100 ms 미만이 가능하지만 aiortc/GStreamer·시그널링·이미지 크기가
  늘어난다. MJPEG 로 부족하다는 실측이 나오면 연다.
- **카메라 해상도를 올린다.** 보류. 차선 인식 파이프라인(호모그래피 프로필이 320×240 기준)과
  얽혀 있다. 별도 결정으로 다룬다.

### Consequences

- 운전석 보유자의 영상이 2 fps → 12 fps 로 오른다. 로봇 CPU 는 JPEG 인코딩만큼 늘어난다
  (320×240, q72 기준 프레임당 수 ms).
- CORE 는 스트리밍 응답을 처음 갖는다. uvicorn 워커 하나를 오래 붙잡으므로 동시 1 개로 막는다.

### Validation

- SOURCE: 스트림 라우트 시험(운전석 없음 409, 인증 없음 401, 새 시퀀스만 전송, 한 번에 하나).
- ROS-SIM: 가제보에서 스트림 fps·지연 측정.
- DEVICE: 실물 로봇 태블릿 녹화에서 영상 fps ≥ 10, 명령→화면 반영 지연 측정값을 기록한다.

**Related:** [D-193](D-193-login-code-and-credential-lifecycle.md), [D-275](D-275-web-surface-and-video-runtime-ownership.md),
[D-323](D-323-rosy-pilot-teleop-app.md), [D-332](D-332-pilot-response-speed.md), [D-343](D-343-pilot-rooms-and-driver-seat.md).
