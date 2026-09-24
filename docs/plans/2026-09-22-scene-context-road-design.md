# Scene-Context Profiles for Road Perception Design

Date: 2026-09-22

## Goal

카메라 도로 인식(`sensing/road.py`, D-151)이 장면마다 고정된
`RoadPerceptionConfig` 하나로만 동작하는 것을 바꿔, "학습된 장면"마다
등록된 파라미터 프로파일을 쓰고, 어느 장면에도 해당하지 않으면 어디서든
안전한 제네릭 프로파일로 폴백한다. 학습된 장면을 통한 일반 처리의 첫
소비자는 도로 인식 파라미터다.

ADR 후보: **D-162 — 학습된 장면은 설정이지 권한이 아니다**(이 설계와 함께
Proposed로 등록).

## Decision

1. **장면 = 상황 기반 context id** (위치와 무관). `place` 앵커 필드는
   스키마에 넣지 않고, 귀환/토폴로지 임무가 생길 때 확장으로 남긴다.
   v0 context 집합은 닫힌 집합이다: `generic`, `lane_follow`, `stop_line`,
   `crosswalk`.
2. **학습/저작은 오프라인**이다. 프로파일은 리비전 문자열이 붙은 등록
   아티팩트다. 디바이스에서 학습하거나 자기 갱신하지 않는다. 신경망
   서술자 매칭(L1)이 필요해지면 Hailo 게이트(D-29/T5)를 공유한다.
3. **폴백 우선 설계**가 일반화의 정의다. 제네릭 프로파일이 기본값이고,
   매칭 성공은 "업그레이드"다. 새 사이트 제로샷은 별도 기능이 아니라
   폴백 품질로 충족한다. 불확실성은 항상 능력을 줄이는 방향으로만 결합한다
   (`PersonAdvisory.clip()`과 같은 원칙).
4. **장면은 설정이지 권한이 아니다.** context 선택은 인지 파라미터만
   바꾼다. 최종 명령, 정지 판정, mode 전환 권한은 여전히 CORE 소유다
   (D-2/D-38/D-151). context 전환은 히스테리시스로만 일어나고 관제
   supervisory 변경(D-151 "정지 중 apply")과 무관하게 evidence 품질만
   좌우한다.
5. **첫 소비자는 도로다.** CORE `traffic_policy` 파라미터의 장면별
   테이블은 같은 evidence를 소비하는 후속 슬라이스다(이 플랜 T5).

### 이름 구분 (중요)

- 기존 `road_scene.yaml` / `scene_revision` 파라미터 = 시뮬레이션
  semantic world 정답(D-151). 절대 검출기 입력이 아니다.
- 신규 **scene context** = 런타임 상황 분류 결과. 코드 식별자는
  `context_id`, `context_profile_revision`으로 `scene_revision`과 절대
  섞이지 않게 한다. 모듈은 `sensing/scene_context.py`.

## Modules

### 1. `scene_context` (pure, ROS-free)

- 소유 위치: `src/core/control/control/sensing/scene_context.py`
- `SceneContextProfile`: `RoadPerceptionConfig` 필드 8개 전체를 명시적으로
  담는 frozen 프로파일 + `context_id` + `profile_revision`. diff가 아니라
  전체 집합으로 기록해 병합 모호성을 없앤다. 값 경계는
  `detect_road_observation`의 검증과 동일하다.
- `SceneContextStore`: 등록 레지스트리. 닫힌 context 집합, 중복
  context_id/revision 금지, `generic` 프로파일 필수. 알 수 없는 id 조회는
  KeyError로 실패한다(fail-closed).
- `SceneContextMatcher`: `RoadObservation` 스트림을 context로 분류한다.
  L0은 저작된 규칙이다 — 우선순위 crosswalk > stop_line >
  lane_follow, 신뢰도 문턱값 미만은 후보 아님. 진입은 `enter_frames`
  연속 확인, 이탈은 `exit_frames` 연속 부재, `signal_conflict` 프레임은
  계수를 동결한다(모순 중 추측 금지).
- `SceneContext`: evidence 1개 — `context_id`, `confidence`(현재
  context의 마지막 확인 신뢰도), `profile_revision`.

### 2. `road_observer_node` wiring

- `scene_context_enabled`(기본 False) 등 파라미터 추가. 비활성이면
  payload에 context 필드가 아예 없다(하위 호환).
- 활성이면 프레임마다 matcher를 update하고, 선택된 프로파일의
  `perception_config()`로 검출하고, payload에 additive 필드
  `context`를 붙인다. v0 프로파일 값은 제네릭과 동일하다 — 값 튜닝은
  DEVICE gate 증거로만 한다(D-52 카메라 자세와 같은 문화).
- `reset()`은 이 노드가 알 수 있는 세션 폐기 지점, 즉 보정 명령(ground
  model 교체)에서 호출한다. mode 전환 시 CORE는 정책 세션을 이미 폐기하고
  (D-151), road observer는 모드를 모르므로 Control 매처는 히스테리시스
  자기 교정(exit_frames 연속 부재)에 의존한다. 모드 구독 와이어링은
  프로파일이 중립에서 벗어나 실제 동작 차이가 생기는 DEVICE 튜닝 게이트에서
  재판정한다.

### 3. CORE 수용 (T5)

- `bridge/translate.py::road_evidence`가 additive `context` 필드를
  선택적으로 읽는다. 필드가 없으면 기존 동작 그대로.
- `traffic_policy` manager는 context를 상태/observability에 노출한다.
  정책 파라미터 변경은 하위 ADR 플립 전까지 없다(D-151 supervisory).

## Data Flow

```text
camera/front -> road observer -> detect(context profile) -> road/observation
                                                 +- context {id, confidence, revision}
road/observation -> CORE translate -> traffic policy (context 표시만, v0)
```

## Fail-closed rules

- 알 수 없는 `profile_revision`으로 로드 시도: 폐기, 제네릭 유지.
- store에 `generic` 없음 / 중복 id·revision: 생성 거부.
- `signal_conflict`: context 전환 계수 동결.
- context 비활성/필드 부재 payload: CORE는 기존 동작(기본 파라미터).
- context 어떤 결과도 정지·감속을 직접 만들지 않는다. 오직 CORE 정책이
  기존 경로로만 명령을 결정한다.

## Validation

1. 프로파일 경계 검증(bright_threshold, fraction, 픽셀 수) 시험.
2. store 계약(중복·generic 필수·알 수 없는 id) 시험.
3. matcher 히스테리시스: 진입 확인 프레임 수, 이탈 프레임 수, conflict
   동결, 우선순위(crosswalk > stop_line > lane_follow) 시험.
4. payload: enabled일 때만 `context` 필드, disabled일 때 필드 부재
   시험(T3).
5. CORE translate 양방향(필드 있음/없음) 시험(T5).

## Acceptance boundary

LOCAL(Windows host pytest)은 순수 로직과 계약만 증명한다. context 분류가
실제 조명·시간대에서 유지되는지는 ROS-SIM(Gazebo 카메라)과 DEVICE
증거가 필요하며, 프로파일 값 튜닝은 DEVICE gate 전까지 의도적으로
제네릭과 동일하게 둔다. 본 슬라이스는 "장면 프로파일 메커니즘"의
source-complete다.
