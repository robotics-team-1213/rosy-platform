# 로봇 신호 소스 통합 실행 계획 — T1~T5

- **Status:** T1~T4 완료, T5 호스트 폐루프 착지 (2026-09-29) — T5 잔여: WSL Gazebo·실물 벤치
- **Date:** 2026-09-29
- **Design:** `docs/plans/2026-09-29-robot-signal-source-integration-design.md` (ADR D-337)

각 작업은 독립 커밋이고 뒤 작업은 앞 작업의 시험 위에 선다. 모든 순수 로직은
ROS import 없이(Windows 호스트 pytest 가능), 전송은 가짜 클라이언트로 검증한다.

## T1 — 융합 순수 로직 (`core_features.traffic_policy`) ✅

- `SignalHeadEvidence` dataclass(설계 §2) — 커플링 검증 포함
- `TrafficPolicyManager.observe_signal()` 채널과 §3 융합 표 전 행:
  합의 / 불일치(`signal_source_conflict`) / 관측 단독 / 소등(`signal_dark`) /
  stale·frozen·pending 무시 / `stop_and_go`에서 관측 신호도 `signal_unexpected`
- 시험: `src/runtime/gateway/test/test_traffic_policy.py` 확장 (호스트)
- 착지(2026-09-29): `observe_signal`은 `observe`와 같은 나이 보정·증거 리비전
  증가를 가지며, reset·apply_staged가 신호 증거도 지운다. 부정(0·2개 이상 점등)
  헤드는 카메라 색이 있을 땐 무주장(무시), 카메라 색이 없을 땐 `signal_dark`.

## T2 — 관측 폴러 전송 ✅

- `core_features.traffic_policy.observer_source`: httpx 폴러, 주입 시계·전송,
  `/observed` → `SignalHeadEvidence` 변환(운영자 `roi_map` 적용), 동결·나이 예산
- 시험: 가짜 httpx — 200 정상 / 503 NO_FRAME / 지연 / frozen / 형식 오류 기각
- 착지(2026-09-29): `parse_observed`는 확정·비동결 프레임만 증거를 만들고
  pending/frozen/불량 본문은 침묵(None). 색은 운영자 위치 지도(`roi_map`)가
  정하고 관측 `group`은 해석에 쓰지 않는다(관측 설계 §2 정신). 폴러는
  `last_outcome`·`last_age_s`를 남겨 T3 readback이 소비한다. 스케줄링·스레드는
  T3 배선 소관이라 여기 없다.

## T3 — 설정·배선·계약 ✅

- `traffic_policy.signal_observer: {url, roi_map, timeout_s}` — `url` 빈 값이면
  폴러 없음(기본 꺼짐). `services.py` 배선, `rosy_default.yaml` 문서화
- `TrafficPolicyStatus` additive: `signal_source_kind`, 관측 `age_s`·`frozen`
  — API Ref MINOR 동시 갱신(D-18), 이벤트 1종(`..._signal_source_stale`)
- 착지(2026-09-29): 바인딩은 파일 설정 전용(오버레이)이고 map/scene 없는
  바인딩은 빌드를 실패시킨다. `SignalObserverMonitor`(데몬 스레드)가 폴링을
  소유하며 서버 프레임 나이를 접수 시각에 보정해 주입한다.
  `fused` 표기는 관측 증거가 유효한 동안만. 침묵 전환마다
  `nav.traffic_policy_signal_source_stale`(warning) 1회. API Ref v1.56.

## T4 — dashboard

- 교통 팩트에 "신호 원" 행(`/setup`·`/console`), 정적 스캔 시험
- 착지(2026-09-29): 값은 `signal_source_kind`(camera|fused)를 그대로 보여 주고
  관측 프레임 동결 시 `frozen`으로 표기한다. 새 토큰·부품 없음.

## T5 — 벤치(호스트 밖)

- WSL2/Gazebo 폐루프: 신호 있는 씬에서 로봇 카메라 시야 밖 연출 + 관측 증거로
  `WAIT_SIGNAL→PROCEED` 전환, 불일치 주입 시 HOLD 정지
- 실물: 관측 서비스·ESP32·로봇이 한 LAN — `docs/validation/` 증거 디렉터리
- 합성/호스트 합격은 DEVICE가 아니다(D-94)
- 진행(2026-09-29): **호스트 폐루프 착지** — `tools/sim/simulate_semantic_road.py`가
  3 시나리오(신호 제어·무신호 stop_and_go·관측 융합)를 production subjects로 돌리고
  `docs/validation/semantic-road-stop-and-go-2026-09-29/`에 PASS 증거가 있다.
  잔여: WSL Gazebo 실렌더링 폐루프(카메라 시야 밖 연출은 기존 마운트의 신호
  비가시 성질로 자연 재현 가능 — 2026-09-21 증거 참조), 관측 서비스 실HTTP(T2
  전송) 연결, 실물 LAN. WSL2 Jazzy+Gazebo+`/opt/rosy` 오버레이 존재 확인(2026-09-29).

## 완료 기준

T1~T4 합격 후 `signal_observer` 미설정 사이트는 바이트 단위로 오늘과 같은
동작(폴러 부재·상태 `camera`)이어야 한다. T5 전까지 게이트는 SOURCE/LOCAL.
