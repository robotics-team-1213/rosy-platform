## 2026-11-27 · uncommitted · Hold point review round 3

- 변경: 검토 3차(PR #1140): 해제 안 된 정지점 receipt(fence 포함) 동안 도착 판정 금지, 정지점이 대체할 경로는 어떤 취소든 fence 후 그 주기 반환, 정지점 경로 재시도는 자율 기체의 FAILED만(외부 CANCELED는 종료), ARRIVED 후 위치 밖 확인 대기는 차단 기체가 있으면 stall 아님, 콘솔 신뢰·좌표계 시험은 경로에서 떨어진 기체와 통과 대조군
- 증거: 원격 pytest (PR 본문)
- gate 변화: 없음
- 결정: 없음
- 교훈: 없음
