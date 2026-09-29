## D-337 로봇의 제2 신호 소스는 관측 서비스의 실측뿐이다

**Status:** Accepted (2026-09-29). 경계와 융합 규칙의 결정만. 관측 폴러 구현(T2 이후),
ROS-SIM·DEVICE·FIELD 수용은 이 ADR의 범위가 아니다.

### Context

ROSY-SIGNAL-001(ESP32 접점 제어)은 클라이언트 책임 4에서 "신호등 보고만으로 로봇 쪽
안전 동작을 억제하는 경로를 만들지 않는다"고 못 박았고, D-163 관측 평면 설계 §4는
"훗날 로봇이 신호를 '보고' 판단해야 하면 이 관측 API가 그 입력이 된다"고 예약해 뒀다.
두 조항은 그동안 충돌처럼 읽혔다 — 하나는 신호 보고의 안전 근거화를 금지하고, 하나는
로봇의 신호 소비를 약속한다.

사이에서 현행 교통 정책은 `RoadEvidence.source="CAMERA_ROAD"`만 받는다. 신호등이
실재해도 로봇 카메라가 등을 못 보면 정지선에서 무한 `WAIT_SIGNAL / signal_unknown`이다.
한편 Fleet의 3자 교차 검증(의도 vs 접점 vs 실측)은 2≠3 — 컨트롤러 주장과 실제 점등이
갈라질 수 있다 — 을 구별하기 위해 존재한다.

### Decision

1. **로봇이 소비할 수 있는 제2 신호 소스는 관측 서비스 `GET /observed`(측정된 빛)뿐이다.**
   ESP32 `/status`(접점 주장)의 로봇 직접 소비는 금지한다. 주장을 믿는 로봇은 배선
   끊김·LED 사망 같은 표시 불일치를 주행 허가로 번역한다.
2. **방향은 읽기뿐.** 로봇→신호등·관측으로 가는 명령 경로를 만들지 않는다(관측 서버에는
   POST가 애초에 없다). 신호 순서의 소유자는 여전히 Fleet이다(D-12).
3. **융합은 fail-closed.** 소스 불일치는 `HOLD / signal_source_conflict`. 소등·부정
   (0개 또는 2개 이상 점등)은 `WAIT_SIGNAL / signal_dark`로 진입 불허 — "신호 없음"이
   아니다. 관측 증거가 진입을 단독 허가하는 경우는 없고, 카메라 증거와 함께 쓰인다.
   무신호 `junction_rule: stop_and_go` 선언에서는 어떤 소스의 신호 관측이든
   `signal_unexpected`로 정지한다.

### Alternatives

- **ESP32 `/status` 직접 소비:** 2≠3 구별을 로봇이 스스로 포기하는 것. 기각.
- **관측 서버에 로봇 전용 엔드포인트·푸시 추가:** 읽기 전용 계약을 위험에 놓는다.
  폴링만으로 충분하다. 기각.
- **카메라 단독 유지:** 무한 `signal_unknown` 문제가 그대로 남는다. 기각 — 이 ADR의
  존재 이유다.

### Transition / validation

- 2026-09-29 T1 착지(같은 날 커밋): `SignalHeadEvidence` + `observe_signal()` + 융합
  판정 — 호스트 시험 통과, 관측 미설정 사이트는 동작 무변경(폴러 자체가 없음).
- T2(폴러)~T5(벤치): `docs/plans/2026-09-29-robot-signal-source-integration.md`.

**Consequences:** 로봇이 ESP32 `/status`를 직접 읽는 경로가 생기면 이 ADR 위반이다.
관측 소비는 "측정된 빛" 입력뿐이며, 신호등 순서 소유(Fleet)와 신호등의 표시 장치
역할은 변하지 않는다.

**References:** [ROSY-SIGNAL-001](../../firmware/signal/README.md),
[관측 평면 설계(D-163)](../plans/2026-09-22-signal-observer-vision-design.md),
[로봇 신호 소스 통합 설계](../plans/2026-09-29-robot-signal-source-integration-design.md),
[무신호 junction_rule 설계](../plans/2026-09-29-traffic-policy-unsignalized-junction-design.md).
