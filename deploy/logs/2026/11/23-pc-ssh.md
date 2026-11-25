## 2026-11-23 · uncommitted · PC SSH 워치독 서명 갱신

- 변경: 승인된 PC는 서명과 순번을 검증한 SSH 워치독 실행 파일을 원자적으로 교체한다. D-805 동결과 PC별 복구 설정을 보존한다.
- 증거: 서명, 순번, 셸 구문, 교체 실패, 셀 PC 설치 경로의 설정 보존을 호스트 회귀로 확인한다. AI PC에서 첫 서명 파일(순번 1)을 내려받아 설치했다.
- gate 변화: 없음. AI PC 외 장비의 수용은 별도다.
- 결정: 없음
- 교훈: 현장에서 systemd가 모르는 `ConditionPathIsExecutable=` 지시어를 무시했다. 실행 파일 조건을 `ConditionFileIsExecutable`로 고치고, 현장 문제의 원인을 systemd 파서 회귀로 고정했다.
