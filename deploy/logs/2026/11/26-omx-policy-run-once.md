## 2026-11-26 · uncommitted · OMX 정책 실행 1회 제출 작업 cell_policy_run

- 변경: 한 세션·한 잠금 안에서 사전 확인(무게·envelope·라이브러리·세션 상태·카메라 새 프레임) → home(필요 시) → cell_policy_drive를 도는 작업과 단계별 시간 영수증. 세션 래퍼(A·B)가 시작 실패 이유·모터 comm 코드·잠금 보유자를 JSON으로 남기고 일시 원인만 정해진 횟수 안에서 재시도. timed 관측의 첫 상태를 세션 live 관절 상태에서 읽음
- 증거: test_omx_policy_oneshot.py 원격 시험(결과는 PR 보고에 기록), 래퍼 bash -n
- gate 변화: 없음(관측 신선도 한계 0.6 s, 가드, person_at_switch, D-1024, lease 그대로)
- 결정: 없음
- 교훈: 없음(실물 수용 전)
