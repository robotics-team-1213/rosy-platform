# OMX 실행 전 검사기 (D-782)

후보 행동 묶음이 무엇을 할지 예측하고, **멈출 근거가 있는지**만 답한다.

| verdict | 뜻 | 기존 gate에 주는 영향 |
|---|---|---|
| `REJECT` | 예측 상태가 설정한 normalized 한계를 벗어남 | 멈출 근거 |
| `HOLD` | ensemble 불일치가 `hold_sigma`보다 큼 | 멈출 근거 |
| `NO_OBJECTION` | 예측상 한계 위반 없음 | **없음. 허가가 아니다** |
| `ABSTAIN` | 입력 만료·rig/보정 불일치·horizon/주기 불일치·학습 범위 밖 | 없음 |

## 그림자 재생

```text
python operations/prediction/world_model/shadow.py <world-model-dataset> --artifact <run>/artifact.json --digest <승인-digest> --out <새-replay>
```

dataset의 eval window마다 검사기를 돌리고, 시도별로 멈춤 판정이 있었는지를 사람 라벨(성공/실패)과 대조한다.
재생은 입력 나이를 0으로 두므로 실시간 만료는 시험하지 않는다.

## 단계

| D-782 단계 | 이 폴더 상태 |
|---|---|
| W3 그림자 | 검사기·기록·오프라인 재생 구현. 실물 실행 옆에서 기록하는 결선은 아직 없음 |
| W4 veto | 미결선. 사용자 승인, D-430 Safety 리뷰, D-773 A4 필요 |
