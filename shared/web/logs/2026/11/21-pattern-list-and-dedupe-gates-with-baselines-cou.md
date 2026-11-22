## 2026-11-21 · uncommitted · pattern list and dedupe gates with baselines counted on main (slice S1 of #378)

- 변경: shared/web/patterns.yaml, shared/web/test/test_patterns_registry.py, test_shared_dedupe.py, test_icon_gates.py, test_no_element_style.py, DESIGN.md (C1-C25 table, 5 sections moved to docs/reference/ui-design-details.md), tokens.css (unused --shadow-base removed), test/robot_literal_backlog.txt
- 증거: baselines re-counted on current main with the gate functions (plain python); lab run per D-584 recorded in the PR; pytest not run on this PC
- gate 변화: 새 검사: 패턴 목록 대조, 공용 도우미·직접 쓰기·본문 복제 상한, 소비자 없는 이름 상한, 아이콘 정적 검사 상한, 전 웹 표면 element style 검사
- 결정: 없음
- 교훈: 없음
