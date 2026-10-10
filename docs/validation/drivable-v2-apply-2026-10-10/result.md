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

## 카메라 실시간 읽기 — 2026-10-10

- 두 로봇 모두 `rosy-camera`와 같은 ROS domain·CycloneDDS 설정으로 `/line/keep_debug`를 구독했다. 9dfk는 연속 8프레임 모두 `paint_source_used: learned_drivable`, `paint_model_revision: lane-seg-20261010-451f0f85`였다. 8kcn은 8프레임 중 5프레임에서 같은 revision을 확인했고, 처음 3프레임은 revision이 null이었다. 설치용 revision의 ONNX SHA-256은 위 원본 v2와 같다. 따라서 위의 "실제 프레임 사용 HOLD"는 해소됐지만, 8kcn의 프레임별 사용률과 지연은 아직 수용되지 않았다.
- 9dfk의 사용 프레임 `paint_mask_age_s`는 0.248–0.499초, 8kcn은 0.495–0.875초였다. 이 표본은 정지 상태 1초가량의 짧은 관측이다. 양쪽 모두 `paint_reuse: warped`, `strategy: drivable_centre`였고 `paint_drivable.reason: ok`를 반환했다. 주행 중 지연이나 정확도의 증거는 아니다.
- `/line-follow/perception`의 `model_revision`은 paint가 아닌 shadow를 읽는다. 9dfk shadow는 `lane-seg-20261006-28e8454d`, 8kcn shadow는 `v13-drivable-20261010-86c86e7f`로 유지했다. 8kcn의 이 API가 보고한 unsigned 오류도 그 shadow 모델에 대한 것이다. v2 설치용 paint 폴더에도 서명 파일은 없다. 차선 모델의 현재 런타임은 이를 경고로 처리하며 추론은 실행됐지만, 서명과 운영 승격은 별개다.
- 두 로봇의 CORE는 확인 시 `IDLE`, line-follow `OFF`, 속도 0, E-Stop false였다. 목적지 navigation 능력은 둘 다 `goal_navigation: false`다. 사용자가 말한 navigation은 차선추종을 뜻한다. D-378의 후보별 R0 재생·폐루프, R1 그림자, 현장 감독·누르는 동안 조건이 미완료라 CAMERA_LINE 전환과 주행 명령은 보내지 않았다.
