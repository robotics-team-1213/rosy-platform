## D-608 Fleet 사건 보고서는 교착 판정과 정지 원인을 구별하고 출처별 증거와 사람 검토를 남긴다

**Status:** Proposed (2026-10-10, 사용자 요청. 소스·시험 PC 검증과 현장 배포·브라우저·물리 확인은 별도)

잇는 결정: [D-407](D-407-lane-stuck-recovery-console-then-local.md), [D-503](D-503-autonomy-chain-facts-and-exception-queue.md), [D-517](D-517-multi-robot-lane-traffic.md), [D-577](D-577-trouble-fleet-rules-and-ai-pc-realtime-situation-facts.md), [D-579](D-579-learning-capture-goal.md). 최종 주행 명령은 CORE만 낸다([D-18](D-18-rosy-core.md)).

### Context

- 현장 Fleet의 2026-10-10 읽기 전용 기록에는 라인 정지 에피소드가 100건(그중 `no_motion` 55, `lane_lost` 27, `obstacle_ahead` 18) 있고, Rosy Cam의 `sighting_audit`도 갱신된다. 당시 `site_trips`는 0건이었다. 이 자료는 반복 정지를 보여 주지만 실제 다중 로봇 교착을 증명하지 않는다.
- 기존 `/traffic.wait_cycle`은 한 주기의 대기 순환 후보이고, Fleet 해결기는 같은 순환 3주기 뒤에만 인계한다(D-517). AI PC의 `wait_cycle_confirmed`는 신선한 상태와 세 스냅샷 동안의 정지를 따로 검사하며 `fleet_agrees`가 거짓일 수 있다(D-577). 화면이 첫 후보부터 모두 “교착”이라고 쓰면 이 차이가 사라진다.
- 닫힌 라인 정지의 앞 카메라 한 장은 Fleet 메모리에서 버리도록 D-577이 정한다. 과거 보고서에 이미지가 있는 것처럼 표시하거나 원본 프레임을 학습 내보내기에 섞을 수 없다.

### Decision

1. **판정 어휘를 분리한다.** `line_stuck`은 CORE의 한 로봇 정지 에피소드다. `wait_cycle` 첫 관측은 “대기 순환 후보”다. Fleet 해결기의 `trigger: wait_cycle`은 지속된 순환으로 표시한다. AI PC의 `wait_cycle_confirmed`는 별도 사실이고 `fleet_agrees: false`이면 “AI 단독 판단”으로 표시한다. `stalled`, `livelock`, `unknown_occupancy_long`은 각각 별개로 기록한다. 어느 하나를 다른 하나의 확정 근거로 자동 승격하지 않는다.
2. **사건 기록은 기존 영속 자료에서 조립한다.** `GET /api/fleet/incidents?limit=1..100`(viewer)은 최신 라인 정지 에피소드 `reports`와 최신 AI 상황 사실 `traffic_reports`를 각각 `rosy.incident.v1` JSON으로 반환한다. 라인 정지는 `id`, `classification`, `robot_ids`, 시작·종료 시각, 출처별 `evidence.core`·`fleet`·`rosy_cam`·`ai_facts`·`front_image`, `actions`, `reviews`를 둔다. Rosy Cam은 같은 사이트 DB의 사건 시작 ±5초에 수락된 해당 로봇 관측 하나만 연결하고, 없으면 null이다. AI 사실은 시작 ±5초·같은 로봇의 최근 3개만 참고로 연결한다. 이 시간상 인접성은 인과 관계가 아니다. 앞 카메라 그림은 보존하지 않았다고 명시한다. `traffic_reports`는 D-577의 영속 `fleet_ai_facts` 중 교착·정체·위치 불명 사실을 사실 행 ID별로 제공하고, CORE·Rosy Cam 근거가 연결되지 않았으면 null을 둔다.
3. **사람 검토는 추가 기록이다.** 이름 있는 운영자는 라인 정지 또는 AI 사실 행별 원인 분류(`line_marking`, `obstacle`, `robot_fault`, `localization`, `traffic_wait`, `unknown`)와 최대 1000자 메모를 제출한다. `fleet_incident_reviews`와 `fleet_ai_fact_reviews`는 이전 검토를 덮지 않고 시각·운영자와 함께 누적한다. 교정은 사실이나 CORE 답을 바꾸지 않는다. 보고서 JSON은 LLM 분석과 오프라인 재생의 입력이며, 사람 검토는 정답 후보이지 모델·규칙의 자동 승격이 아니다.
4. **콘솔에 보고서를 둔다.** 최근 사건을 CORE·Fleet·Rosy Cam·AI·조치·사람 검토 순서로 보여 주고 JSON을 내려받는다. 진행 중인 조치는 기존 예외 큐와 CORE 재검사 경로를 쓴다. 이 기능은 로봇 이동, E-Stop 해제, 자동 경로 전환, 모델 학습 실행을 새로 만들지 않는다.
5. **폐루프의 다음 관문.** 사건 수집 → 사람이 원인과 근거를 검토 → 식별 정보를 정리한 JSON과 D-379 녹화를 기존 수집·평가 라인에 연결 → 원인별 재발률과 오경보를 측정 → 별도 승인과 재생·시뮬레이션·현장 검증 뒤 규칙·모델을 바꾼다. 이미지 보존·프레임 반출·자동 재학습은 별도 계약과 동의가 필요하다.

### Consequences

- AI PC의 `incident_context` 사실은 열린 정지 한 건에 대한 원인 초안이다(D-577 개정). 이 사실은 일반 사실의 시작 ±5초 근접 결합 대신 같은 로봇의 정확한 `stuck_id`와 시작 -5초~+120초로 연결한다. 보고서 `evidence.ai_facts`와 화면에 초안·출처별 근거·누락 자료가 함께 나오며 사람 검토와 분리된다. Rosy Cam은 관측 메타데이터만 사용한다. 영상 내용은 해석하지 않았음을 명시하고, 모델 활성화와 실제 현장 검증은 별도 관문이다.

- 보고서의 Rosy Cam 관측은 당시 가까운 관측이지 장애물의 사진이나 원인 증명이 아니다. 관측이 없을 때 null을 유지한다.
- AI 상황 사실은 행별 검토가 가능하지만, 같은 순환에서 매 초 생긴 행을 하나의 영속 사건으로 묶지 않는다. AI PC가 꺼진 동안 Fleet의 순환만 생긴 경우도 아직 영속 사건 ID가 없다. 이 두 연결과 운행 결과 연결은 후속 구현이다.
- 시험 PC 호스트 테스트는 UI 렌더링과 API 계약을 확인한다. 현장 Fleet 이미지·인증 브라우저·Rosy Cam 프레임·물리 로봇 수용은 따로 확인한다.
