## 2026-11-20 · uncommitted · docs(adr): D-1057 셀 작업 허가 증거는 실측값으로만 공급

- 변경: ADR D-1057과 ADR Log 행, API Reference에 bed-confirm·owner-evidence 두 경로(버전은 "vX.Y (조정 세션 예약)" 자리표시).
- 증거: 아래 Fleet·셀 변경 커밋의 로컬 시험과 `rosy_harness.py lint`. 원격 시험은 조정 세션.
- gate 변화: 없음. 실물 인터록(브레이크·bed 센서·명령 속도)은 만들지 않았다.
- 결정: 없음
- 교훈: 없음
