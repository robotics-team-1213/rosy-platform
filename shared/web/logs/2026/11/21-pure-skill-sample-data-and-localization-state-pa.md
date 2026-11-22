## 2026-11-21 · uncommitted · Pure skill, sample-data and localization state parts (slice 4 of #378)

- 변경: Add skill-state.js, sample-data.js and localization-state.js to web_common with node tests; nothing imports them yet, so no screen changes. The rest of slice 4 (robot-profile, robot-row, robot-options, evidence-line) waits for status-tag.js and value-text.js from slice 2.
- 증거: node --test skill-state and localization-state tests; remote lab affected run (see PR body)
- gate 변화: 없음
- 결정: 없음
- 교훈: 없음
