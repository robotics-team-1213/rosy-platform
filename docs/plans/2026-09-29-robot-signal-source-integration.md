# 로봇 신호 소스 통합 실행 계획 — T1~T5

- **Status:** 계획 (설계 승인 직후, 미착수)
- **Date:** 2026-09-29
- **Design:** `docs/plans/2026-09-29-robot-signal-source-integration-design.md` (ADR D-337)

각 작업은 독립 커밋이고 뒤 작업은 앞 작업의 시험 위에 선다. 모든 순수 로직은
ROS import 없이(Windows 호스트 pytest 가능), 전송은 가짜 클라이언트로 검증한다.

## T1 — 융합 순수 로직 (`core_features.traffic_policy`)

- `SignalHeadEvidence` dataclass(설계 §2) — 커플링 검증 포함
- `TrafficPolicyManager.observe_signal()` 채널과 §3 융합 표 전 행:
  합의 / 불일치(`signal_source_conflict`) / 관측 단독 / 소등(`signal_dark`) /
  stale·frozen·pending 무시 / `stop_and_go`에서 관측 신호도 `signal_unexpected`
- 시험: `src/runtime/gateway/test/test_traffic_policy.py` 확장 (호스트)

## T2 — 관측 폴러 전송

- `core_features.traffic_policy.observer_source`: httpx 폴러, 주입 시계·전송,
  `/observed` → `SignalHeadEvidence` 변환(운영자 `roi_map` 적용), 동결·나이 예산
- 시험: 가짜 httpx — 200 정상 / 503 NO_FRAME / 지연 / frozen / 형식 오류 기각

## T3 — 설정·배선·계약

- `traffic_policy.signal_observer: {url, roi_map, timeout_s}` — `url` 빈 값이면
  폴러 없음(기본 꺼짐). `services.py` 배선, `rosy_default.yaml` 문서화
- `TrafficPolicyStatus` additive: `signal_source_kind`, 관측 `age_s`·`frozen`
  — API Ref MINOR 동시 갱신(D-18), 이벤트 1종(`..._signal_source_stale`)

## T4 — dashboard

- 교통 팩트에 "신호 원" 행(`/setup`·`/console`), 정적 스캔 시험

## T5 — 벤치(호스트 밖)

- WSL2/Gazebo 폐루프: 신호 있는 씬에서 로봇 카메라 시야 밖 연출 + 관측 증거로
  `WAIT_SIGNAL→PROCEED` 전환, 불일치 주입 시 HOLD 정지
- 실물: 관측 서비스·ESP32·로봇이 한 LAN — `docs/validation/` 증거 디렉터리
- 합성/호스트 합격은 DEVICE가 아니다(D-94)

## 완료 기준

T1~T4 합격 후 `signal_observer` 미설정 사이트는 바이트 단위로 오늘과 같은
동작(폴러 부재·상태 `camera`)이어야 한다. T5 전까지 게이트는 SOURCE/LOCAL.
