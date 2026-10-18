# 10/7 원본 영상: odom 경계 충돌 후보의 재생 비교

> **포팅 메모 (2026-10-13):** 이 기록은 원 브랜치 `fix/lane-odom-cross-veto`의 구현(keeper 내장)으로 2026-10-09에 낸 결과다. 현재 main의 재생 도구는 `learning/evaluation/perception/road_replay.py`이고 후보는 `--odom-veto`를 줄 때만 켜진다. 포팅한 구현(`control/keep_odom_veto.py`)으로 다시 재생하지 않았다.

**판정: 효과 미확인, HOLD.** D-556의 기본값은 꺼짐이다. 이 기록은 후보 코드의 재생 출력 비교이며 물리 경계 ID나 주행 수용 판정이 아니다.

## 입력과 방법

- 후보 출발점: `2c4d97b80` (`fix/lane-odom-cross-veto` 작업 트리). 비교 대상은 같은 날 로컬 `main`의 `road_replay.py` 출력이다.
- 원본: 10/7 `teleop_rosy_60_20261007T143038Z.mp4` (124프레임, SHA-256 `34a121783a34b5ffe38a8f291a246604358acaba48795c1be475aed30729b859`)와 `teleop_rosy_60_20261007T143211Z.mp4` (83프레임, SHA-256 `76604d0d3186a6e26ab57d3c0f360c976ffc483dc65f7405a12756ed956ba3fc`). 로컬 입력은 `X:\DevTemp\projects\rosy-platform\2026-10-08--045427--lane-evidence-learning--e0687b\evidence\recordings\video`에 있다.
- 각 코드 위치에서 `python learning/training/perception/road_replay.py <mp4> --out <X:\DevTemp\lane-odom-veto\base38|cand38|base11|cand11>`로 돌렸다. sidecar JSONL의 odom을 후보 keeper에 전달했다. 출력 `metrics.json`과 `frames.jsonl`을 영상별로 비교했다.
- `--recorded-ground`는 첫 프레임의 `line/keep_debug`가 없어 실행을 완료하지 못했다. 아래 값은 **명목 지면 투영**이고 실측 경계 정확도가 아니다.

## 관측

| 영상 | 비교 프레임 | baseline 대비 후보의 `frames.jsonl` 차이 | baseline 대비 `metrics.json` 차이 | 기존 출력 |
|---|---:|---:|---:|---|
| `143038` | 124 | 0 | 0 | keeper `none_rate` 0.113, `on_paint_rate` 0.127; road STOP 100% |
| `143211` | 83 | 0 | 0 | keeper `none_rate` 0, `on_paint_rate` 0.012; road STOP 100% |

따라서 D-556의 합성 교차 사례는 SOURCE 회귀를 막지만 이 207프레임의 문제는 줄이지 못했다. `road_replay`의 `validated`는 거짓이고 동일 물리 경계·벽·분기 판정의 사람 정답은 없다. odom 일치나 마스크 면적을 주행 허가로 사용하지 않는다.

## 다음 검증

Fleet이 고른 경로·장소 지시는 유지하면서 CORE가 유효 기간과 지도 자세를 확인한 경로 문맥을 인식에 주는 D-531을 우선 검증한다. 차선 공백에서는 최근 확실한 동일 차로, 짧은 odom 예측, 진행할 간선의 방향, 신선한 몸 경로 여유가 함께 성립할 때만 D-476의 제한된 bridge 후보가 된다. 경계 ID 충돌·벽·분기·위치 미확정이면 정지 상태에서 원래 trip과 진단을 보존하고 재획득이나 재정착 후 계획을 다시 평가한다. 이 문단은 제안이며 구현·SIM·DEVICE/FIELD 수용은 없다.
