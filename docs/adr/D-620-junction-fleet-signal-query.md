## D-620 교차로 진입 전 Fleet 신호 질의와 3초 무응답 우측 진입

**Status:** Accepted (2026-10-10, 사용자 결정; SOURCE·원격 시험·ARTIFACT·DEVICE·FIELD 별도)

### Context

사용자는 차선추종 시험에서 교차로 진입 전에 Fleet에 신호를 묻고, 답이 없으면
3초 뒤 우측으로 진입하며, 답이 있으면 그 신호를 기다려 움직이도록 요청했다.
기존 D-494/D-495 게이트는 교차로를 발견하면 정지하고 측정된 오돔 기반 회전을 수행한다.
Fleet에는 D-525 신호표와 D-536/D-593 지도 자세가 이미 있다.

### Decision

1. `line_follow.junction_signal_enabled` 기본값은 `false`다. 명시적으로 켠
   CAMERA_LINE 시험의 **지시 없는 교차로**에만 적용한다. 기존 trip 지시의 주인은
   Fleet으로 유지한다. IR_LINE, OFF, teleop에는 적용하지 않는다.
2. 로봇은 교차로 게이트에서 정지한 에피소드마다 UUID 요청 ID를 하나 만들고,
   기존 인증된 `/ws/robots` API의 1Hz heartbeat `junction_signal_request`로 신호를 묻는다.
   HELLO로 바인딩된 로봇 신원만 조회하며 다른 로봇 신원을 지정할 수 없다.
3. Fleet는 같은 heartbeat의 `junction_signal`로
   `{request_id, lamp:green|red|unknown, may_enter:boolean, reason}`을 답한다.
   trip의 신호·통행권이 있으면 그것을 쓴다. 독립 차선추종은 2초 이내 지도 자세,
   진행 방향의 차로 안, 다음 장소까지 0.6m 이내일 때 해당 접근로의 기존 신호표를 쓴다.
   지도·신호 연결이 없거나 신호표 오류·타 차량의 점유가 있으면 진입을 허용하지 않는다.
4. 답이 한 번도 없는 정지 에피소드가 **3초** 경과하면 D-495의 `right`,
   `turn_deg:-90`, 기본 전진 거리 0.10m를 한 번 선택한다.
   `green && may_enter:true`인 2초 이내 응답도 같은 우측 회전 경로를 선택한다.
   적색·미확인·진입 불허·만료 응답은 계속 기다린다. 응답 만료는 무응답으로 바뀌지 않는다.
5. 실제 회전을 시작하기 전 새 적색 응답이 오면 선택한 fallback도 취소하고 대기한다.
   이전 요청 ID, OFF 뒤 답, 이미 시작한 회전에 대한 뒤늦은 답은 다음 회전을 만들지 않는다.
   잘못된 상관 응답, Fleet ERROR, pairing 거부는 `unknown` 대기다.
   카메라 공백은 같은 정지 에피소드의 응답과 3초 시계를 지우지 않는다.
6. 모든 실제 바퀴 판단은 기존 CORE tick에 남는다. 정지 오돔·회전 근거·IR·몸체
   sweep·통행권 만료·횡단보도·watchdog·E-Stop을 그대로 확인한다.
   이 응답은 D-517 통행권을 만들거나 늘리지 않는다. Fleet와 연결되지 않은 fallback은
   공동 교차로 우선권을 보장하지 않으므로 현장 감독이 있는 시험에 한정한다.
7. `line_follow.junction.signal_request_id`와 `signal_state`를 상태 API에 추가하고
   CORE journal에 질의·답변 변화·fallback 선택을 기록한다. 로그의 `entered`는 CORE가
   회전 단계를 시작한 상태이며 실제 이동 증거는 MCAP의 `/cmd_vel`·오돔으로 따로 확인한다.

### Consequences

- 새로운 REST 자격 증명이나 별도 네트워크 worker 없이 기존 Fleet 링크를 재사용한다.
- 이전 Fleet가 신호 필드를 답하지 않는 경우는 무응답이다. 기능을 켜기 전에 양쪽
  설치 revision과 설정을 확인한다. 기본 꺼짐으로 기존 장치 동작을 유지한다.
- 우측은 현재 90도 회전이다. 비직각 교차로와 무감독 다중 로봇 운행은 현장 수용 대상이 아니다.
- 새 런타임 파일은 verbatim 수정만 가능한 D-553 delta 대상이 아니다.
  native ARM64 payload 전체 빌드·서명과 Fleet 이미지 빌드를 거쳐 설치한다.

### Verification

- CORE 실제 manager를 사용한 결정적 오돔 시험: 3초 경계, 적색/미확인 유지,
  녹색 전환, 늦은 적색, 잘못된/이전 ID, pairing 거부, 카메라 공백, 중복 회전 금지,
  회전 근거 없을 때 정지, OFF, 실제 FleetAgent heartbeat 송수신.
- Fleet 실제 hub/신호표 시험: paired 신원, 조회 오류의 unknown 응답,
  자유/점유 구역, 신선한 지도 자세와 오래된 자세.
- 기존 교차로·Fleet 링크·API·횡단보도 회귀 시험. 실물 통과 판정은 별도다.
