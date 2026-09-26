# Scene-Context Road Execution Plan

Date: 2026-09-22 · Design: `2026-09-22-scene-context-road-design.md` · ADR candidate: D-162 (Proposed)

ROS-free pure logic first (T1–T2), node wiring next (T3), CORE 수용 last
(T5). 모든 task는 test-first다.

## T1 — `sensing/scene_context.py` 프로파일 + store

- `SceneContextProfile` (frozen, `RoadPerceptionConfig` 8개 필드 전체 +
  `context_id` + `profile_revision`), `perception_config()`.
- `SceneContextStore`: 닫힌 집합(`generic`, `lane_follow`, `stop_line`,
  `crosswalk`), 중복 id/revision 거부, `generic` 필수, 알 수 없는 id는
  KeyError.
- Test: `src/core/control/test/test_scene_context.py`
  - 경계 검증 (bright_threshold 1–254, fraction (0,1], 픽셀/바 수, bool 가드)
  - store 계약 4케이스 + `perception_config()` 등가성

## T2 — `SceneContextMatcher` 히스테리시스 분류

- 규칙: crosswalk > stop_line > lane_follow, `min_confidence` 미만은
  후보 아님. `enter_frames` 연속 확인 후 전환, `exit_frames` 연속 부재 후
  generic 복귀, `signal_conflict` 프레임은 계수 동결, `reset()` 지원.
- `SceneContext` evidence: `context_id`, `confidence`(마지막 확인값),
  `profile_revision`.
- Test: 같은 파일에 추가
  - 시작 generic, 문턱 미만 무시, 진입 N-1 불변/N 전환, 이탈 M-1 유지/M
    복귀, conflict 동결, 우선순위, reset, non-RoadObservation ValueError

## T3 — `road_observer_node` wiring + payload additive 필드

- 파라미터: `scene_context_enabled`(False), `scene_context_enter_frames`(3),
  `scene_context_exit_frames`(8), `scene_context_min_confidence`(0.5).
- `road_observation_payload(..., context=None)` — keyword-only additive.
  enabled일 때만 `"context"` 키 존재.
- 보정 명령(ground model 교체) 시점에서 `matcher.reset()`. mode 전환은
  CORE 정책 리셋(D-151)+매처 히스테리시스 자기 교정으로 커버하고, 모드
  구독 와이어링은 DEVICE 튜닝 게이트에서 재판정한다(설계 문서 §2).
- Test: `test_road_perception.py` payload 케이스 + `test_road_observer_wiring.py`
  파라미터/비활성 기본 동작 케이스.

## T4 — 모듈 하네스 갱신

- `src/core/control/logs.md` append, `progress.md` LOCAL evidence 갱신,
  `python tools/harness/rosy_harness.py generate`.

## T5 — CORE 수용 (하위 슬라이스로 분리 가능)

- `bridge/translate.py::road_evidence` additive 선택 읽기 + 
  `test_bridge_translate.py`.
- `traffic_policy` manager: context를 상태 snapshot에 표시(동작 변화
  없음) + core traffic policy 시험. 정책 파라미터 테이블은 별도 ADR
  플립과 DEVICE 튜닝 증거 뒤에 둔다.

## 범위 밖 (설계 문서 선언 유지)

- 위치(place) 앵커, 신경망 서술자 매칭(Hailo 게이트), 디바이스 학습,
  프로파일 값 튜닝(DEVICE gate), vision 단독 정지 결합.
