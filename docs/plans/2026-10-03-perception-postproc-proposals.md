# 인식 후처리 제안 — D-408 학습 페인트 마스크에 연결 성분 면적 문턱

**상태:** 제안. 코드는 바꾸지 않았다. **담당:** lane keep 세션(`lane_keep*.py`, `line_observer_node._paint_for`, `tools/lane_replay.py`의 소유자).

**근거:** 2026-10-02 후처리 감사 3번 항목. 같은 감사의 1·2·4·5번 항목은 가지 `fix/perception-postproc-nms`에서 고쳤다([D-395](../adr/D-395-fleet-assisted-localization.md) 개정 11, `src/runtime/sensing/logs.md`). 이 항목은 주행 경로라서 소유 세션에 넘긴다.

## 지금 동작

- `paint_source=denoise`이면 `denoise_white_mask`가 8-연결 성분 40 px 미만을 버린다(`lane_keep_lines.DENOISE_MIN_AREA_PX`).
- `paint_source=learned`이면 `_paint_for`가 `paint_worker.latest()`의 `lane_marking_mask`를 거르지 않고 `LaneKeeper.update(paint_mask=...)`에 넘긴다.
- 그림자 근거(`learned/lane_mask.lane_evidence`)는 이번 가지에서 같은 40 px 문턱을 얻었다(`MIN_COMPONENT_PX`). 페인트 경로만 아직 문턱이 없다.

## 측정 (133221Z, 260장)

D-379 자동 라벨 마스크를 모델 출력 대신 쓰고 잡음 모형을 씌워 실제 `LaneKeeper`에 넣었다. 잡음 모형은 다음 셋이다.
- 2–3 px 반점, 밀도 0.2 %
- 페인트 픽셀의 2 %에 5×5 구멍
- ±1 px 침식 또는 팽창

| 변형 | 선 2개 이상인 쪽 /100장 | 같은 쪽 중복 /100장 | 가로선 나온 장 | 오차 흔들림 평균 / p95 | 방향 흔들림 |
|---|---|---|---|---|---|
| 깨끗함 | 5.0 | 0 | 59 | 0.058 / 0.213 | 3.74° |
| 잡음 | 7.3 | 0 | 62 | 0.059 / 0.190 | 4.68° |
| 잡음 + 면적 문턱 | 6.2 | 0 | 57 | 0.058 / 0.192 | 4.18° |
| 잡음 + 면적 문턱 + EMA | 6.2 | 0 | 57 | 0.049 / 0.189 | 4.18° |

- 기대 효과는 작다. 여분 선과 가로선이 약 10 % 준다. 방향 흔들림은 4.68° → 4.18°다.
- 124745Z(81장)에서는 잡음 + 면적 문턱이 깨끗함과 같은 줄 수·전략 분포로 돌아왔다(오차 흔들림 0.065 → 0.053).
- 깨끗한 라벨의 가로선(260장 중 59장, 81장 중 11장)은 실제 정지선 페인트다. D-379 라벨에는 stop_line·crosswalk 픽셀이 0개이고 정지선이 `lane_line`으로 칠해져 있다. 그래서 거짓 정지선 비율은 이 자료로 잴 수 없다.

## 제안

1. 학습 마스크가 `LaneKeeper`에 들어가기 전에 `denoise` 경로와 같은 8-연결 40 px 문턱을 건다. 걸 자리는 `_paint_for`의 learned 갈래나 `paint_worker` 출력 중 소유 세션이 고른다. 문턱은 `DENOISE_MIN_AREA_PX` 하나를 함께 쓴다.
2. 판정은 replay bench로 한다(D-205). `paint_source=learned`에서는 주행이 바뀌기 때문이다. 이 표는 자동 라벨에 합성 잡음을 씌운 것이지 실제 모델 출력이 아니다. onnxruntime이 있는 곳(D-373 learned site)에서 실제 logits로 `lane_sim.py`를 다시 돌린다.
3. 오차 EMA는 넣지 않는다. 평균 흔들림은 16 % 줄지만 p95는 거의 그대로다. 그리고 `smoothing=0.5`와 쪽 추적 위에 지연을 더한다.
4. (θ, ρ) 선 NMS도 넣지 않는다. 341장에서 같은 쪽 근접 중복(dy < 4 cm, dheading < 10°)이 깨끗한 자료와 잡음 자료 모두 0이었다.

## 재현

- 스크립트와 원 출력: `X:\DevTemp\rosy-nms-audit\lane_sim.py`, `lane_sim.out`, `report.md`(저장소 밖)
- 자료: `data/perception/store/datasets/d379-auto-lanes/*/masks`(gitignored)
