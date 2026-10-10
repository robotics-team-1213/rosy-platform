# D-614 crop128 v2 적용 기록 — 2026-10-10

## 결정과 입력

- 사용자: v2 후보를 바로 적용하고 ADR로 결정. 대상은 9dfk와 8kcn 모두.
- 결정: [D-614](../../adr/D-614-drivable-crop128-v2-immediate-paint.md). 모델 PC 원본은 `~/rosy-ml/candidates/drivable-v13-crop128-20261010-v2`; 64개 파일의 `SHA256SUMS` 검사 통과.
- 원본 ONNX SHA-256: `451f0f85b390d6601dc38c60865ed721936ff407845f7a8196099ae9a110f3d2`.
- 모델 PC에서 별도 시험 패키지 `lane-seg-20261010-451f0f85` 생성. ONNX 바이트는 그대로, 매니페스트 revision과 필수 `camera_profile_revision: unknown-provisional`만 추가했다. 전달본 `input.crop.note`는 설치 로더가 거절하여 `notes.crop_mapping`으로 옮겼다. `input.crop`의 실행 필드는 `{from_frame:[240,320], rows:[112,240]}`이다.
- 모델 PC ONNX Runtime CPU 예열: 입력 `[1,3,128,320]`, 출력 `[1,6,128,320]`, 모두 유한값. 로봇 설치 로더도 양쪽에서 이 매니페스트와 모델을 열었다.

## 장치 적용

| 로봇 | 적용 전 CORE | 설치·포인터 | 적용 후 |
|---|---|---|---|
| 9dfk | `IDLE`, line-follow `OFF`, 속도 0, trip lease·activity 없음, E-Stop false | `/var/lib/rosy/models/paint` → `lane-seg-20261010-451f0f85`; `paint.previous` → `lane-seg-20261010-71edcb6d` | ONNX SHA 일치; `rosy-camera`·`rosy-core` active; `rosy-camera` 계정 `LaneSegModel.open` 통과 |
| 8kcn | `IDLE`, line-follow `OFF`, trip lease·activity 없음, E-Stop false; 속도 표본은 선속도 −0.00064 m/s, 각속도 0.01319 rad/s | 같은 새 포인터·이전 포인터. 0.001 rad/s 기준으로 첫 시도는 쓰기 전에 중단했고, line-follow 명령 0과 두 번의 정지 표본(선속도 <0.005 m/s, 각속도 <0.03 rad/s)을 확인해 다시 적용 | ONNX SHA 일치; `rosy-camera`·`rosy-core` active; `rosy-camera` 계정 `LaneSegModel.open` 통과 |

두 로봇 모두 모델 저장소 `.lock`을 잡고, 해시·로더를 검사한 뒤 새 폴더를 설치했다. 현재 paint를 원자적으로 바꾸기 전에 이전 경로를 `paint.previous`에 썼고 `history.jsonl`에 `push-paint-d614`를 남겼다. `shadow`·`active`는 바꾸지 않았다. E-Stop 해제, 모드 전환, 주행 명령은 없었다.

## 남은 증거

- 로봇 API의 `GET /line-follow/perception`은 9dfk에서 `applied: false`, `applied_model_revision: null`을 반환했다. 이 화면의 `model_revision`은 shadow 쪽 이전 모델로, paint 포인터의 새 추론 증거가 아니다. 카메라 로그에서도 새 revision을 확인하지 못했다. **실제 프레임에서 새 모델이 사용됐는지는 HOLD**다.
- 팀 README의 hard-frame test 개선(선 밖 오검 13.9% → 1.7%)은 제공된 평가다. ROSY 독립 재생·폐루프 SIM, Pi 실측 지연, `paint_source_used`/`paint_model_revision` 비율, 실물 R1/R2 수용은 별개다. 새 모델을 설치했다는 사실로 주행 안전이나 성능을 승인하지 않는다.
- 복귀 대상은 각 로봇의 `paint.previous`에 남은 `lane-seg-20261010-71edcb6d`다. 실패 또는 관문 미달 때 포인터를 이 경로로 되돌리고 실제 읽기를 다시 확인한다.
