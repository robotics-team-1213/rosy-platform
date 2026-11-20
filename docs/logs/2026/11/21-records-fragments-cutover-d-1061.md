## 2026-11-21 · uncommitted · records fragments cutover (D-1061)

- 변경: new_record.py api --surface/--slug unnumbered fragments, consolidate numbers them; lint cutover rule, ADR number guard, strict/lenient records checks; adr_reserve fetch+remote ref push; records bot on main push
- 증거: pytest test/test_records_fragments.py test/test_land_conflict_free_records.py; rosy_harness.py lint
- gate 변화: 없음
- 결정: D-1061
- 교훈: 없음
