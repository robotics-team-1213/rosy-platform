---
module: docs
---

# 차선 판단을 동작 id로 연결 (D-228)

결정: [D-228](../adr/D-228-decision-lives-in-core-features.md). 입력은 저장소 밖 `ROSY_Decision_Fabric_AI_Judgment_Architecture_v0.8.md` 의 첫 사례 `lane_recovery` 다.

이 계획은 `control` 을 나누지 않고, `src/runtime` 을 만들지 않는다. 차선 추종이 내는 선속도·각속도는 `line_follow` 에 남는다. 판단 라이브러리는 `FOLLOW` 또는 `STOP` 만 고른다.

## Task 1: 규칙

**Files:** `src/core/core_features/core_features/decision/lane.py`, `src/core/core_features/test/test_lane_recovery.py`

1. 보이는 차선, 신뢰도가 기준 이상, 관측이 신선하고, 소스가 모드와 같으면 `FOLLOW`.
2. 그 밖은 `STOP`. 신뢰도 부족을 `SLOW` 로 바꾸지 않는다. 지금 추종기는 그 경우를 이미 정지로 처리한다.
3. `SAFE_STOP` 이면 라우터가 `FOLLOW` 를 버리고 `INVALID` 로 남긴다. 규칙이 그 id 를 `STOP` 으로 고쳐 쓰지 않는다.
4. 결과는 속도 필드를 갖지 않는다.

완료: `python -m pytest src/core/core_features/test/test_lane_recovery.py -q`

## Task 2: 추종기가 같은 규칙을 읽게

**Files:** `src/core/core_features/core_features/line_follow/manager.py`, `src/core/core/test/test_line_follow.py`

조건: Task 1 이 통과한 뒤. `line_follow.tick` 은 `lane_recovery_rule` 이 `FOLLOW` 일 때만 기존 속도 식으로 들어간다.

1. `tick` 의 추적 여부는 `lane_recovery_rule` 의 `FOLLOW` 와 같다.
2. `TRACKING` 일 때의 선속도·각속도 식은 그대로다.
3. `HOLD` / `LOST` / `WAITING` 문구와 손실 래치는 매니저에 남는다. 동작 id 가 그 문구를 대체하지 않는다.

완료: 기존 `test_line_follow.py` 가 속도 값을 바꾸지 않고 통과한다.

## Task 3: 다른 판단 종류

도킹, 배회, 잡기, 자동 라벨은 각각의 요구가 생기기 전에 규칙을 추가하지 않는다. 원격 모델과 사이트 워커는 이 계획에 없다.
