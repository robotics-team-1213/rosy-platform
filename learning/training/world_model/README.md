# World 모델 M1 학습

D-782의 첫 모델이다. 현재 관절·집게 상태(normalized)와 다음 `horizon` step의 controller reference를 받아
다음 `horizon` step의 상태를 예측하는 bootstrap ridge ensemble이다. member 간 불일치를 불확실성으로 쓴다.

```text
python learning/training/world_model/m1_job.py <world-model-dataset> --out <새-run> --members 5 --ridge 1.0 --seed 7820
```

- 입력은 `learning/curation/omx/world_model_dataset.py`가 만든 dataset이다. train split만 쓰고 정규화도 train에서만 계산한다.
- 출력 `artifact.json`은 `rosy.world-model-artifact.v1`이며 dataset 바이트의 SHA-256과 자기 digest를 담는다.
- `train-report.json`의 train MAE는 학습 데이터 위의 값이다. 수용 판단은 `learning/evaluation/world_model/m1_eval.py`가 한다.
- 학습은 승격·그림자·배포가 아니다. 같은 seed와 dataset이면 같은 digest가 나온다.
