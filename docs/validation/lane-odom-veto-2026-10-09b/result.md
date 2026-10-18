# 10/7 D-556 재생 정정: 원본 MCAP의 odom을 사용

> **포팅 메모 (2026-10-13):** 이 기록은 원 브랜치 `fix/lane-odom-cross-veto`의 구현(keeper 내장)으로 2026-10-09에 낸 결과다. 현재 main의 재생 도구는 `learning/evaluation/perception/road_replay.py`이고 후보는 `--odom-veto`를 줄 때만 켜진다. 포팅한 구현(`control/keep_odom_veto.py`)으로 다시 재생하지 않았다.

**판정: 후보가 크게 바뀌지만 정확도 미확인, HOLD.** [앞선 MP4 비교](../lane-odom-veto-2026-10-09/result.md)의 차이 0은 MP4 sidecar에 odom 자세가 없어 D-556 조건을 시험하지 못한 결과다. `--compare-boundary`로 확인한 신선한 odom 프레임은 `143038` 0/124, `143211` 0/83이었다. 이전 기록의 “sidecar JSONL의 odom을 전달했다”와 “문제를 줄이지 못했다”는 결론을 철회한다.

## 입력과 재현

- 같은 녹화의 원본 MCAP `20261007T143038Z_rosy_60/bag/bag_0.mcap` SHA-256 `0d8b19042429368c12c8a76349873c7d83fc7dfaafe62ee4a97ffbc87bd4b7f76`, `20261007T143211Z_rosy_60/bag/bag_0.mcap` SHA-256 `287015247472833f8eae7c17e81cb33bd27c19fddc841d559804b10591c2d920`. 로컬 입력은 `X:\DevTemp\projects\rosy-platform\2026-10-08--045427--lane-evidence-learning--e0687b\evidence\recordings\`에 있다.
- 로컬 `main`과 `fix/lane-odom-cross-veto`에서 각각 `python learning/training/perception/road_replay.py <session-folder> --out <X:\DevTemp\lane-odom-veto\mcapbase38|mcap38|mcapbase11|mcap11> --compare-boundary`를 실행했다. 후보의 신선한 odom은 124/124, 83/83이다.
- `--recorded-ground`는 원본 MCAP 첫 프레임에 `line/keep_debug`가 없어 `missing line/keep_debug`로 멈췄다. 지면은 명목 투영이며 `validated=false`다.

## 출력 차이

| 세션 | 총 프레임 | 프레임 출력 차이 | baseline → 후보에서 `strategy` 변경 | keeper `none_rate` | road 상태 |
|---|---:|---:|---|---|---|
| `143038` | 124 | 81 | `right_only → none` 81 | 0.097 → 0.750 | 양쪽 모두 STOP 100% |
| `143211` | 83 | 59 | `right_only → none` 49, `left_only → none` 9, `both → none` 1 | 0 → 0.711 | 양쪽 모두 STOP 100% |

첫 변경 프레임은 각각 31, 24다. 후보의 충돌 래치는 뒤의 정상 영상처럼 보이는 프레임도 계속 HOLD하므로, **진짜 차선 침범 거부인지 과잉 정지인지** 이 숫자로 판단할 수 없다. 원본 MCAP에서 140/207프레임이 바뀐 사실은 활성화 근거가 아니라 사람의 동일 물리 경계·벽·분기 검수 우선순위다. 다음 검증은 D-475에 따라 그 구간의 물리 경계 ID, 바닥/벽, 로봇 위치를 독립 판정한 뒤 false HOLD와 unsafe FOLLOW를 나눠 센다. CORE bridge·호 주행, SIM 및 DEVICE/FIELD도 별도다.
