# OMX ACT optimizer 진단과 수정

실제 RGB 시연 25개 입력 검증은 [입력 보고서](../omx-object-rgb-truth-2026-10-21e/result.md)에 기록했다.
첫 실제 10,000 step 모델은 재적재에 성공했으나 검증 MAE 0.2840533379436038rad로,
상수 기준 0.29584911500909206rad에 가까웠다. 이 모델은 native 과제에 선택하지 않았다.
이 보고서 시점 learned native calibration과 과제 시작은 각각 0건이다.

## 실제 자료의 제한 진단

동일 train 20/validation 5 episode에서 각각 균등 간격 64개 실제 RGB frame을 읽었다.
train 1,280 / validation 320 frame, seed 42750, 조건별 1,000 optimizer step,
동일 초기 가중치와 batch 생성기를 사용했다. 정규화는 원 train 20개 기준이다.
이 실험은 deployable policy를 내보내지 않았으며 물체 과제 성공률이 아니다.

| 조건 | main/backbone lr | 최종 100 loss 평균 | validation MAE rad | 현재 관절 대비 예측 step >0.04rad 비율 |
|---|---|---:|---:|---:|
| 기존 단일 그룹 | 0.001 / 0.001 | 0.35948856 | 0.11716758 | 98.75% |
| ACT 공식 그룹 | 0.0001 / 0.00001 | 0.03495144 | 0.01442761 | 29.6875% |
| 설치본 기본 lr·공식 그룹 | 0.00001 / 0.00001 | 0.05582447 | 0.01785697 | 62.1875% |

실제 `result.json` SHA256:
`85929822df1aac79aca20f290aaf340a7e5e4957362126aaed911ce84be84ee6`.
첫 모델의 실제 10,000 loss history SHA256:
`b0e8940e2ca5665db1db5827b41812d9cf380a3fedafbe710e6137a397f9a93b`.

공식 `ACTPolicy.get_optim_params()`를 사용하고 main lr 0.0001, backbone lr 0.00001로
수정했다. 실제 optimizer 그룹을 offline report에 기록하며 clip norm 1.0과 원본
입력·정답·시각·해시 검증을 유지한다. 원본 행동 출력을 보정하거나 native step 제한을
완화하지 않았다. 진단의 잔여 제한 초과 비율은 정식 재학습과 독립 과제가 필요함을 뜻한다.

## 검증

- RED `20a2f1e8d8`: MODEL pinned native ACT 실제 학습·재적재 fixture에서 optimizer lr
  `[0.001] != [0.0001, 0.00001]`로 실패했다.
- GREEN `bc94cadec587d846afdd882bf0610e91f36d2bd0`: 같은 실제 native 검사 1 PASS,
  별도 원격 `test_act_job.py` 15 PASS, known-failures 비교 모두 0 NEW.
- native 검사에는 기존 NumPy/torchvision deprecation warning 182건이 있었다.
  synthetic fixture 검사이며 물체 과제 증거로 계산하지 않는다.

동일 25개 원본의 새 10,000 step 실행을 시작했다. 그 결과, 선택 checkpoint,
새로운 물체 과제 20회와 18회 이상 성공 여부는 후속 실행 증거로 보고해야 한다.
