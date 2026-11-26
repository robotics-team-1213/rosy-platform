## 2026-11-26 · uncommitted · Fleet console part2 browser tests follow in-place roster cards and the viewer E-stop

- 변경: test_keyboard_traverses_the_roster_and_arms_a_goal waits for a real state change to re-render the focused rosy_03 summary card and checks focus stays on that same node (f729d4bee2 keeps one article per robot, so the old wait for a rebuilt card never ended). The viewer case of test_desktop_exception_states_fit_without_hiding_evidence expects a live E-stop with no reason (D-1043, c900aba2df) instead of the old operator lock.
- 증거: origin/main b864ae96ac reproduced 2 failed, 26 passed: D:/DevTemp/ui-map-panel-1126/part2-fix/repro/run-1.txt
- gate 변화: 없음
- 결정: D-1043
- 교훈: 없음
