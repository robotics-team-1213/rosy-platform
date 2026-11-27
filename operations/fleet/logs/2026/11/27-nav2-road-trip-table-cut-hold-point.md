## 2026-11-27 · uncommitted · Nav2 road trip table-cut hold point

- 변경: 블록 표가 현재 구간에서 경로를 자르면 같은 구간의 가장 먼 안전 정지점까지 보내고 막은 기체를 이름으로 보이며 기다린다(통행권·점유 칸 앞 여유·구역 칸·횡단보도·급커브 물러섬, 덮임 상실 시 취소 후 재설정, 가드 값 불변)
- 증거: 원격 pytest operations/fleet/test 9783 passed 0 new (D:/DevTemp/route-overlap-wait-1127/rt6)
- gate 변화: 없음
- 결정: D-1009 범위(표가 자른 경우만, 콘솔 wire 검사 유지)
- 교훈: 없음
