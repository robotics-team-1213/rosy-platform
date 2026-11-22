## 2026-11-21 · uncommitted · Keep controls steady during the measured-calibration refresh

- 변경: measured-calibration refresh no longer adds disabled-reason lines above the checkbox or rewrites unchanged attributes; the browser file runs in CI again (LAB_FILES removed)
- 증거: test_measured_calibration_browser asserts the checkbox box is unchanged while a read is held; test_calibration_browser_file_runs_in_ci pins CI routing
- gate 변화: 없음
- 결정: 없음
- 교훈: A 2 s refresh that adds a disabled-reason line moves controls under a held press on a slow device; the click lands on the parent
