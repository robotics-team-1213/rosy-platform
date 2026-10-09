# 남쪽 굽이 SIM의 지도 전체 차로 투영

2026-10-08의 두 `edge_left` 폐루프 SIM 원본을 **같은** `map_v2_fleet/lane_graph.yaml`의 모든 segment에 투영해 [기존 west edge 단독 분석](../lane-goal-sim-2026-10-08/result.md)과 [가드 적용 재실행](../lane-fallback-sim-2026-10-08/result.md)을 보완했다. 아래 수치는 SIM 참 자세의 **중심점과 가장 가까운 지도 중심선** 거리다. 다른 segment로의 전환은 허용하지만 선택된 trip 경로와 같은지는 검사하지 않는다.

| 원본 / 출발 후 첫 프레임 | 유효 프레임 | 전체 중심선 최대 거리 | 40 mm 초과 | 반폭 92.5 mm 초과 | 최악 위치 |
|---|---:|---:|---:|---:|---|
| 이전 `edge_south1`, SHA-256 `6F068DAA8184D9FDA6F6BF9F894A32AEBB07D9BB80126ADC82E77FB29122B1D4` / 75 | 487 | 0.0638 m | 16 | 0 | frame 236, west |
| 오른쪽 대체 가드 적용 `edge_south1`, SHA-256 `F3960380436433C15EEBC2FA315B0C42BEA4AC67DE2CF8541B75EF987C13A1DA` / 64 | 334 | 0.0363 m | 0 | 0 | frame 235, west |

재현:

```text
python docs/validation/lane-network-projection-2026-10-08/evidence/analyze_network.py X:/DevTemp/bend-window-sim/edge-south1-frames.npz middleware/perception/map/map_v2_fleet/lane_graph.yaml --start-index 75
python docs/validation/lane-network-projection-2026-10-08/evidence/analyze_network.py X:/DevTemp/lane-fallback-width/edge-south1-frames.npz middleware/perception/map/map_v2_fleet/lane_graph.yaml --start-index 64
```

가드 적용 실행의 frame 214는 west edge만 보면 0.1760 m 떨어져 있지만, 회전교차로의 `ring_w`에서는 0.0149 m다. 그러므로 기존 **west 단독** 최대 편차를 곧바로 차선 침범으로 해석하면 안 된다. 두 실행은 동일 입력의 통제 A/B가 아니므로 표의 차이를 새 가드 효과로 귀속하지 않는다. 지도 중심선과 가까운 것도 차체 외곽의 벽·페인트 여유, 같은 물리 경계, 경로 지시 소비, 실물 주행을 입증하지 않는다. 두 실행 모두 `left:60` 교차로 완료 0건이며 `obstacle_ahead` HOLD로 끝났다.
