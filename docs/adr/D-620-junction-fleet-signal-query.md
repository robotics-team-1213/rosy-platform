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

### Execution record — 2026-10-10

- 사용자의 “좋아” 승인으로 `fix/junction-device` 브랜치 push, native ARM64 payload
  전체 빌드·서명, Fleet 이미지 빌드, `9dfk`와 `8kcn` 설치 및 현장 감독 시험을 진행한다.
  이 승인은 main 착지나 자동 배포 게시를 포함하지 않는다.
- 로봇 payload와 Fleet 이미지는 병렬로 준비할 수 있다. 두 구성 요소의 설치 revision,
  인증된 Fleet 연결과 신호 응답을 확인한 뒤 `junction_signal_enabled`를 활성화한다.
  기존 CORE 주행·횡단보도·E-Stop 게이트는 유지한다.
- **SOURCE:** 승인 시점 설치 후보는 `fix/junction-device`의 `f7dfa282a`다.
  D-620 구현과 기존 v2 모델 floor gate 및 CORE 몸체 자기 반사 보정을 포함한다.
- **원격 시험:** 후보 코드 `e83d3038f9`에서 432 passed, 2 skipped, 0 NEW;
  계약 코드 `d7f032f513`에서 1095 passed, 0 NEW다. 두 skip은 선택 의존성 시험이며
  이 결과는 ARM64 추론이나 실물 이동 증거를 대신하지 않는다.
- **ARTIFACT:** 이 기록 시점 새 ARM64 서명 payload와 Fleet 이미지 빌드는 미확인이다.
- **DEVICE:** 이 기록 시점 두 로봇의 새 payload 설치, Fleet 이미지 적용과 신호 readback은
  미확인이다. 빌드 성공만으로 설치 완료를 판정하지 않는다.
- **FIELD:** 이 기록 시점 적색 대기→녹색 출발, 완전 무응답 3초→우측 진입 및
  횡단보도 연속 clear 3초 후 통과는 실물 미확인이다. 요청 ID·신호 상태·CORE journal과
  MCAP의 `/cmd_vel`·오돔을 함께 기록하며, `entered` 로그만으로 합격을 선언하지 않는다.

- **병렬 준비 후 추가 검증:** 최신 `origin/main`의 `6512cb70fa67` 위에 배포 후보를
  재정렬했다. push 전 검사가 드러낸 크기 경계는 기존 계획대로 Fleet 신호 메서드와
  heartbeat 루프를 분리해 해결했고, API v1.202 고정값과 로그 이름을 함께 정렬했다.
  `4bb0177350`의 관련 원격 회귀 시험은 **248 passed, 0 NEW**다
  (`junction-boundary-verify/run-1.txt`). 전체 push 게이트와 빌드·설치·FIELD는 별도 확인한다.
- **추가 승인:** 사용자의 “빌드 머지 배포” 요청으로 main 착지와 배포를 진행한다.
  병렬로 착지한 D-619가 API v1.202를 사용하므로 양쪽 계약을 보존하고 D-620은
  v1.203으로 정렬한다. 이전 SHA의 시험을 새 병합 후보의 수용 증거로 대체하지 않는다.
