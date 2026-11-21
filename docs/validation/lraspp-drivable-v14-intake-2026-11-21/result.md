# LRASPP drivable v14.0.01: manifest와 intake

2026-11-21 KST. 11/16에 학습한 LRASPP_r v2 분할 모델에 `rosy.perception.model/1` manifest를 붙이고 개인 노트북에서 intake를 돌렸다. 로봇 전달(`deliver.py push`), Pi 5 지연 측정, Gazebo·실물 주행은 하지 않았다.

## 모델

| 항목 | 값 |
|---|---|
| revision / version | `v14-drivable-20261116-16bb1c85` / `v14.0.01` (D-558) |
| 구조 | LRASPP_r. drivable을 별도 헤드 없이 클래스로 직접 학습했다 (v13의 동결 차선 모델 + 헤드 방식과 다르다) |
| 파일 | `model_fp32.onnx` 13.0 MB (sha256 `16bb1c85…`), `model_int8.onnx` 3.7 MB (sha256 `a77bce58…`, ONNX Runtime 정적 QDQ). 가중치는 git에 넣지 않는다 (D-356) |
| 입력 | 240×320 프레임의 행 112–239 → `[1,3,128,320]`, RGB, /255. manifest `input.crop` |
| 출력 | `logits` `[1,8,128,320]`, `nchw_logits` |
| 학습 | 시드 3개(42, 1, 2) 중 시드 1, 75 epoch, train 2,101 / val 483장, 검증 mIoU 0.928 |
| 증강 | v1 조명 증강에 밝기 ×0.6–1.4, 채도 ×0.6–1.4를 더했다 (`--aug v2`) |
| 자료 | `geg6-final_all` 2,806장, 전 프레임 사람 검수. content sha256 `652f375a…`는 `manifest.json`·`images/`·`masks/` 파일마다 `상대경로<TAB>sha256` 줄을 정렬해 해시한 값이다 |

v1(`v14-drivable-20261114-b68c0084`, `v14.0.00`)은 구조·자료가 같고 밝기가 바뀌면 약하다(밝기 ×0.5에서 mIoU 0.567, v2는 0.921). 원장에 `retired`로 적었다.

## 클래스 role

| index | 이름 | role | 로봇에서의 처리 |
|---:|---|---|---|
| 0 | background | background | |
| 1 | lane_left | lane_marking | `lane_mask`가 이 이름으로 D-576 경계 규칙을 적용한다 |
| 2 | lane_right | lane_marking | 위와 같다 |
| 3 | crosswalk | ignore | 길 계산에서는 지나갈 수 있는 바닥이다. `runner.infer_drivable`이 이 이름의 마스크를 따로 넘긴다 |
| 4 | speed_bump | ignore | crosswalk와 같다 |
| 5 | drivable | drivable (`current_road_region/1`) | 갈 길을 계산한다 |
| 6 | parking_zone_line | ignore | 이 이름을 쓰는 코드가 아직 없다. 처리 로직이 생길 때까지 지나갈 수 있는 바닥으로 둔다 (2026-11-21 사용자 결정) |
| 7 | lane_guide_line | ignore | 위와 같다 |

**crosswalk 주의:** 학습 자료의 crosswalk 픽셀이 0개다(`final_all/manifest.json` pixel_counts). 그래서 이 모델의 횡단보도 마스크는 항상 비어 있고, 횡단보도 감속·정지를 학습 모델에 기대면 안 된다.

## intake 결과

명령: `python learning/registry/perception/intake.py <model folder> --out <scratch>`. tool commit `e106ee65`, `intake_gate.yaml` 기본값(eval set 없음). 원본: [intake_report.json](intake_report.json), [model_manifest.json](model_manifest.json).

| 항목 | 결과 | 기준 |
|---|---:|---:|
| 판정 | **PASS** | |
| replay 프레임 (`data/teleop/learning/*.mp4` 7개) | 1,381 | |
| NaN / 오류 프레임 | 0 / 0 | 0 |
| visible 비율 | 0.996 | ≥ 0.30 |
| 지연 p50 / p95 (노트북 CPU, fp32) | 19.4 / 27.1 ms | ≤ 400 ms |
| 규칙 기반 검출기와의 error 차이 median / p95 | 0.345 / 0.766 | 기준 없음 |

replay 영상은 2026-09-19 촬영본이라 geg6 코스와 다를 수 있다. error 차이는 참고값이고 판정에 쓰지 않는다.

## 남은 일

- Pi 5에서 fp32·int8 실측. README 추정치는 fp32 약 70 ms, int8 약 40–50 ms다. manifest에 두 파일이 모두 있으면 runner는 fp32를 연다.
- `deliver.py push <robot> v14-drivable-20261116-16bb1c85`로 shadow 슬롯에 넣고 기록을 비교한다. 실물을 움직이는 paint 슬롯은 따로 승인을 받는다.
- 고정 eval set(D-379)에서 v13 후보와 비교한다.
