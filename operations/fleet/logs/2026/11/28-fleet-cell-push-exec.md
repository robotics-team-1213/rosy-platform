## 2026-11-28 · uncommitted · feat(fleet): a push cell task is auto-admitted like the free pick and completes on measured displacement (D-1083)

- 변경: `cell_motion.restrict_motion_admission`가 밀기와 자유 위치 집기를 같은 조건(스위치 켜짐 + service + propose 없음)으로 `QUEUED`로 둔다. `PUSH_NOT_EXECUTABLE`(생성·`/admit`)을 없앴다. `claim_refusal`은 밀기에 `capabilities`의 `"push"`를 요구한다(`WORKER_LACKS_PUSH_CAPABILITY`, 작업은 `QUEUED`). `/complete`는 밀기에서 `push_completion_verified`(정확한 증거 키, 명령 거리와 같음, 방향 변위 0.5~1.5×mm+3, 옆 6 mm 이하, 합 일치)로 증거를 직접 검사한다. 밀기에는 화물 신원 필드를 못 싣는다.
- 증거: remote_pytest `operations/fleet/test`·`test_cell_motion_tasks.py`(허용·거절 매트릭스, 표지 게이트, 실제 `/complete` 경로) — 실행 기록은 구현 보고서
- gate 변화: 없음(밀기 완료 가드가 새로 생김, 다른 가드는 그대로)
- 결정: D-1083
- 교훈: 없음(셀 수용 전)
