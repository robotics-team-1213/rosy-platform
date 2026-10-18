# World 모델 오프라인 평가

```text
python learning/evaluation/world_model/m1_eval.py <world-model-dataset> --artifact <run>/artifact.json --out <새-eval> [--split eval|test]
```

D-782 §6 기준이다. horizon의 **모든 step**에서 다음 두 기준선을 모두 이겨야 `pass`다.

| 기준선 | 예측 |
|---|---|
| hold | 다음 상태 = 현재 상태 |
| reach | 다음 상태 = 그 step을 구동한 controller reference |

`eval-report.json`에는 step별 MAE(model/hold/reach), 기준선 승리 여부, ensemble 2σ 구간의 실제 포함률이 들어간다.
포함률은 보고만 하고 판정에는 쓰지 않는다. exit code는 pass 0, reject 3이다.
`pass`는 오프라인 근거일 뿐 승격·그림자·실사용 수용이 아니다.
