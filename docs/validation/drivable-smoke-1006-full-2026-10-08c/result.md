# 10/6 두 원본 영상의 주행영역 smoke 출력 (2026-10-08c)

**판정: HOLD, 후보 진단만.** 10/7 [207프레임 기록](../drivable-smoke-1007-full-2026-10-08b/result.md)에 이어 10/6 두 영상 3,129프레임을 시험 헤드로 읽었다. 사람이 검수한 픽셀 정답이나 같은 물리 경계 ID가 없으므로 이것은 IoU·주행 성공률·논문 `R_F/R_M`이 아니다.

## 출처와 재현

- 시험 ONNX revision `lane-seg-20261007-b389d6a0`은 고정 차선 모델에 주행영역 헤드를 붙인 20장 smoke 데이터의 산출물이다. 모델 SHA-256: `b389d6a0690fec9bfa5f5a2db1f0ada56eb68ea58b0e747ff9afa3a028a6b145`. 모델 출력 역할에 `wall`은 없다. `wall_fraction=0`은 벽이 없다는 관측이 아니다.
- 10/6 `082612Z` MP4 2,487장 SHA-256: `e6c3785b4cbc0cbd8f81ce4b09b1202ec4c15792981ee803628becef5949dd13`.
- 10/6 `091340Z` MP4 642장 SHA-256: `cb4eb6d39c24a6a0cc4ad5adee615b0e21ef2ef781f6b8d68aa89fe9fff3c491`.
- MP4와 같은 프레임 수의 sidecar `teleop_rosy_26_*.jsonl`은 카메라 index·stamp와 촬영 당시 `line/keep_debug`를 담는다. X: `projects/rosy-platform/2026-10-08--045427--lane-evidence-learning--e0687b/evidence/recordings/`의 `source-readback-1006.json`, `conversion-readback-1006.json`이 원본 MCAP과 변환 파일 해시를 기록한다. 촬영 당시 keeper는 threshold paint를 썼으며 이 시험 헤드를 사용하지 않았다. 두 녹화의 운전 intent는 모두 승인된 `MANUAL/manual`이다([계보 분석](../../plans/2026-10-08-lane-papers-contract-fit.md)).
- [full_1006.py](evidence/full_1006.py)는 ffmpeg RGB 스트림을 순서대로 읽고, 모델·MP4 해시, 프레임 index·개수, logits shape와 finite 값을 검사한다. 출력의 `argmax` class 5를 화면 하단 40%(`y=144..239`)에서 집계했다. Windows Python 3.12, onnxruntime 1.30.0, numpy 2.5.3으로 실행했다. [summary.json](evidence/summary.json), [per_frame.jsonl](evidence/per_frame.jsonl)에는 수치와 원본 frame stamp가 있다. 요약 JSON SHA-256: `c6ec220a9385425bac97bb7f2d3a2dabaeae7eca98992967c5abfd1e694845aa`. 프레임 JSONL SHA-256: `6bca79ca720eb23677b283982a284e9e14ef7b9808aed30362f69da0c6293198`.
- [sample_1006.py](evidence/sample_1006.py)로 원본·후보 overlay 6장을 X: `DevTemp/rosy-drivable-candidate-20261008/full-1006/samples/`에 만들었다. 영상 화소·가중치는 공개 저장소에 넣지 않았다. 이 overlay는 D-475 평가 workspace에 표시하거나 정답 초안으로 사용하지 않는다.

## 관찰

| 영상 | 실제 keeper 출력 | 하단 drivable 비율 min/median/max | `none` 중 >50% | 전체 <2% |
|---|---|---:|---:|---:|
| `082612Z` 2,487장 | `none` 2,483, 한쪽 4 | 21.3% / 54.8% / 96.2% | 1,506/2,483 | 0 |
| `091340Z` 642장 | `both` 190, 한쪽 354, `none` 98 | 53.7% / 70.6% / 89.6% | 98/98 | 0 |

긴 영상에서 움직임으로 분류된 `keeper none` 138장 중 60장, 짧은 영상에서는 32장 중 32장에 하단 drivable >50%가 동시에 있었다. 짧은 영상의 `none` 구간 중앙값 68.2%는 `both` 구간 63.8%보다 높다. 이는 별도 시스템 출력의 **동시 발생**일 뿐, `none`이 정답이거나 마스크가 잘못됐다는 판정은 아니다. 촬영 당시 차선 보정이 검증되지 않았고 keeper `none`도 실제 차로 정답이 아니다.

원시 인접 마스크 IoU의 중앙값은 긴 영상 0.991, 짧은 영상 0.999였다. 긴 영상은 대부분 정지해 같은 이미지가 반복된다. 높은 겹침은 정확도나 가림 복원 근거가 아니며, 같은 경계 ID를 검수하지 않은 이 수치를 논문의 `R_F/R_M`으로 부르지 않는다.

시각 후보: 긴 영상 884번은 벽을 마주한 채 선 쌍이 보이지 않는 화면에서 하단 96.2%가 녹색이고, 짧은 영상 630번은 벽과 가로 표식 앞에서 89.6%다. D-475 §8의 벽 정면에는 drivable이 없다는 정의와 충돌할 가능성이 커 사람의 원본 판독이 필요하다. 긴 영상 2129번(21.3%)은 과노출·근접 가림이 심해 픽셀 정답 판단에 부적합한 후보이다. 192번은 물체 받침 주변을 넓게 칠하므로 가림 화소를 별도로 검수해야 한다. 이 후보 선택은 모델 출력을 보고 했으므로 **고정 평가 세트가 아니다**.

## 다음 게이트

모델 출력 면적이나 출력 지속성으로 경계 수용·진입 허가·STOP 해제를 하지 않는다. D-475 기준의 사람이 승인한 보이는 바닥/unknown 마스크와 같은 물리 경계 ID가 있는 장면을 먼저 확보하고, 벽·분기 음성 및 직선·곡선·한쪽 선 소실 양성을 분리 평가한다. 카메라 보정과 지도 자세, Pi 추론 지연, 재생·시뮬레이션·실물 수용은 별도 게이트다. CORE 단일 최종 `/cmd_vel` 권한은 유지한다.
