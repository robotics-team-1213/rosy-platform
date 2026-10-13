# 10/7 전체 207프레임 주행영역 smoke 출력 (2026-10-08b)

**판정: HOLD, 후보 진단만.** [8장 시각 확인](../drivable-smoke-1006-1007-2026-10-08/result.md)을 10/7 두 영상의 전 프레임으로 넓혔다. 이 값은 사람 검수 픽셀 정답, 차선 인스턴스 매칭, 논문의 `R_F/R_M`, 주행 안전성 점수가 아니다.

## 입력·재현

- 모델은 `lane-seg-20261007-b389d6a0` 시험 ONNX. SHA-256: `b389d6a0690fec9bfa5f5a2db1f0ada56eb68ea58b0e747ff9afa3a028a6b145`. 모델 PC `~/rosy-ml/scratch/v11-drivable-head/out/`의 사본을 X: `DevTemp/rosy-drivable-candidate-20261008/`에서 읽었다. 20장 smoke 데이터(학습 15, 검증 5)에서 나온 헤드이며 승인 모델이 아니다.
- X: `projects/rosy-platform/2026-10-08--045427--lane-evidence-learning--e0687b/evidence/recordings/video/`의 MP4 둘을 `ffmpeg -vsync 0`으로 순서대로 PNG 추출했다. `143038Z` 124장, `143211Z` 83장. 추출 프레임 20·55의 RGB 화소를 기존 후보 PNG와 비교해 동일함을 확인했다. MCAP→MP4 계보는 같은 X:의 `conversion-readback.json`·`source-readback.json`과 [원본 증명](../lane-1007-source-proof-2026-10-08/result.md)을 따른다.
- 첫 MP4 SHA-256: `34a121783a34b5ffe38a8f291a246604358acaba48795c1be475aed30729b859`.
- 둘째 MP4 SHA-256: `76604d0d3186a6e26ab57d3c0f360c976ffc483dc65f7405a12756ed956ba3fc`.
- 비교 재생은 X: `evidence/replay-1007-143038/frames.jsonl`(SHA-256 `8907621ecf6ff1d27633e3dd63bc44947de7364f3f5043c6137948ba7fa652b9`)과 `evidence/replay-1007-143211/frames.jsonl`(SHA-256 `b7f8a26fb53ec5355930cc6f6f8a8a1d6116ab847d3432b80beb9b7613317aa0`). 인덱스·개수가 각각 124·83으로 맞는다. 재생의 `validated=false` 제한은 유지된다.
- [full_1007.py](evidence/full_1007.py)는 manifest의 RGB/1÷255/NCHW를 사용하고 모델 해시·finite logits·shape·프레임 개수를 확인한다. `argmax` class 5를 화면 하단 40%(`y=144..239`)에서 집계했다. 출력은 [summary.json](evidence/summary.json)과 [per_frame.jsonl](evidence/per_frame.jsonl)이다. 원본 영상·추출 PNG·모델 가중치는 공개 저장소에 넣지 않았다. Windows Python 3.12, onnxruntime 1.30.0, numpy 2.5.3, Pillow 12.3.0.

## 관찰

| 영상 | 재생 RoadState | 하단 drivable 비율 min/median/max | STOP 중 drivable >50% | 2% 미만 |
|---|---|---:|---:|---:|
| `143038Z` 124장 | STOP 13, TRACK 111 | 46.3% / 79.4% / 93.8% | 13/13 | 0/124 |
| `143211Z` 83장 | STOP 83 | 55.2% / 73.9% / 83.5% | 83/83 | 0/83 |

연속 원시 마스크 IoU의 중앙값은 첫 영상 0.968, 둘째 0.959다. 카메라 이동을 워프하지 않았고 사람이 정한 동일 경계가 없으므로 이 값은 단지 **출력의 인접 프레임 겹침**이다. 높은 겹침은 올바른 위치나 진입 허가를 뜻하지 않는다. 이 사례에서 주행영역 비율만의 50% 문턱은 재생 STOP 96/96프레임을 모두 통과시킨다. STOP에는 경계·경로·분기 판단의 이유가 있으므로, 이 상관관계는 마스크 오류율이 아니라 **주행영역 면적이 STOP 판단을 대신할 수 없다는 증거**다.

## 다음 게이트

D-475의 사람 승인 마스크로 벽·분기 음성, 직선·곡선·한쪽 선 소실 양성의 보이는 바닥 IoU와 조향 중심 오차를 재야 한다. 같은 물리 경계 ID가 확보되기 전에는 `R_F/R_M`을 계산하지 않는다. 모델은 shadow 후보로만 두고, 경계 불확실 시 STOP과 CORE 단일 `/cmd_vel` 권한을 유지한다. 본 기록으로 학습 데이터 admission, Pi 실행 예산, 실물 로봇 수용을 통과했다고 주장하지 않는다.
