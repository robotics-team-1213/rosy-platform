# 10/6–10/7 drivable smoke head 후보 출력 (2026-10-08)

**판정: HOLD.** 10/7 단일 프레임 후보의 출력 형태를 확인했다. 이 기록은 사람 정답, IoU, 연속 프레임 안정성, 주행 허가가 아니다. [D-475](../../adr/D-475-human-reviewed-fixed-eval-truth.md) §7에 따라 모델 출력을 평가 정답 초안이나 검수 앱의 입력으로 쓰지 않았다.

## 출처와 재생 방법

- 모델 PC의 시험 산출물: `~/rosy-ml/scratch/v11-drivable-head/out/model.onnx`, `model_manifest.json`, `drivable_head_run.json`. 모델 revision `lane-seg-20261007-b389d6a0`; ONNX SHA-256 `b389d6a0690fec9bfa5f5a2db1f0ada56eb68ea58b0e747ff9afa3a028a6b145`. 고정 차선 모델 revision은 `lane-seg-20261006-5f5ddcd9`이다.
- 모델 학습/검증 데이터는 `sam3-road-091340Z-smoke` revision `38cc567d11baea4e62b94c1547fe0217a8cbc4fcc44ef6f66e68d43c08d55718`, 총 20장(train 15, val 5). 기록된 val drivable IoU `0.5779127313`은 이 작은 smoke 분할에만 해당한다. D-475의 사람 검수 평가 점수가 아니다.
- 영상 입력은 X: `projects/rosy-platform/2026-10-08--045427--lane-evidence-learning--e0687b/evidence/human-review-candidates/`에서 추린 10/6–10/7 원본 추출 PNG 8장(320×240). MCAP 출처/변환 해시 및 후보 프레임 선정 이유는 같은 X:의 `evidence/recordings/{source-readback.json,conversion-readback.json}`과 `evidence/human-review-candidates/README.md`에 있다. 각 PNG SHA-256은 [report.json](evidence/report.json)에 기록했다.
- Windows Python 3.12, onnxruntime 1.30.0, numpy 2.5.3, Pillow 12.3.0으로 [candidate_infer.py](evidence/candidate_infer.py)를 실행했다. 입력은 manifest의 RGB, `1/255`, NCHW를 따랐다. ONNX 해시와 입력/출력 shape, finite logits를 검사했다. 이미지는 모델 크기와 같아 리사이즈가 없었다. `argmax` class 5를 drivable로 집계했다. near는 화면 하단 40%(`y=144..239`)다.
- 원본·overlay·mask는 X: `DevTemp/rosy-drivable-candidate-20261008/candidate-output/`에만 있다. 공개 저장소에 영상 화소를 넣지 않았다. 로컬 `report.json` SHA-256은 `ca527959b9a9b98286777b84078935db99192bacbd3572b97b1673fc30d1be5a`다.

## 관찰

| 프레임 | 하단 40% 중 drivable | 판독 |
|---|---:|---|
| 10/7 `143038Z` 0 | 93.8% | 바닥 대부분을 칠한다. 양 경계 적합성은 미확정. |
| 10/7 `143038Z` 20 | 83.9% | 한쪽 경계 소실·횡단 표식 후보에서도 넓게 칠한다. |
| 10/7 `143038Z` 35 | 79.2% | 경계의 좌우 분류 전환 후보에서도 넓게 칠한다. |
| 10/7 `143038Z` 80 | 52.8% | 분기·횡단 표식 후보에서 진입 가지는 구분하지 않는다. |
| 10/7 `143038Z` 123 | 83.3% | false-boundary 후보에도 넓게 칠한다. |
| 10/7 `143211Z` 55 | 73.9% | 기존 경계 재생은 STOP이지만 원형·분기 표식 주변을 칠한다. |
| 10/6 `091340Z` 190 | 70.6% | 분기·장애물 받침 후보에서도 넓게 칠한다. |
| 10/6 `091340Z` 448 | 73.1% | **벽을 향한 STOP 후보**에서 전경 바닥 대부분을 칠한다. D-475 §8의 “벽을 마주한 장면에는 drivable이 없다”와 충돌할 가능성이 높다. 사람 확인 전에는 오류 후보로만 둔다. |

10/7 `143211Z` 55와 10/6 `091340Z` 448의 넓은 마스크는 현재 재생의 STOP과 동시에 나타난다. 따라서 **주행영역 화소가 많다는 이유로 STOP을 해제할 수 없다.** 해당 프레임은 모델의 벽·분기 음성 검수 우선순위다. 선을 따라가는 조향과 진입 가능 공간을 분리해야 한다.

## 한계와 다음 게이트

8장은 선택된 정지 영상이며 전체 10/6–10/7 프레임의 실패율이 아니다. 사람 검수 마스크, 동일 물리 경계 ID, 보정·지도 정합, Pi 지연, 연속 miss/flicker, 실물 주행 검증이 없다. `drivable_head.py`의 직접 학습 CLI는 현재 검수 승인 admission을 강제하지 않으므로 이 smoke 성적을 승격 근거로 쓰지 않는다. D-475의 평가 workspace에는 이 overlay를 표시하지 않는다. 별도의 사람이 정한 벽·분기 음성 및 보이는 바닥 픽셀 정답이 생긴 뒤 고정 세트에서 비교한다. CORE 단일 `cmd_vel` 경계와 불확실할 때 STOP은 유지한다.
