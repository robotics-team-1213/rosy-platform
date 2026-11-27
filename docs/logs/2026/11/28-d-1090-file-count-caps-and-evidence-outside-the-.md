## 2026-11-28 · uncommitted · D-1090 file-count caps and evidence outside the repo

- 변경: test/architecture/test_file_count_budget.py가 추적 파일 50개 이상 영역마다 파일 수 상한을 건다(코드 +20, adr·solutions +10, validation·plans 0). 날짜 증거의 기본 위치를 ROSY_SCRATCH와 PR 본문으로 옮겼다.
- 증거: 30일 순증 약 3,040개(추가 3,270, 삭제 230), 신규 solutions 165·adr 139·validation 101. 네 입장 병렬 토론 1단계.
- gate 변화: 새 구조 시험 하나(상한 초과 실패, 여유 40 초과 경고)
- 결정: D-1090 Accepted
- 교훈: 없음
