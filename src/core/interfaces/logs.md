## 2026-09-22 · uncommitted · chore: update ARTIFACT blocker to Native Image Builder (D-164)

- 변경: deploy/robot/Dockerfile 의존성을 Native Pi Image Builder로 일괄 변경
- 증거: D-161, D-164
- gate 변화: 없음


# interfaces logs

추가만 한다. 형식: [module harness 설계](../../docs/plans/2026-09-15-module-harness-design.md) §4.2.
2026-09-15 이전 이력은 `git log -- src/interfaces`를 본다.

## 2026-09-15 · uncommitted · docs(harness): start the interfaces harness record
- 변경: `progress.md`, `logs.md` 추가
- 증거: repo `test/`에서 `interfaces`·`Emotion.srv`·`SetLed.srv`·`SetLamp.srv`·`SetBrightness.srv`를 grep — srv 스키마를 고정하는 host-runnable contract test 없음(`src/core/test/test_bridge_timers.py`는 import stub 목록에만 존재). SOURCE/LOCAL 모두 미실행 — 근거 부재
- gate 변화: 없음(신규 기록). SOURCE/LOCAL HOLD, ROS-SIM N/A, ARTIFACT/DEVICE HOLD(io 이미지에 포함, Device 계획과 동일 blocker), FIELD N/A
- 결정: D-61 Proposed
- 교훈: 없음

## 2026-09-16 · uncommitted · docs(harness): park interfaces field gate and point at the CI build
- 변경: 2차 리뷰 반영. io 이미지에 실리는 패키지이므로 FIELD를 PARKED로, 다음 gate에 CI `Build (colcon)` 결과를 증거로 쓰는 경로 추가
- 증거: 미실행 — 기록 정정만
- gate 변화: FIELD N/A→PARKED
- 결정: 없음
- 교훈: 없음
