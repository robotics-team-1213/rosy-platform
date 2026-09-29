## D-348 Pilot 은 로봇이 찾아 준 이웃 목록으로 방(로비)을 보이고, 로봇 한 대에는 운전석 하나만 둔다

**Status:** Accepted (2026-09-29, 설계 결정). 구현·장치 수용은 Validation 게이트로 따로 닫는다.
D-340 의 셸 조건 2(mDNS 로봇 탐색)가 실제 요구로 기록되었다 — 셸 착수는 D-340 이 정한 CORS·토큰
결정을 따로 거친다. 이 ADR 은 셸 없이 PWA 로도 동작하는 부분을 정한다.

### Context

- 운전자는 로봇 주소를 몰라도 로봇을 골라 들어가야 한다. 로봇은 이미 `_rosy._tcp` 를 광고하고
  (현장 LAN 발견 규칙 v0.1), 2026-09-29 PC 에서 `rosy-pinky-8kcn.local` 로 찾아졌다.
- 브라우저(PWA)는 mDNS 를 탐색할 수 없다.
- 태블릿 실측에서 pilot 탭 52 개가 한 로봇을 동시에 폴링했고 그중 하나가 MANUAL 로 들어가 있었다.
  CORE 는 teleop 을 보내는 클라이언트를 구분하지 않는다 — 두 화면이 한 로봇을 동시에 조종할 수 있다.
- 오늘 pilot 에 로그인 코드 페어링(`POST /api/v1/auth/pair`)을 붙였고 태블릿에서 동작했다.

### Decision

1. **방 = 기기 하나.** 방 카드는 이름·종류·release(TXT 공개 정보), 온라인, 배터리·모드 요약,
   운전석 상태를 보인다.
2. **이웃은 로봇이 찾아 준다.** CORE 가 Avahi 로 `_rosy._tcp` 를 탐색해
   `GET /api/v1/site/rooms` 로 돌려준다. 규칙 v0.1 의 검사(필수 TXT, `.local` 호스트명, 사설
   IPv4, 포트 형식)를 통과한 광고만 넣고 **TXT 공개 정보만** 싣는다. 토큰·신원 증명은 아니다.
   → 어느 로봇에 붙어도 같은 로비가 보인다. 현장 Fleet 이 있으면 그 발견 결과를 합친다.
3. **입장은 그 기기의 origin 으로 이동**한다: `http://<hostname>.local:8080/pilot/#join`.
   CORS 를 열지 않는다(D-323 same-origin 유지). 인증은 기기마다 로그인 코드 페어링으로 한다.
4. **기억된 방은 호스트·이름만** 저장한다. 토큰은 영구 저장하지 않는다(D-193) — 이전 "최근 접속"이
   토큰을 localStorage 에 평문으로 남기던 것을 2026-09-29 에 걷어냈다.
5. **운전석(seat).** `POST /api/v1/teleop/seat {client_id}` 가 임대를 준다. teleop 이 임대를 연장하고
   2 s 동안 teleop 이 없으면 풀린다. 다른 클라이언트의 teleop 은 `409 SEAT_TAKEN`. 좌석 보유자는
   `DELETE` 로 내려놓는다. 비상 정지는 좌석과 무관하게 누구나 한다. 다른 사람이 운전 중이면
   "관전"(영상 폴링·상태)과 "양보 요청"만 할 수 있다.
6. **운영 경로는 로봇이 pilot 을 서빙**하는 것이다. PC 중계(`tools/pilot_device_bridge.py`)는 이미지에
   pilot 이 없는 동안의 개발 도구로만 쓴다.

### Alternatives

- **셸 앱에서 NsdManager 로 직접 탐색.** D-340 셸이 생기면 추가 출처로 쓴다. 셸 없이도 로비가
  동작해야 하므로 로봇 쪽 탐색을 먼저 한다.
- **CORS 를 열어 한 origin 에서 여러 로봇을 조종.** 거부. D-323·D-275 의 same-origin 전제를 깨고
  토큰이 여러 로봇에 섞인다.

### Consequences

- CORE 에 Avahi 탐색 의존이 생긴다(이미 fleet_agent 가 쓰는 도구). 탐색 실패는 빈 목록이지 오류가 아니다.
- 좌석은 SAF 요구(한 로봇 한 조종자)를 새로 만든다. API Ref·SRS 추적을 같이 갱신한다.

### Validation

- SOURCE: Avahi 출력 파서 시험(규칙 v0.1 거부 사례), 좌석 임대·만료·409 시험, pilot 로비 브라우저 시험.
- DEVICE: 로봇 두 대(또는 로봇+시뮬)에서 태블릿 로비 → 입장 → 좌석 → 다른 태블릿 409 를 녹화한다.

**Related:** [D-193](D-193-login-code-and-credential-lifecycle.md), [D-275](D-275-web-surface-and-video-runtime-ownership.md),
[D-323](D-323-rosy-pilot-teleop-app.md), [D-340](D-340-app-shell-wraps-web-surfaces.md), [D-346](D-346-pilot-live-driver-video.md).
