## 2026-11-21 · uncommitted · Run test_measured_calibration_browser.py as lab evidence again

- 변경: affected_browser.LAB_FILES routes the file to pr_land lab, not CI browser jobs
- 증거: affected_browser.split puts it in the lab part; test_calibration_browser_file_is_lab_only pins it
- gate 변화: 없음
- 결정: 없음
- 교훈: fails on GitHub runners 3 of 3, passes on lab PCs; cause open
