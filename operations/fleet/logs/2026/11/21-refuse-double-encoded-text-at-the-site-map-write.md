## 2026-11-21 · uncommitted · Refuse double-encoded text at the site map write boundary

- 변경: core_common.text_encoding + SiteMapStore save_draft/save_profile raise TEXT_DOUBLE_ENCODED; tracked-text test; one mojibake comment fixed
- 증거: pyflakes, harness lint 0 errors, step_back 0 block, lab affected run
- gate 변화: 없음
- 결정: 없음
- 교훈: 없음
