---
symptom: "test_omx_cell_field.py가 전체(FULL) 부하 실행에서만 intermittently 실패하고 단독(alone)에서는 통과한다 — state[\"t\"] stale 거부"
discovered: 2026-11-15
category: test-failures
tags: [omx, cell_field, max-gap-s, fixture, flaky-test, landing-gate, liveness, deadline, gateway]
---

# `marking_cell` 픽스처의 고정 `time.time()` 스탬프가 부하 시 `MAX_GAP_S` (0.5s)를 넘어 stale 실패로 위장한다

## 증상

`test/test_omx_cell_field.py::test_supervised_marks_use_checked_commands_and_keep_park_recovery`가
원격 전체(`FULL`) 스위트 부하 아래에서 intermittently `refused`(또는 `"blobs" not in out`)로
실패하고(`LOAD-FLAKY`), 단독 재실행에서는 통과해 명시적 `--tests full` 착지가 반복 중단됐다
(2026-11-15 `fc18332803` 커밋 메시지 기록 기준).

## 원인

- `deploy/robot/omx/cell_envelope.py`의 `_state_current(state, now)`(:100-104)는
  `deploy/robot/omx/guarded_device.py`(:14)의 `MAX_GAP_S = 0.5` 이내인지
  `0 <= now - state["t"] <= MAX_GAP_S`로 검사한다.
- `deploy/robot/omx/cell_pipeline_io.py`(:115)는 실행 중 `time.time()` 기준으로 `_state_current`를 호출한다.
- 수정 전 `test/test_omx_cell_field.py`의 `marking_cell` 픽스처(:63-65)는 setup 시점의
  `time.time()`을 `state["t"]`에 1회 고정했다. 원격 다중 잡 부하로 테스트 본문 또는
  모듈 로딩이 `0.5s` 이상 지연되면 픽스처가 의도치 않게 stale 상태로 판정됐다.

## 해결

`test/test_omx_cell_field.py`(:63-88, 커밋 `fc18332803`, `main` 착지 `8756a1f8ef`)에서
픽스처 생성 시각 `created = time.time()`를 기록하고, `act("state")`가 호출될 때마다
`{**state, "t": time.time() + (state["t"] - created)}`를 반환하도록 수정했다.

- 정상 경로는 쿼리 시점의 현재 시각을 기준으로 신선도(`<= MAX_GAP_S`)를 유지한다.
- `test_marks_reject_wrong_or_stale_follower_before_motion_or_cleanup`(:130)처럼
  테스트가 명시적으로 `case.state["t"] -= 3600`으로 과거 시점을 주입하면 오프셋이 그대로
  유지되어 fail-closed 거부 계약은 약화되지 않는다.
- 운영 코드(`MAX_GAP_S`, `_state_current`)는 그대로 유지했다.

## 검증 근거

- 수정 직후 `python tools/remote/remote_pytest.py --sha fix/sync-publish-20261115 -- test/test_omx_cell_field.py -q`
  단독 실행(`rosy` 호스트): `19 passed`, exit 0.
- `main` 착지(`8756a1f8ef`) 시 원격 검증(`rosy` 호스트): `239 passed`, `0 new, 0 known, 0 flaky`.

## 재발 방지

- `_state_current` 등 짧은 wall-clock freshness 창(`MAX_GAP_S = 0.5s`)을 검사하는 테스트 픽스처는
  setup 시점에 `time.time()`을 고정하지 말고 응답 시점에 오프셋(`time.time() + (t - created)`)으로 계산한다.
- 정상 실행을 살리기 위해 `MAX_GAP_S`를 키우거나 stale 거부 테스트를 완화하지 않고,
  명시적 시간 오프셋 검증을 그대로 둔 채 픽스처 시계만 일관되게 맞춘다.
## 같은 계열 사례 (2026-11-18)

두 시험이 착지 사전 시험에서 NEW 로 멈췄고, 같은 후보 sha 의 단독 원격 재실행은 통과했다. 둘 다 운영 코드의 시간 창은 그대로 두고 시험 쪽 시계만 고쳤다(커밋 `f22cfd55aa`, main 에는 병합 `9b988da637` 로 들어감).

- `middleware/core/gateway/test/test_control_unit_core_pipeline.py`: 부하 호스트에서 준비 단계만 74 s 걸려 합성 odometry 가 `HARDWARE_LIVENESS_S`(15 s, `contracts/foundation/core_common/domain/capabilities.py`)를 넘겼다. `_hardware_presence` 가 "silent" 를 돌려 `navigation.goal_navigation is not advertised` 로 실패했다. 해결: dispatch 직전에 `services.state.set_velocity(0.0, 0.0)` 로 odometry 를 새로 넣는다.
- `test/test_omx_arm_session_carry.py::test_the_deadline_never_interrupts_a_fold_in_progress`: 0.05 s 데드라인이 느린 호스트에서 carry 가 명령에 들어가기 전에 지나 `entered.wait(5)` 가 시간 초과했다. 해결: `ArmGoals.timing` 으로 `clock` 을 주입하고(`arm_session_carry.py` 가 kwargs 로 넘김), carry 가 명령 안에 들어간 뒤에야 시계를 60 s 앞당긴다.

검증: 같은 커밋으로 두 파일을 포함한 7파일 원격 실행 exit 0, 묶음 착지 사전 시험에서 재발 없음.

일반 규칙: 시험이 짧은 실시간 창(신선도, 생존, 데드라인)을 넘기는 순간을 표현하려면 sleep 이나 작은 실제 시간 값에 기대지 말고, 주입한 시계를 시험이 원하는 시점에 앞당긴다. 부하 호스트에서는 준비 단계만으로 수십 초가 걸릴 수 있다.
