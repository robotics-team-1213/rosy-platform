# dashboard logs

추가만 한다. 형식: [module harness 설계](../../../docs/plans/2026-09-15-module-harness-design.md) §4.2.

## 2026-09-25 · uncommitted · refactor(hmi): operator screens leave the API package (D-243)

- 변경: `core_api_web/web`의 정적 파일을 이 패키지로 옮겼다. API는 설치 share 또는 이 소스 폴더를 읽는다
- 증거: 이 기록 직후 dashboard·gateway 대시보드 시험
- gate 변화: 신규. SOURCE GO, LOCAL GO, ARTIFACT HOLD, ROS-SIM/DEVICE/FIELD N/A
- 결정: D-243
- 교훈: 없음
